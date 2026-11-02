from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from vision_edge.detection import OnnxDetector, ReplayDetector
from vision_edge.ingest import ReplaySource
from vision_edge.pipeline import CameraPipeline
from vision_edge.sinks import MemorySink, OutboxSink
from vision_shared.schemas import CameraConfig, EventState, Rule, RuleType, SiteConfig, Zone


def _write_replay(path: Path, seconds: int = 60, people_from: float = 10.0) -> None:
    with path.open("w") as fh:
        for i in range(seconds * 5 + 1):
            t = i / 5
            dets = []
            if people_from <= t < 40:
                for k in range(3):
                    x = 300 + 120 * k
                    dets.append(
                        {"class_name": "person", "confidence": 0.9, "box": [x, 300, x + 60, 600]}
                    )
            fh.write(json.dumps({"t": t, "w": 1280, "h": 720, "detections": dets}) + "\n")


def _site(events_only: bool = False) -> SiteConfig:
    cam = CameraConfig(
        id="cam",
        source="r.jsonl",
        zones=[Zone(id="z", polygon=[(0.1, 0.3), (0.9, 0.3), (0.9, 0.95), (0.1, 0.95)])],
    )
    rule = Rule(
        id="crowd",
        type=RuleType.ZONE_OCCUPANCY_OVER,
        camera_id="cam",
        zone_id="z",
        threshold=2,
        min_duration_s=5,
        clear_after_s=3,
    )
    return SiteConfig(id="site", cameras=[cam], rules=[rule], events_only=events_only)


def test_replay_pipeline_raises_and_clears_event(tmp_path: Path) -> None:
    replay = tmp_path / "r.jsonl"
    _write_replay(replay)
    site = _site()
    sink = MemorySink()
    p = CameraPipeline(site=site, camera=site.cameras[0], detector=ReplayDetector(), sinks=[sink])
    stats = p.run(ReplaySource(replay, "cam"))
    assert stats.frames == 301
    [event] = sink.triggered
    assert event.rule_id == "crowd"
    assert event.value == 3
    assert event.attributes["video_time_s"] == 15.0
    assert event.state is EventState.CLEARED
    assert event.cleared_at is not None


def test_outbox_writes_every_event_version(tmp_path: Path) -> None:
    replay = tmp_path / "r.jsonl"
    _write_replay(replay)
    site = _site()
    outbox = OutboxSink(tmp_path / "outbox")
    p = CameraPipeline(site=site, camera=site.cameras[0], detector=ReplayDetector(), sinks=[outbox])
    p.run(ReplaySource(replay, "cam"))
    lines = (tmp_path / "outbox" / "events.jsonl").read_text().splitlines()
    assert [json.loads(x)["state"] for x in lines] == ["triggered", "cleared"]


def test_events_only_site_never_produces_media(tmp_path: Path) -> None:
    replay = tmp_path / "r.jsonl"
    _write_replay(replay)
    site = _site(events_only=True)
    sink = MemorySink()
    p = CameraPipeline(
        site=site,
        camera=site.cameras[0],
        detector=ReplayDetector(),
        sinks=[sink],
        media_dir=tmp_path / "media",
    )
    p.run(ReplaySource(replay, "cam"))
    assert sink.triggered and not sink.snapshots and not sink.clips
    assert not (tmp_path / "media").exists()


def test_onnx_postprocess_topk_and_scaling() -> None:
    d = OnnxDetector.__new__(OnnxDetector)
    d.threshold, d.classes, d.top_k = 0.5, {"person"}, 300
    d.class_names = {1: "person", 3: "car"}
    boxes = np.array(
        [[0.5, 0.5, 0.2, 0.4], [0.1, 0.1, 0.1, 0.1], [0.8, 0.8, 0.1, 0.1]], dtype=np.float32
    )
    logits = np.full((3, 4), -10.0, dtype=np.float32)
    logits[0, 1] = 3.0  # person, high
    logits[1, 3] = 3.0  # car, filtered by classes
    logits[2, 1] = -1.0  # person, below threshold
    out = d.postprocess(boxes, logits, width=1000, height=500)
    assert len(out) == 1
    assert out[0].class_name == "person"
    assert np.allclose(out[0].box, (400, 150, 600, 350))
