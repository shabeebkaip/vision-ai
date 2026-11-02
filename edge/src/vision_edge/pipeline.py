"""Per-camera pipeline: frame -> detections -> tracks -> scene -> rules -> events -> sinks."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

from vision_edge.detection import Detector
from vision_edge.frames import Frame
from vision_edge.media import ClipRecorder, draw_snapshot, encode_jpeg
from vision_edge.rules import Clear, RuleEvaluator, Trigger, build_evaluator
from vision_edge.scene import SceneState
from vision_edge.sinks import EventSink
from vision_edge.tracking import ByteTracker
from vision_shared.schemas import CameraConfig, Event, EventState, SiteConfig

log = structlog.get_logger(__name__)


@dataclass
class RunStats:
    frames: int = 0
    events: int = 0
    seconds_of_video: float = 0.0
    wall_seconds: float = 0.0
    detect_seconds: float = 0.0

    @property
    def fps(self) -> float:
        return self.frames / self.wall_seconds if self.wall_seconds > 0 else 0.0


@dataclass
class CameraPipeline:
    site: SiteConfig
    camera: CameraConfig
    detector: Detector
    sinks: Sequence[EventSink]
    media_dir: Path | None = None
    clip_pre_s: float = 5.0
    clip_post_s: float = 5.0
    tracker: ByteTracker = field(default_factory=ByteTracker)
    stats: RunStats = field(default_factory=RunStats)
    after_frame: list[Callable[[CameraPipeline, Frame], None]] = field(default_factory=list)
    """Called after every frame: status reporting, config reload (EDG-13)."""

    def __post_init__(self) -> None:
        self.scene = SceneState(self.camera)
        self.evaluators: list[RuleEvaluator] = [
            build_evaluator(r, self.camera, self.site.timezone)
            for r in self.site.rules_for(self.camera.id)
        ]
        self._open: dict[str, Event] = {}
        self._clips: ClipRecorder | None = None
        self._apply_site_settings()

    def _apply_site_settings(self) -> None:
        rules = self.site.rules_for(self.camera.id)
        self._classes = {c for r in rules for c in r.classes}
        self._min_conf = min((r.min_confidence for r in rules), default=0.4)
        wants_clips = self.media_dir is not None and not self.site.events_only
        if wants_clips and self._clips is None:
            assert self.media_dir is not None
            self._clips = ClipRecorder(
                self.media_dir, self.camera.fps, pre_s=self.clip_pre_s, post_s=self.clip_post_s
            )
        elif not wants_clips and self._clips is not None:
            self._finish_clips()
            self._clips = None

    def _finish_clips(self) -> None:
        if self._clips is not None:
            for event, path in self._clips.flush():
                for s in self.sinks:
                    s.update(event, path)

    # ------------------------------------------------------------------ live reconfiguration
    def reconfigure(self, site: SiteConfig, now: datetime | None = None) -> bool:
        """Apply a new site config without restarting (EDG-13).

        Rules whose definition and geometry are unchanged keep their state (durations, cooldowns,
        open alerts). Changed or removed rules are rebuilt or dropped, and their open alerts are
        closed as "cleared" so the cloud is not left with an alert that can never clear. Returns
        False when this camera's stream itself changed (source or fps): that needs a restart.
        """
        camera = next((c for c in site.cameras if c.id == self.camera.id), None)
        if camera is None or not camera.enabled:
            camera = self.camera.model_copy(update={"zones": [], "lines": []})
            site = site.model_copy(
                update={"rules": [r for r in site.rules if r.camera_id != camera.id]}
            )
        if camera.source != self.camera.source or camera.fps != self.camera.fps:
            return False
        geometry_same = camera.zones == self.camera.zones and camera.lines == self.camera.lines
        old = {e.rule.id: e for e in self.evaluators}
        keep: list[RuleEvaluator] = []
        for rule in site.rules_for(camera.id):
            prev = old.get(rule.id)
            if (
                prev is not None
                and prev.rule == rule
                and geometry_same
                and site.timezone == self.site.timezone
            ):
                keep.append(prev)
            else:
                keep.append(build_evaluator(rule, camera, site.timezone))
        kept_ids = {id(e) for e in keep}
        dropped = {rid for rid, e in old.items() if id(e) not in kept_ids}
        when = now or datetime.now(timezone.utc)
        for key, event in list(self._open.items()):
            if event.rule_id in dropped:
                self._open.pop(key)
                event.state = EventState.CLEARED
                event.cleared_at = when
                event.attributes["cleared_by"] = "config_change"
                for s in self.sinks:
                    s.update(event)
        if not geometry_same:
            self.scene = SceneState(camera)
        self.site, self.camera, self.evaluators = site, camera, keep
        self._apply_site_settings()
        log.info(
            "pipeline.reconfigured",
            camera_id=camera.id,
            config_version=site.version,
            rules=len(keep),
            rebuilt=len(keep) - (len(old) - len(dropped)),
            removed=len(set(old) - {e.rule.id for e in keep}),
        )
        return True

    # ------------------------------------------------------------------ one frame
    def process(self, frame: Frame) -> list[Event]:
        t0 = time.perf_counter()
        raw = self.detector.detect([frame])[0]
        self.stats.detect_seconds += time.perf_counter() - t0
        dets = [
            d for d in raw if d.class_name in self._classes and d.confidence >= self._min_conf * 0.5
        ]
        tracked = self.tracker.update(dets, frame.video_time_s)
        obs = self.scene.update(frame.ts, tracked, frame.width, frame.height)

        new_events: list[Event] = []
        for ev in self.evaluators:
            for outcome in ev.evaluate(obs):
                if isinstance(outcome, Trigger):
                    event = self._on_trigger(outcome, frame, tracked)
                    new_events.append(event)
                elif isinstance(outcome, Clear):
                    self._on_clear(outcome)

        if self._clips is not None:
            for event, path in self._clips.push(frame):
                for s in self.sinks:
                    s.update(event, path)

        self.stats.frames += 1
        self.stats.seconds_of_video = frame.video_time_s
        self.stats.events += len(new_events)
        for hook in self.after_frame:
            hook(self, frame)
        return new_events

    def _on_trigger(self, t: Trigger, frame: Frame, tracked: list) -> Event:  # type: ignore[type-arg]
        event = Event(
            site_id=self.site.id,
            camera_id=self.camera.id,
            rule_id=t.rule.id,
            rule_type=t.rule.type,
            severity=t.rule.severity,
            condition_started_at=t.condition_started_at,
            triggered_at=t.triggered_at,
            value=t.value,
            message=t.message,
            attributes={**t.attributes, "video_time_s": round(frame.video_time_s, 2)},
            needs_verification=t.rule.verify,
        )
        snapshot = None
        if frame.image is not None and not self.site.events_only:
            img = draw_snapshot(frame.image, self.camera, tracked, t.rule.zone_id, t.message)
            snapshot = encode_jpeg(img)
        for s in self.sinks:
            s.emit(event, snapshot)
        self._open[t.key] = event
        if self._clips is not None and frame.image is not None:
            self._clips.start(event)
        return event

    def _on_clear(self, c: Clear) -> None:
        event = self._open.pop(c.key, None)
        if event is None:
            return
        event.state = EventState.CLEARED
        event.cleared_at = c.cleared_at
        event.attributes.update(c.attributes)
        for s in self.sinks:
            s.update(event)

    # ------------------------------------------------------------------ whole source
    def run(self, frames: Iterable[Frame]) -> RunStats:
        started = time.perf_counter()
        try:
            for frame in frames:
                self.process(frame)
        finally:
            self._finish_clips()
            self.stats.wall_seconds = time.perf_counter() - started
        log.info(
            "pipeline.done",
            camera_id=self.camera.id,
            frames=self.stats.frames,
            events=self.stats.events,
            video_s=round(self.stats.seconds_of_video, 1),
            fps=round(self.stats.fps, 1),
        )
        return self.stats
