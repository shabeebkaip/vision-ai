"""EDG-12 end to end: the real edge outbox and uploader against the real device API.

Skipped where the edge package is not installed (the cloud-only CI job)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from vision_cloud.jobs import InMemoryQueue
from vision_shared.schemas import Event, EventState, RuleType, Severity

from .conftest import T0, World, auth

pytest.importorskip("vision_edge")

from vision_edge.outbox import Outbox
from vision_edge.sinks import OutboxSink
from vision_edge.uploader import CloudClient, Uploader


def _event(world: World, i: int, camera: str | None = None) -> Event:
    a = world.a
    at = T0 + timedelta(minutes=i)
    return Event(
        id=f"edge-{i:03d}",
        site_id=a.site_ids[0],
        camera_id=camera or a.camera_ids[0],
        rule_id=a.rule_id,
        rule_type=RuleType.ZONE_OCCUPANCY_OVER,
        severity=Severity.WARNING,
        condition_started_at=at - timedelta(seconds=30),
        triggered_at=at,
        value=4,
        message=f"crowd {i}",
    )


def test_outbox_reaches_the_cloud_with_media(
    world: World, queue: InMemoryQueue, tmp_path: Path
) -> None:
    outbox = Outbox(tmp_path / "outbox")
    sink = OutboxSink(outbox.dir, outbox)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\0\0\0\x18ftypmp42" + b"\0" * 2000)
    first = _event(world, 1)
    sink.emit(first, b"\xff\xd8\xff\xe0jpeg")
    sink.update(first, clip)
    first.state = EventState.CLEARED
    first.cleared_at = T0 + timedelta(minutes=3)
    sink.update(first)
    sink.emit(_event(world, 2), None)
    sink.emit(_event(world, 3, camera="not-a-camera"), b"jpeg")  # refused by the cloud

    client = CloudClient("http://testserver", world.a.device_token, http=world.client)
    res = Uploader(outbox, client).drain()

    assert (res.events_sent, res.events_failed, res.media_sent, res.media_dropped) == (3, 1, 2, 1)
    owner = auth(world.a.owner_token)
    detail = world.client.get("/api/v1/events/edge-001", headers=owner).json()
    assert detail["state"] == "cleared"
    assert detail["snapshot_key"] and detail["clip_key"]
    assert world.client.get("/api/v1/events/edge-002", headers=owner).status_code == 200
    assert world.client.get("/api/v1/events/edge-003", headers=owner).status_code == 404
    jobs = [(name, j["event_id"]) for name, j in queue.jobs if j["event_id"].startswith("edge-")]
    assert jobs.count(("event.created", "edge-001")) == 1
    assert ("event.cleared", "edge-001") in jobs
    assert ("event.media_ready", "edge-001") in jobs

    # A second drain sends nothing; re-queuing the same versions changes nothing in the cloud.
    assert Uploader(outbox, client).drain().events_sent == 0
    again = Outbox(tmp_path / "again")
    again.add_event(_event(world, 2))
    assert Uploader(again, client).drain().events_sent == 1
    created = [n for n, j in queue.jobs if n == "event.created" and j["event_id"] == "edge-002"]
    assert created == ["event.created"]  # stored once, despite being sent twice
