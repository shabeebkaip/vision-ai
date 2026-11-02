"""CLD-05: idempotent event ingest, media upload and finalise, aggregates, bursts."""

from __future__ import annotations

import time
from datetime import timedelta
from urllib.parse import urlsplit

from vision_cloud.jobs import InMemoryQueue
from vision_shared.schemas import Event

from .conftest import T0, World, auth, make_event


def test_duplicate_submissions_create_one_event(world: World, queue: InMemoryQueue) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    event = make_event(a.site_ids[0], a.camera_ids[0], a.rule_id)
    first = c.post("/device/v1/events", json=event, headers=dev)
    assert first.status_code == 201 and first.json()["status"] == "created"
    for _ in range(3):
        dup = c.post("/device/v1/events", json=event, headers=dev)
        assert dup.status_code == 200 and dup.json()["status"] == "unchanged"
    items = c.get(f"/api/v1/events?rule_id={a.rule_id}", headers=auth(a.owner_token)).json()[
        "items"
    ]
    assert [e["id"] for e in items].count(event["id"]) == 1
    created = [j for j in queue.jobs if j[0] == "event.created" and j[1]["event_id"] == event["id"]]
    assert len(created) == 1


def test_cleared_version_updates_event(world: World, queue: InMemoryQueue) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    event = make_event(a.site_ids[0], a.camera_ids[0], a.rule_id)
    assert c.post("/device/v1/events", json=event, headers=dev).status_code == 201
    cleared = {
        **event,
        "state": "cleared",
        "cleared_at": (T0 + timedelta(minutes=2)).isoformat(),
        "value": 1,
        "snapshot_key": "media/local-path.jpg",  # edge-local path: ignored by the cloud
    }
    r = c.post("/device/v1/events", json=cleared, headers=dev)
    assert r.status_code == 200 and r.json()["status"] == "updated"
    # Going back to triggered is not possible.
    assert c.post("/device/v1/events", json=event, headers=dev).json()["status"] == "unchanged"
    detail = c.get(f"/api/v1/events/{event['id']}", headers=auth(a.owner_token)).json()
    assert detail["state"] == "cleared" and detail["value"] == 1
    assert detail["snapshot_key"] is None
    assert Event.model_validate(
        {k: v for k, v in detail.items() if k in Event.model_fields}
    ).cleared_at == T0 + timedelta(minutes=2)
    assert (
        "event.cleared",
        {"organisation_id": a.org_id, "site_id": a.site_ids[0], "event_id": event["id"]},
    ) in queue.jobs


def test_event_validation(world: World) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    naive = make_event(a.site_ids[0], a.camera_ids[0])
    naive["triggered_at"] = "2026-11-01T09:00:00"
    r = c.post("/device/v1/events", json=naive, headers=dev)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    extra = {**make_event(a.site_ids[0], a.camera_ids[0]), "unexpected": 1}
    assert c.post("/device/v1/events", json=extra, headers=dev).status_code == 422
    other_site = make_event(a.site_ids[1], a.camera_ids[1])  # device belongs to site 1
    r = c.post("/device/v1/events", json=other_site, headers=dev)
    assert r.status_code == 422 and "site" in r.json()["error"]["message"]
    long_id = make_event(a.site_ids[0], a.camera_ids[0], id="x" * 65)
    assert c.post("/device/v1/events", json=long_id, headers=dev).status_code == 422


def test_batch_has_per_item_results(world: World) -> None:
    c, a = world.client, world.a
    good = make_event(a.site_ids[0], a.camera_ids[0])
    bad = make_event(a.site_ids[0], "no-such-camera")
    r = c.post(
        "/device/v1/events/batch",
        json={"events": [good, bad, good]},
        headers=auth(a.device_token),
    )
    assert r.status_code == 200
    statuses = [x["status"] for x in r.json()["results"]]
    assert statuses == ["created", "rejected", "unchanged"]


