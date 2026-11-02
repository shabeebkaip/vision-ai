"""EDG-12: outbox + uploader against a fake cloud that follows the device API's rules.

Done-when from the plan: "pulling the internet for 2 hours then restoring delivers every event
once, in order".
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from vision_edge.outbox import OpKind, Outbox
from vision_edge.sinks import OutboxSink
from vision_edge.uploader import CloudClient, RetryLater, Unauthorised, Uploader
from vision_shared.schemas import Event, EventState, RuleType, Severity

T0 = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


class FakeCloud:
    """In-memory device API: idempotent by event id, triggered -> cleared only, media via a
    pre-signed PUT then finalise. `online=False` drops every request like a dead link;
    `lose_next_response` processes a request but fails before the answer reaches the box."""

    def __init__(self) -> None:
        self.online = True
        self.lose_next_response = False
        self.token = "cxd_test"
        self.cameras = {"cam1"}
        self.events: dict[str, dict[str, object]] = {}
        self.arrivals: list[tuple[str, str]] = []  # (event id, state) for each stored change
        self.objects: dict[str, bytes] = {}
        self.media: dict[str, set[str]] = {}
        self.requests = 0
        self.events_only = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests += 1
        if not self.online:
            raise httpx.ConnectError("network unreachable", request=req)
        path = req.url.path
        if path.startswith("/storage/"):
            assert "authorization" not in req.headers, "token must not go to storage"
            self.objects[path] = req.content
            return self._answer(httpx.Response(200), req)
        if req.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"detail": "bad token"})
        if path == "/device/v1/events/batch":
            results = [self._ingest(e) for e in json.loads(req.content)["events"]]
            return self._answer(httpx.Response(200, json={"results": results}), req)
        event_id = path.split("/")[4]
        if event_id not in self.events:
            return httpx.Response(404, json={"detail": "event not found"})
        if path.endswith("/uploads"):
            if self.events_only:
                return httpx.Response(409, json={"detail": "events-only"})
            kind = json.loads(req.content)["kinds"][0]
            url = f"http://storage.test/storage/{event_id}/{kind}"
            target = {
                "kind": kind,
                "key": f"k/{event_id}/{kind}",
                "url": url,
                "method": "PUT",
                "headers": {"Content-Type": "image/jpeg" if kind == "snapshot" else "video/mp4"},
                "expires_at": "2030-01-01T00:00:00Z",
            }
            return httpx.Response(200, json={"event_id": event_id, "uploads": [target]})
        if path.endswith("/finalise"):
            body = json.loads(req.content)
            for kind in ("snapshot", "clip"):
                if body[kind]:
                    if f"/storage/{event_id}/{kind}" not in self.objects:
                        return httpx.Response(409, json={"detail": "media missing"})
                    self.media.setdefault(event_id, set()).add(kind)
            return self._answer(httpx.Response(200, json={"event_id": event_id}), req)
        return httpx.Response(404)

    def _answer(self, resp: httpx.Response, req: httpx.Request) -> httpx.Response:
        if self.lose_next_response:
            self.lose_next_response = False
            raise httpx.ReadTimeout("answer lost", request=req)
        return resp

    def _ingest(self, e: dict[str, object]) -> dict[str, object]:
        eid = str(e["id"])
        if e["camera_id"] not in self.cameras:
            return {"event_id": eid, "status": "rejected", "error": "unknown camera"}
        old = self.events.get(eid)
        if old is None:
            self.events[eid] = e
            self.arrivals.append((eid, str(e["state"])))
            return {"event_id": eid, "status": "created"}
        if e["state"] == "cleared" and old["state"] == "triggered":
            self.events[eid] = e
            self.arrivals.append((eid, "cleared"))
            return {"event_id": eid, "status": "updated"}
        return {"event_id": eid, "status": "unchanged"}


def make_event(i: int, camera: str = "cam1") -> Event:
    at = T0 + timedelta(seconds=36 * i)
    return Event(
        id=f"ev-{i:04d}",
        site_id="site",
        camera_id=camera,
        rule_id="queue",
        rule_type=RuleType.QUEUE_LENGTH_OVER,
        severity=Severity.WARNING,
        condition_started_at=at - timedelta(seconds=20),
        triggered_at=at,
        value=5,
        message=f"queue {i}",
    )


def clip_file(tmp: Path, name: str, size: int = 1000) -> Path:
    p = tmp / "clips" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\0" * size)
    return p


@pytest.fixture
def cloud() -> FakeCloud:
    return FakeCloud()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def uploader_for(outbox: Outbox, cloud: FakeCloud, batch_size: int = 25) -> Uploader:
    client = CloudClient(
        "http://cloud.test", cloud.token, http=httpx.Client(transport=cloud.transport())
    )
    return Uploader(outbox, client, batch_size=batch_size)


# --------------------------------------------------------------------------- done-when


def test_two_hour_outage_delivers_every_event_once_in_order(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path / "outbox", clock=clock)
    sink = OutboxSink(outbox.dir, outbox)
    up = uploader_for(outbox, cloud)

    cloud.online = False
    expected: list[tuple[str, str]] = []
    # 2 hours offline: an event every 36 s (200 events), each cleared 10 minutes later, with a
    # snapshot and a clip; the uploader keeps trying (and failing) every 30 s of the outage.
    open_events: list[tuple[float, Event]] = []
    for step in range(240):
        clock.t += 30
        if step % 2 == 0 and step // 2 < 200:
            ev = make_event(step // 2)
            sink.emit(ev, b"jpeg")
            sink.update(ev, clip_file(tmp_path, f"{ev.id}.mp4"))
            expected.append((ev.id, "triggered"))
            open_events.append((clock.t, ev))
        while open_events and clock.t - open_events[0][0] >= 600:
            _, ev = open_events.pop(0)
            ev.state = EventState.CLEARED
            ev.cleared_at = T0
            sink.update(ev)
            expected.append((ev.id, "cleared"))
        with pytest.raises(RetryLater):
            up.drain()
    assert cloud.events == {}
    assert outbox.stats().pending_events == len(expected)

    cloud.online = True
    res = up.drain()

    assert cloud.arrivals == expected  # every change once, in the order it happened
    assert res.events_sent == len(expected)
    assert {k for v in cloud.media.values() for k in v} == {"snapshot", "clip"}
    assert all(cloud.media[e] == {"snapshot", "clip"} for e, _ in expected)
    s = outbox.stats()
    assert (s.pending_events, s.pending_media, s.failed, s.dropped) == (0, 0, 0, 0)


def test_lost_answer_is_resent_but_stored_once(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    for i in range(3):
        outbox.add_event(make_event(i))
    up = uploader_for(outbox, cloud)
    cloud.lose_next_response = True
    with pytest.raises(RetryLater):
        up.drain()
    assert len(cloud.events) == 3  # the cloud stored them; the box did not hear back
    up.drain()
    assert [a[0] for a in cloud.arrivals] == ["ev-0000", "ev-0001", "ev-0002"]
    assert outbox.stats().pending_events == 0


# --------------------------------------------------------------------------- ordering rules


def test_media_waits_for_its_event_and_never_blocks_events(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    sink = OutboxSink(outbox.dir, outbox)
    ev = make_event(1)
    sink.emit(ev, b"jpeg")
    assert outbox.next_media() is None  # event not delivered yet
    sink.update(make_event(2))  # a second event queued after the snapshot
    up = uploader_for(outbox, cloud)
    seen: list[str] = []
    original = cloud.handle

    def spy(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return original(req)

    spy_http = httpx.Client(transport=httpx.MockTransport(spy))
    up.client = CloudClient("http://cloud.test", cloud.token, http=spy_http)
    up.drain()
    assert seen[0] == "/device/v1/events/batch"  # both events in one batch, before any media
    assert set(cloud.events) == {"ev-0001", "ev-0002"}
    assert seen[1:] == [
        "/device/v1/events/ev-0001/uploads",
        "/storage/ev-0001/snapshot",
        "/device/v1/events/ev-0001/finalise",
    ]


def test_same_state_is_queued_once(tmp_path: Path, clock: Clock) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    ev = make_event(1)
    outbox.add_event(ev)
    outbox.add_event(ev)  # e.g. the clip update re-sends the triggered version
    ev.state = EventState.CLEARED
    outbox.add_event(ev)
    outbox.add_event(ev)
    states = [o.event().state for o in outbox.pending_events(10)]
    assert states == [EventState.TRIGGERED, EventState.CLEARED]


def test_refused_event_is_parked_and_does_not_block(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    sink = OutboxSink(outbox.dir, outbox)
    sink.emit(make_event(1, camera="cam-unknown"), b"jpeg")
    sink.emit(make_event(2), b"jpeg")
    res = uploader_for(outbox, cloud).drain()
    assert list(cloud.events) == ["ev-0002"]
    assert (res.events_sent, res.events_failed, res.media_sent, res.media_dropped) == (1, 1, 1, 1)
    s = outbox.stats()
    assert (s.pending_events, s.pending_media, s.failed, s.dropped) == (0, 0, 1, 1)


def test_events_only_site_drops_media_but_keeps_events(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    cloud.events_only = True
    outbox = Outbox(tmp_path, clock=clock)
    OutboxSink(outbox.dir, outbox).emit(make_event(1), b"jpeg")
    res = uploader_for(outbox, cloud).drain()
    assert res.events_sent == 1 and res.media_dropped == 1
    assert cloud.objects == {}


def test_bad_token_is_reported_as_unauthorised(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    outbox.add_event(make_event(1))
    stale = CloudClient(
        "http://cloud.test", "cxd_revoked", http=httpx.Client(transport=cloud.transport())
    )
    with pytest.raises(Unauthorised):
        Uploader(outbox, stale).drain()
    assert outbox.stats().pending_events == 1


# --------------------------------------------------------------------------- disk and retention


def test_clip_quota_drops_oldest_clips_never_events(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path / "o", clock=clock, clip_quota_bytes=2500)
    sink = OutboxSink(outbox.dir, outbox)
    for i in range(4):
        ev = make_event(i)
        sink.emit(ev, None)
        sink.update(ev, clip_file(tmp_path, f"{ev.id}.mp4", size=1000))
    s = outbox.stats()
    assert s.pending_events == 4 and s.dropped == 2 and s.clip_bytes == 2000
    assert not (outbox.dir / "media" / "ev-0000.mp4").exists()
    assert (outbox.dir / "media" / "ev-0003.mp4").exists()
    uploader_for(outbox, cloud).drain()
    assert len(cloud.events) == 4
    assert set(cloud.media) == {"ev-0002", "ev-0003"}


def test_delivered_rows_are_purged_after_retention_pending_never(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path, clock=clock, retention_s=7 * 24 * 3600)
    outbox.add_event(make_event(1))
    uploader_for(outbox, cloud).drain()
    cloud.online = False
    outbox.add_event(make_event(2))
    clock.t += 8 * 24 * 3600
    assert outbox.purge() == 1  # the delivered one
    assert [o.event_id for o in outbox.pending_events(10)] == ["ev-0002"]


def test_outbox_survives_a_restart(tmp_path: Path, cloud: FakeCloud, clock: Clock) -> None:
    first = Outbox(tmp_path, clock=clock)
    OutboxSink(first.dir, first).emit(make_event(1), b"jpeg")
    first.close()
    again = Outbox(tmp_path, clock=clock)
    res = uploader_for(again, cloud).drain()
    assert res.events_sent == 1 and res.media_sent == 1


def test_missing_media_file_is_dropped(tmp_path: Path, cloud: FakeCloud, clock: Clock) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    outbox.add_event(make_event(1))
    outbox.add_media("ev-0001", OpKind.SNAPSHOT, "media/gone.jpg")
    res = uploader_for(outbox, cloud).drain()
    assert res.media_dropped == 1


# --------------------------------------------------------------------------- the loop


def test_run_forever_backs_off_then_recovers(
    tmp_path: Path, cloud: FakeCloud, clock: Clock
) -> None:
    outbox = Outbox(tmp_path, clock=clock)
    outbox.add_event(make_event(1))
    up = uploader_for(outbox, cloud)
    cloud.online = False
    stop = threading.Event()
    waits: list[float] = []

    def fake_sleep(s: float) -> None:
        waits.append(s)
        if len(waits) == 12:
            cloud.online = True
        if len(waits) == 14:
            stop.set()

    up.run_forever(stop, sleep=fake_sleep, idle_s=2.0, max_backoff_s=300.0)
    offline = waits[:12]
    assert offline[0] < offline[3] < offline[6]  # doubling (with ±20 % jitter)
    assert max(offline) <= 300 * 1.2
    assert waits[12:] == [2.0, 2.0]  # back to idle polling once delivered
    assert list(cloud.events) == ["ev-0001"]
    assert outbox.stats().pending_events == 0
