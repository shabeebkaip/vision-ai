"""Synthetic test scenarios: scripted people walking through a scene, with realistic detector noise.

They exercise tracking, zones, lines, schedules and every MVP rule type, with known correct answers,
before any real footage or model weights are available. They never replace real clips: real CCTV
footage (VID-04, VID-07) is what the pass marks are judged on.

    vision-eval synth --out test-videos/synthetic            # detections JSONL for every scenario
    vision-eval synth --out test-videos/synthetic --video    # also render MP4s (for clips/snapshots)
    vision-eval synth --write-manifest test-videos/manifest.yaml
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from pathlib import Path

import cv2
import numpy as np
import yaml

from vision_shared.manifest import ClipEntry, ExpectedEvent, Manifest
from vision_shared.schemas import Direction, Line, Rule, RuleType, Schedule, Zone

Waypoint = tuple[float, float, float]  # (t seconds, x 0..1, y 0..1) of the feet


@dataclass
class Walker:
    path: list[Waypoint]
    class_name: str = "person"
    height: float = 0.28  # box height as a fraction of frame height

    def feet(self, t: float) -> tuple[float, float] | None:
        if t < self.path[0][0] or t > self.path[-1][0]:
            return None
        for (t0, x0, y0), (t1, x1, y1) in zip(self.path, self.path[1:], strict=False):
            if t0 <= t <= t1:
                f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return (x0 + f * (x1 - x0), y0 + f * (y1 - y0))
        return (self.path[-1][1], self.path[-1][2])


@dataclass
class Scenario:
    id: str
    scene: str
    duration_s: float
    walkers: list[Walker]
    zones: list[Zone] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    expected: list[ExpectedEvent] = field(default_factory=list)
    must_not_fire: list[str] = field(default_factory=list)
    start_time: datetime = datetime(2026, 1, 4, 6, 0, tzinfo=timezone.utc)  # 09:00 Riyadh
    lighting: str = "day"
    notes: str = ""
    fps: float = 5.0
    width: int = 1280
    height: int = 720
    seed: int = 7


def _visit(
    x: float,
    y_in: float,
    t_in: float,
    t_out: float,
    y_from: float = 0.99,
    y_to: float = 0.40,
    walk: float = 2.0,
) -> Walker:
    """Walk up from the bottom edge to (x, y_in), stand, then walk up and out."""
    return Walker(
        [(t_in, x, y_from), (t_in + walk, x, y_in), (t_out, x, y_in), (t_out + walk, x, y_to)]
    )


def scenarios() -> list[Scenario]:
    out: list[Scenario] = []

    # 1. Restaurant counter queue: 8 customers, 90 s each, threshold 4 for 20 s.
    q = Zone(
        id="counter_queue",
        name="Counter queue",
        polygon=[(0.30, 0.55), (0.70, 0.55), (0.70, 0.95), (0.30, 0.95)],
    )
    out.append(
        Scenario(
            id="syn-queue-001",
            scene="restaurant counter",
            duration_s=240,
            walkers=[_visit(0.34 + 0.045 * k, 0.75, 10 + 10 * k, 100 + 10 * k) for k in range(8)],
            zones=[q],
            rules=[
                Rule(
                    id="queue",
                    type=RuleType.QUEUE_LENGTH_OVER,
                    camera_id="cam",
                    zone_id="counter_queue",
                    threshold=4,
                    min_duration_s=20,
                    cooldown_s=600,
                ),
                Rule(
                    id="unattended",
                    type=RuleType.ZONE_EMPTY,
                    camera_id="cam",
                    zone_id="counter_queue",
                    min_duration_s=600,
                ),
            ],
            expected=[ExpectedEvent(rule="queue", start_s=50, end_s=132, tolerance_s=15)],
            must_not_fire=["unattended"],
            notes="Queue grows to 8, more than 4 people from ~50 s to ~132 s.",
        )
    )

    # 2. Pharmacy cashier: a 32 s break must not alert, a 150 s absence must.
    c = Zone(
        id="cashier",
        name="Cashier desk",
        polygon=[(0.55, 0.35), (0.85, 0.35), (0.85, 0.70), (0.55, 0.70)],
    )
    staff = Walker(
        [
            (0, 0.70, 0.60),
            (40, 0.70, 0.60),
            (42, 0.97, 0.60),
            (70, 0.97, 0.60),
            (72, 0.70, 0.60),
            (110, 0.70, 0.60),
            (112, 0.97, 0.60),
            (260, 0.97, 0.60),
            (262, 0.70, 0.60),
            (300, 0.70, 0.60),
        ]
    )
    out.append(
        Scenario(
            id="syn-unattended-001",
            scene="pharmacy cashier",
            duration_s=300,
            walkers=[staff],
            zones=[c],
            rules=[
                Rule(
                    id="desk_empty",
                    type=RuleType.ZONE_EMPTY,
                    camera_id="cam",
                    zone_id="cashier",
                    min_duration_s=60,
                    clear_after_s=5,
                )
            ],
            expected=[ExpectedEvent(rule="desk_empty", start_s=111, end_s=261, tolerance_s=15)],
            notes="Short break 41-71 s must stay quiet; long absence 111-261 s alerts once.",
        )
    )

    # 3. Shop at night, 23:30 Riyadh: one intruder for ~60 s.
    floor = Zone(
        id="shop_floor",
        name="Shop floor",
        polygon=[(0.10, 0.30), (0.90, 0.30), (0.90, 0.95), (0.10, 0.95)],
    )
    after_hours = Rule(
        id="after_hours",
        type=RuleType.PRESENCE_AFTER_HOURS,
        camera_id="cam",
        zone_id="shop_floor",
        min_duration_s=5,
        schedule=Schedule(start=time(23, 0), end=time(6, 0)),
    )
    out.append(
        Scenario(
            id="syn-afterhours-001",
            scene="retail shop floor",
            duration_s=200,
            lighting="night IR",
            start_time=datetime(2026, 1, 4, 20, 30, tzinfo=timezone.utc),
            walkers=[
                Walker([(60, 0.05, 0.80), (68, 0.60, 0.70), (120, 0.60, 0.70), (128, 0.05, 0.80)])
            ],
            zones=[floor],
            rules=[after_hours],
            expected=[ExpectedEvent(rule="after_hours", start_s=61, end_s=127, tolerance_s=15)],
            notes="Intruder at 23:31 Riyadh time.",
        )
    )

    # 4. Same shop at 14:00 with shoppers: the after-hours rule must stay quiet.
    out.append(
        Scenario(
            id="syn-afterhours-neg-001",
            scene="retail shop floor",
            duration_s=200,
            start_time=datetime(2026, 1, 4, 11, 0, tzinfo=timezone.utc),
            walkers=[
                Walker(
                    [
                        (10 + 40 * k, 0.05, 0.75 - 0.08 * k),
                        (25 + 40 * k, 0.85, 0.75 - 0.08 * k),
                        (40 + 40 * k, 0.95, 0.75 - 0.08 * k),
                    ]
                )
                for k in range(4)
            ],
            zones=[floor],
            rules=[after_hours],
            must_not_fire=["after_hours"],
            notes="Daytime shoppers; opening hours.",
        )
    )

    # 5. Mall entrance: 14 people come in, 3 go out; alert at the 10th entry.
    door = Line(id="door", name="Entrance", start=(0.20, 0.50), end=(0.80, 0.50))
    entries = [
        Walker([(15 + 15 * k, 0.25 + 0.035 * k, 0.20), (21 + 15 * k, 0.25 + 0.035 * k, 0.90)])
        for k in range(14)
    ]
    exits = [
        Walker([(t, x, 0.90), (t + 6, x, 0.20)]) for t, x in [(50, 0.72), (120, 0.30), (200, 0.55)]
    ]
    out.append(
        Scenario(
            id="syn-entrance-001",
            scene="mall entrance",
            duration_s=300,
            walkers=entries + exits,
            lines=[door],
            rules=[
                Rule(
                    id="entries",
                    type=RuleType.LINE_CROSSING,
                    camera_id="cam",
                    line_id="door",
                    direction=Direction.IN,
                    threshold=10,
                    window_s=300,
                    cooldown_s=300,
                ),
                Rule(
                    id="exits",
                    type=RuleType.LINE_CROSSING,
                    camera_id="cam",
                    line_id="door",
                    direction=Direction.OUT,
                    threshold=5,
                    window_s=300,
                ),
            ],
            expected=[ExpectedEvent(rule="entries", start_s=150, end_s=156, tolerance_s=10)],
            must_not_fire=["exits"],
            notes="10th entry at ~152.6 s; only 3 exits so the exit rule stays quiet.",
        )
    )

    # 6. Back door: five passers-by, one person loitering 140 s.
    back = Zone(
        id="back_door",
        name="Back door",
        polygon=[(0.60, 0.40), (0.95, 0.40), (0.95, 0.90), (0.60, 0.90)],
    )
    passers = [Walker([(t, 0.50, 0.65), (t + 12, 0.99, 0.65)]) for t in (20, 60, 100, 180, 240)]
    loiterer = Walker([(80, 0.50, 0.75), (83, 0.80, 0.75), (220, 0.80, 0.75), (223, 0.50, 0.75)])
    out.append(
        Scenario(
            id="syn-loiter-001",
            scene="warehouse back door",
            duration_s=300,
            walkers=[*passers, loiterer],
            zones=[back],
            rules=[
                Rule(
                    id="loitering",
                    type=RuleType.DWELL_OVER,
                    camera_id="cam",
                    zone_id="back_door",
                    min_duration_s=90,
                    cooldown_s=60,
                )
            ],
            expected=[ExpectedEvent(rule="loitering", start_s=81, end_s=222, tolerance_s=15)],
            notes="Passers-by spend ~7 s in the zone; the loiterer ~140 s.",
        )
    )

    # 7. Clinic waiting area: 8 people for ~100 s, limit 6 for 30 s.
    wait = Zone(
        id="waiting",
        name="Waiting area",
        polygon=[(0.10, 0.40), (0.90, 0.40), (0.90, 0.95), (0.10, 0.95)],
    )
    seats = [(0.18 + 0.09 * (k % 4) * 2, 0.62 + 0.18 * (k // 4)) for k in range(8)]
    out.append(
        Scenario(
            id="syn-crowd-001",
            scene="clinic waiting area",
            duration_s=240,
            walkers=[
                _visit(x, y, 20 + 2 * k, 120 + 2 * k, y_from=0.999, y_to=0.30)
                for k, (x, y) in enumerate(seats)
            ],
            zones=[wait],
            rules=[
                Rule(
                    id="crowded",
                    type=RuleType.ZONE_OCCUPANCY_OVER,
                    camera_id="cam",
                    zone_id="waiting",
                    threshold=6,
                    min_duration_s=30,
                )
            ],
            expected=[ExpectedEvent(rule="crowded", start_s=33, end_s=124, tolerance_s=15)],
            notes="7th person arrives ~33 s; count drops to 6 at ~124 s.",
        )
    )
    return out


# --------------------------------------------------------------------------- rendering


def _box(
    w: Walker, feet: tuple[float, float], width: int, height: int
) -> tuple[float, float, float, float]:
    bh = w.height * height
    bw = bh * 0.38
    x, y = feet[0] * width, feet[1] * height
    return (x - bw / 2, y - bh, x + bw / 2, y)


def detections_for(s: Scenario) -> list[dict[str, object]]:
    rng = random.Random(s.seed)
    rows: list[dict[str, object]] = []
    n = int(s.duration_s * s.fps)
    for i in range(n + 1):
        t = i / s.fps
        dets: list[dict[str, object]] = []
        for w in s.walkers:
            feet = w.feet(t)
            if feet is None or rng.random() < 0.08:  # 8 % missed detections
                continue
            x1, y1, x2, y2 = _box(w, feet, s.width, s.height)
            j = (y2 - y1) * 0.015
            box = [round(v + rng.uniform(-j, j), 1) for v in (x1, y1, x2, y2)]
            box = [
                max(0.0, min(box[0], s.width)),
                max(0.0, box[1]),
                min(box[2], s.width),
                min(box[3], s.height),
            ]
            dets.append(
                {
                    "class_name": w.class_name,
                    "confidence": round(rng.uniform(0.55, 0.95), 3),
                    "box": box,
                }
            )
        if rng.random() < 0.01:  # occasional one-frame false positive
            x, y = rng.uniform(0.1, 0.9) * s.width, rng.uniform(0.3, 0.9) * s.height
            dets.append(
                {
                    "class_name": "person",
                    "confidence": round(rng.uniform(0.35, 0.6), 3),
                    "box": [x - 30, y - 160, x + 30, y],
                }
            )
        rows.append({"t": round(t, 3), "w": s.width, "h": s.height, "detections": dets})
    return rows


def render_video(s: Scenario, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), s.fps, (s.width, s.height))
    base = np.zeros((s.height, s.width, 3), np.uint8)
    for yy in range(s.height):
        shade = (
            60 + int(80 * yy / s.height) if s.lighting == "day" else 25 + int(30 * yy / s.height)
        )
        base[yy, :] = (shade, shade, shade + 10)
    palette = [
        (200, 120, 60),
        (60, 160, 200),
        (90, 200, 90),
        (180, 80, 180),
        (50, 90, 220),
        (220, 200, 80),
    ]
    for i in range(int(s.duration_s * s.fps) + 1):
        t = i / s.fps
        img = base.copy()
        for k, w in enumerate(s.walkers):
            feet = w.feet(t)
            if feet is None:
                continue
            x1, y1, x2, y2 = (int(v) for v in _box(w, feet, s.width, s.height))
            colour = palette[k % len(palette)]
            head = int((x2 - x1) * 0.35)
            cv2.circle(img, ((x1 + x2) // 2, y1 + head), head, (170, 190, 220), -1)
            cv2.rectangle(img, (x1, y1 + 2 * head), (x2, y2), colour, -1)
        cv2.putText(
            img, f"{s.id}  t={t:6.1f}s", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
        )
        writer.write(img)
    writer.release()


def write_scenarios(
    out_dir: Path, video: bool = False, only: Sequence[str] | None = None
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for s in scenarios():
        if only and s.id not in only:
            continue
        p = out_dir / f"{s.id}.detections.jsonl"
        with p.open("w", encoding="utf-8") as fh:
            for row in detections_for(s):
                fh.write(json.dumps(row) + "\n")
        written.append(p)
        if video:
            render_video(s, out_dir / f"{s.id}.mp4")
    return written


def manifest_entries(rel_dir: str = "synthetic") -> Manifest:
    clips = []
    for s in scenarios():
        clips.append(ClipEntry(
            id=s.id, detections=f"{rel_dir}/{s.id}.detections.jsonl", file=f"{rel_dir}/{s.id}.mp4",
            source="synthetic (vision_ml.tools.synthetic), generated, no real footage",
            scene=s.scene, angle="fixed, ceiling", lighting=s.lighting, resolution=f"{s.width}x{s.height}",
            fps=s.fps, start_time=s.start_time, duration_s=s.duration_s, tags=["synthetic"],
            zones=s.zones, lines=s.lines, rules=s.rules, expected=s.expected,
            must_not_fire=s.must_not_fire, notes=s.notes,
        ))  # fmt: skip
    return Manifest(clips=clips)


def write_manifest(path: Path) -> None:
    data = manifest_entries().model_dump(mode="json", exclude_defaults=False)
    header = (
        "# Test-clip manifest (VID-02). Synthetic entries are generated by\n"
        "# `vision-eval synth --write-manifest`; append real clips below them by hand.\n"
    )
    path.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
