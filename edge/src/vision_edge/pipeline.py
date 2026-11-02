"""Per-camera pipeline: frame -> detections -> tracks -> scene -> rules -> events -> sinks."""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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

    def __post_init__(self) -> None:
        self.scene = SceneState(self.camera)
        self.evaluators: list[RuleEvaluator] = [
            build_evaluator(r, self.camera, self.site.timezone)
            for r in self.site.rules_for(self.camera.id)
        ]
        rules = self.site.rules_for(self.camera.id)
        self._classes = {c for r in rules for c in r.classes}
        self._min_conf = min((r.min_confidence for r in rules), default=0.4)
        self._open: dict[str, Event] = {}
        self._clips: ClipRecorder | None = None
        if self.media_dir is not None and not self.site.events_only:
            self._clips = ClipRecorder(
                self.media_dir, self.camera.fps, pre_s=self.clip_pre_s, post_s=self.clip_post_s
            )

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
            if self._clips is not None:
                for event, path in self._clips.flush():
                    for s in self.sinks:
                        s.update(event, path)
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
