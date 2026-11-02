"""Evaluation harness (task VID-05).

Runs the real edge pipeline over every clip in the manifest, matches the alerts it raises against the
clip's expected events, and produces a scorecard per rule type:

  caught      expected events that got an alert inside [start - tolerance, end + tolerance]
  missed      expected events with no such alert
  false       alerts that match no expected event (including any alert from a must_not_fire rule)
  precision   caught / (caught + false)
  recall      caught / (caught + missed)
  false/h     false alerts per camera-hour of footage
  delay       seconds from the condition starting to the alert (mean)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from vision_edge.detection import Detector, build_detector
from vision_edge.ingest import DEFAULT_START, FileSource, ReplaySource
from vision_edge.pipeline import CameraPipeline
from vision_edge.sinks import MemorySink
from vision_shared.manifest import ClipEntry, ExpectedEvent, Manifest
from vision_shared.schemas import CameraConfig, Event, SiteConfig


@dataclass
class AlertRecord:
    rule: str
    rule_type: str
    at_s: float
    message: str


@dataclass
class ClipResult:
    clip_id: str
    duration_s: float
    frames: int
    wall_s: float
    alerts: list[AlertRecord] = field(default_factory=list)
    caught: list[tuple[str, float]] = field(default_factory=list)  # (rule, delay_s)
    missed: list[str] = field(default_factory=list)
    false_alerts: list[AlertRecord] = field(default_factory=list)
    rule_types: dict[str, str] = field(default_factory=dict)  # rule id -> type
    error: str = ""


@dataclass
class RuleTypeScore:
    rule_type: str
    caught: int = 0
    missed: int = 0
    false: int = 0
    camera_hours: float = 0.0
    delays: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        n = self.caught + self.false
        return self.caught / n if n else None

    @property
    def recall(self) -> float | None:
        n = self.caught + self.missed
        return self.caught / n if n else None

    @property
    def false_per_hour(self) -> float:
        return self.false / self.camera_hours if self.camera_hours else 0.0

    @property
    def mean_delay_s(self) -> float | None:
        return sum(self.delays) / len(self.delays) if self.delays else None

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_type": self.rule_type,
            "caught": self.caught,
            "missed": self.missed,
            "false": self.false,
            "camera_hours": round(self.camera_hours, 4),
            "precision": self.precision,
            "recall": self.recall,
            "false_per_hour": round(self.false_per_hour, 3),
            "mean_delay_s": round(self.mean_delay_s, 1) if self.mean_delay_s is not None else None,
        }


def _resolve(base: Path, ref: str | None) -> Path | None:
    if not ref or ref.startswith("s3://"):
        return None
    p = Path(ref)
    return p if p.is_absolute() else base / p


def run_clip(
    entry: ClipEntry,
    base_dir: Path,
    detector_kind: str = "auto",
    model: str | None = None,
    detector: Detector | None = None,
) -> ClipResult:
    camera = CameraConfig(
        id="cam",
        source=entry.detections or entry.file or "-",
        fps=entry.fps,
        zones=entry.zones,
        lines=entry.lines,
    )
    rules = [r.model_copy(update={"camera_id": "cam"}) for r in entry.rules]
    site = SiteConfig(id="eval", timezone=entry.timezone, cameras=[camera], rules=rules)
    start = entry.start_time or DEFAULT_START

    det_path = _resolve(base_dir, entry.detections)
    video_path = _resolve(base_dir, entry.file)
    use_replay = detector_kind in ("auto", "replay") and det_path is not None and det_path.exists()
    if use_replay:
        assert det_path is not None
        frames = ReplaySource(det_path, "cam", start_time=start)
        det: Detector = build_detector("replay")
    else:
        if video_path is None or not video_path.exists():
            return ClipResult(
                entry.id, entry.duration_s or 0, 0, 0, error="no detections cache and no video file"
            )
        kind = "rfdetr-nano" if detector_kind in ("auto", "replay") else detector_kind
        det = detector or build_detector(kind, model=model)
        frames = FileSource(video_path, "cam", fps=entry.fps, start_time=start)  # type: ignore[assignment]

    sink = MemorySink()
    pipeline = CameraPipeline(site=site, camera=camera, detector=det, sinks=[sink])
    stats = pipeline.run(frames)
    duration = entry.duration_s or stats.seconds_of_video

    result = ClipResult(
        entry.id,
        duration,
        stats.frames,
        stats.wall_seconds,
        rule_types={r.id: r.type.value for r in rules},
    )
    alerts = [_record(e, start) for e in sink.triggered]
    result.alerts = alerts
    used: set[int] = set()
    for exp in sorted(entry.expected, key=lambda e: e.start_s):
        idx = _match(exp, alerts, used)
        if idx is None:
            result.missed.append(exp.rule)
        else:
            used.add(idx)
            result.caught.append((exp.rule, round(alerts[idx].at_s - exp.start_s, 1)))
    result.false_alerts = [a for i, a in enumerate(alerts) if i not in used]
    return result


def _record(e: Event, start) -> AlertRecord:  # type: ignore[no-untyped-def]
    return AlertRecord(
        e.rule_id, e.rule_type.value, round((e.triggered_at - start).total_seconds(), 1), e.message
    )


def _match(exp: ExpectedEvent, alerts: list[AlertRecord], used: set[int]) -> int | None:
    lo, hi = exp.start_s - exp.tolerance_s, exp.end_s + exp.tolerance_s
    for i, a in enumerate(alerts):
        if i not in used and a.rule == exp.rule and lo <= a.at_s <= hi:
            return i
    return None


def score(results: list[ClipResult]) -> dict[str, RuleTypeScore]:
    scores: dict[str, RuleTypeScore] = {}
    for r in results:
        if r.error:
            continue
        for rtype in set(r.rule_types.values()):
            s = scores.setdefault(rtype, RuleTypeScore(rtype))
            s.camera_hours += r.duration_s / 3600.0
        for rule, delay in r.caught:
            s = scores[r.rule_types[rule]]
            s.caught += 1
            s.delays.append(delay)
        for rule in r.missed:
            scores[r.rule_types[rule]].missed += 1
        for a in r.false_alerts:
            scores[a.rule_type].false += 1
    return dict(sorted(scores.items()))


def run_manifest(
    manifest: Manifest,
    base_dir: Path,
    detector_kind: str = "auto",
    model: str | None = None,
    only: list[str] | None = None,
    tags: list[str] | None = None,
) -> list[ClipResult]:
    clips = [
        c
        for c in manifest.clips
        if (not only or c.id in only) and (not tags or set(tags) & set(c.tags))
    ]
    detector = None
    if detector_kind not in ("auto", "replay"):
        detector = build_detector(detector_kind, model=model)
    return [run_clip(c, base_dir, detector_kind, model, detector) for c in clips]


# --------------------------------------------------------------------------- reports


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def scorecard_markdown(
    results: list[ClipResult],
    scores: dict[str, RuleTypeScore],
    regressions: list[str] | None = None,
) -> str:
    lines = [
        "# Detection scorecard",
        "",
        "| Rule type | Caught | Missed | False | Precision | Recall | False / camera-hour | Mean delay |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scores.values():
        delay = "–" if s.mean_delay_s is None else f"{s.mean_delay_s:.0f}s"
        lines.append(
            f"| {s.rule_type} | {s.caught} | {s.missed} | {s.false} | {_pct(s.precision)} | "
            f"{_pct(s.recall)} | {s.false_per_hour:.2f} | {delay} |"
        )
    total_frames = sum(r.frames for r in results)
    total_wall = sum(r.wall_s for r in results) or 1e-9
    lines += [
        "",
        f"{len(results)} clip(s), {total_frames} frames, {total_frames / total_wall:.0f} frames/s processed.",
        "",
        "## Per clip",
        "",
        "| Clip | Alerts | Caught | Missed | False | Note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        note = r.error or "; ".join(f"{a.rule} @{a.at_s:.0f}s" for a in r.false_alerts)
        lines.append(
            f"| {r.clip_id} | {len(r.alerts)} | {len(r.caught)} | {len(r.missed)} | {len(r.false_alerts)} | {note} |"
        )
    if regressions:
        lines += ["", "## Regressions against baseline", "", *[f"- {x}" for x in regressions]]
    return "\n".join(lines) + "\n"


def results_json(results: list[ClipResult], scores: dict[str, RuleTypeScore]) -> dict[str, object]:
    return {
        "scores": {k: v.to_dict() for k, v in scores.items()},
        "clips": [asdict(r) for r in results],
    }


def compare_baseline(
    scores: dict[str, RuleTypeScore],
    baseline: dict[str, object],
    recall_drop: float = 0.03,
    false_rise: float = 0.20,
) -> list[str]:
    """Regression rule from VID-10: recall down more than 3 points, or false alerts per
    camera-hour up more than 20 %, for any rule type."""
    problems: list[str] = []
    base_scores = baseline.get("scores", {})
    assert isinstance(base_scores, dict)
    for rtype, s in scores.items():
        b = base_scores.get(rtype)
        if not isinstance(b, dict):
            continue
        br, nr = b.get("recall"), s.recall
        if isinstance(br, (int, float)) and nr is not None and nr < br - recall_drop:
            problems.append(f"{rtype}: recall {br * 100:.0f}% -> {nr * 100:.0f}%")
        bf = float(b.get("false_per_hour") or 0.0)
        nf = s.false_per_hour
        if nf > bf * (1 + false_rise) and nf - bf > 0.05:
            problems.append(f"{rtype}: false alerts per camera-hour {bf:.2f} -> {nf:.2f}")
    return problems


def load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data