def test_snapshot_and_clip_upload_flow(world: World, queue: InMemoryQueue) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    eid = a.event_id
    r = c.post(
        f"/device/v1/events/{eid}/uploads", json={"kinds": ["snapshot", "clip"]}, headers=dev
    )
    assert r.status_code == 200, r.text
    uploads = {u["kind"]: u for u in r.json()["uploads"]}
    snap_key = uploads["snapshot"]["key"]
    assert snap_key == f"{a.org_id}/{a.site_ids[0]}/{a.camera_ids[0]}/2026/11/01/{eid}/snapshot.jpg"
    # Finalising before uploading is refused.
    r = c.post(f"/device/v1/events/{eid}/finalise", json={"snapshot": True}, headers=dev)
    assert r.status_code == 409 and r.json()["error"]["code"] == "media_missing"
    # Upload through the signed URLs (local storage backend serves them).
    for kind, payload in (("snapshot", b"\xff\xd8jpeg"), ("clip", b"mp4-bytes")):
        u = uploads[kind]
        parts = urlsplit(u["url"])
        put = c.put(f"{parts.path}?{parts.query}", content=payload, headers=u["headers"])
        assert put.status_code == 204, put.text
    # A tampered signature is refused.
    parts = urlsplit(uploads["clip"]["url"])
    tampered = parts.query.replace("signature=", "signature=0")
    assert c.put(f"{parts.path}?{tampered}", content=b"x").status_code == 403
    r = c.post(
        f"/device/v1/events/{eid}/finalise", json={"snapshot": True, "clip": True}, headers=dev
    )
    assert r.status_code == 200
    assert r.json()["clip_key"].endswith("/clip.mp4")
    assert any(j[0] == "event.media_ready" for j in queue.jobs)
    # The dashboard gets short-lived view URLs that work.
    detail = c.get(f"/api/v1/events/{eid}", headers=auth(a.owner_token)).json()
    view = urlsplit(detail["snapshot_url"])
    got = c.get(f"{view.path}?{view.query}")
    assert got.status_code == 200 and got.content == b"\xff\xd8jpeg"
    assert c.get(view.path).status_code == 422  # unsigned URL refused (missing signature)


def test_events_only_site_refuses_media(world: World) -> None:
    c, a = world.client, world.a
    r = c.patch(
        f"/api/v1/sites/{a.site_ids[0]}", json={"events_only": True}, headers=auth(a.owner_token)
    )
    assert r.status_code == 200
    r = c.post(
        f"/device/v1/events/{a.event_id}/uploads",
        json={"kinds": ["clip"]},
        headers=auth(a.device_token),
    )
    assert r.status_code == 409
    config = c.get("/device/v1/config", headers=auth(a.device_token)).json()
    assert config["events_only"] is True


def test_aggregates_upsert(world: World) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    rows = [
        {
            "camera_id": a.camera_ids[0],
            "minute": (T0 + timedelta(minutes=i)).isoformat(),
            "metric": "occupancy",
            "target": "desk",
            "value": float(i),
        }
        for i in range(5)
    ]
    r = c.post("/device/v1/aggregates", json={"rows": rows}, headers=dev)
    assert r.status_code == 200 and r.json() == {"accepted": 5}
    rows[0]["value"] = 42.0
    r = c.post("/device/v1/aggregates", json={"rows": rows[:1]}, headers=dev)
    assert r.json() == {"accepted": 1}
    from sqlalchemy import select

    from vision_cloud.db import tenant_session
    from vision_cloud.models import AggregateMinute

    with tenant_session(c.app.state.vision.sessions, a.org_id) as db:  # type: ignore[attr-defined]
        values = db.scalars(select(AggregateMinute.value).order_by(AggregateMinute.minute)).all()
    assert values == [42.0, 1.0, 2.0, 3.0, 4.0]
    bad = [{**rows[0], "minute": "2026-11-01T09:00:30+00:00"}]
    assert c.post("/device/v1/aggregates", json={"rows": bad}, headers=dev).status_code == 422
    other = [{**rows[0], "camera_id": world.b.camera_ids[0]}]
    assert c.post("/device/v1/aggregates", json={"rows": other}, headers=dev).status_code == 422


def test_burst_of_10000_events_is_accepted(world: World) -> None:
    """CLD-05 done-when: a 10,000-event burst (outbox replay in batches of 500)."""
    c, a = world.client, world.a
    dev = auth(a.device_token)
    started = time.monotonic()
    total = 0
    for batch in range(20):
        events = [
            make_event(
                a.site_ids[0],
                a.camera_ids[0],
                a.rule_id,
                id=f"burst-{batch:02d}-{i:03d}",
                at=T0 + timedelta(seconds=batch * 500 + i),
            )
            for i in range(500)
        ]
        r = c.post("/device/v1/events/batch", json={"events": events}, headers=dev)
        assert r.status_code == 200, r.text
        total += sum(1 for x in r.json()["results"] if x["status"] == "created")
    assert total == 10_000
    elapsed = time.monotonic() - started
    assert elapsed < 300, f"burst took {elapsed:.0f}s"
    page = c.get("/api/v1/events?limit=1", headers=auth(a.owner_token)).json()
    assert page["items"][0]["id"] == "burst-19-499"
