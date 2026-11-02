"""CLD-05: duplicate submissions create one event; a 10,000-event burst is accepted."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import Tenant, auth, enrol_device, login, make_tenant
from vision_cloud import models as m
from vision_cloud.db import system_session

T0 = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)


def event(tenant: Tenant, **kw: Any) -> dict[str, Any]:
    """An event exactly as the edge OutboxSink writes it (vision_shared Event JSON)."""
    ev_id = kw.pop("id", str(uuid.uuid4()))
    return {
        "schema_version": "1.0",
        "id": ev_id,
        "site_id": tenant.site_key,
        "camera_id": "counter",
        "rule_id": "queue",
        "rule_type": "queue_length_over",
        "severity": "warning",
        "state": "triggered",
        "condition_started_at": (T0 - timedelta(seconds=20)).isoformat(),
        "triggered_at": T0.isoformat(),
        "cleared_at": None,
        "value": 5.0,
        "message": "5 people in Counter queue",
        "attributes": {"zone_id": "counter_queue"},
        "snapshot_key": f"media/{ev_id}.jpg",
        "clip_key": None,
        "needs_verification": False,
        "created_at": T0.isoformat(),
        **kw,
    }


def _bearer(cred: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {cred}"}


def _count(sessions: sessionmaker[Session]) -> int:
    with system_session(sessions) as db:
        return int(db.scalar(select(func.count()).select_from(m.EventRow)) or 0)


def test_duplicate_submission_creates_one_event(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    ev = event(a)
    r1 = client.post("/device/v1/events", json=ev, headers=_bearer(cred))
    r2 = client.post("/device/v1/events", json=ev, headers=_bearer(cred))
    assert (r1.status_code, r1.json()["status"]) == (201, "created")
    assert (r2.status_code, r2.json()["status"]) == (200, "duplicate")
    assert _count(sessions) == 1
    # The retry gets a fresh upload form because the snapshot is still pending.
    assert r2.json()["snapshot_upload"]["key"] == r1.json()["snapshot_upload"]["key"]

    owner = auth(login(client, a.owner_email))
    page = client.get(f"/api/v1/orgs/{a.org_id}/events", headers=owner).json()
    assert len(page["items"]) == 1
    item = page["items"][0]
    assert item["rule_key"] == "queue" and item["rule_id"] and item["snapshot_state"] == "pending"


def test_cleared_version_and_clip_update_the_event(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    ev = event(a)
    client.post("/device/v1/events", json=ev, headers=_bearer(cred))
    cleared = {
        **ev,
        "state": "cleared",
        "cleared_at": (T0 + timedelta(minutes=3)).isoformat(),
        "clip_key": f"media/{ev['id']}.mp4",
    }
    r = client.post("/device/v1/events", json=cleared, headers=_bearer(cred))
    assert r.status_code == 200 and r.json()["status"] == "updated"
    assert r.json()["clip_upload"]["key"].endswith(f"/{ev['id']}/clip.mp4")
    # A late copy of the older version does not undo the cleared state.
    r = client.post("/device/v1/events", json=ev, headers=_bearer(cred))
    assert r.json()["status"] == "duplicate"
    with system_session(sessions) as db:
        row = db.get(m.EventRow, uuid.UUID(ev["id"]))
        assert row is not None
        assert row.state.value == "cleared" and row.clip_state is m.MediaState.PENDING


def test_media_upload_and_finalise(
    client: TestClient, app: Any, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    ev = event(a)
    receipt = client.post("/device/v1/events", json=ev, headers=_bearer(cred)).json()
    upload = receipt["snapshot_upload"]
    key = upload["key"]
    assert key == (f"{a.org_id}/{a.site_id}/{a.camera_id}/2026/11/02/{ev['id']}/snapshot.jpg")
    assert upload["fields"]["Content-Type"] == "image/jpeg"
    url = f"/device/v1/events/{ev['id']}/media/snapshot/finalise"
    r = client.post(url, headers=_bearer(cred))
    assert r.status_code == 409 and r.json()["error"]["code"] == "media_not_uploaded"

    app.state.store.put(key, b"\xff\xd8jpeg", "image/jpeg")  # the edge's POST to storage
    r = client.post(url, headers=_bearer(cred))
    assert r.status_code == 200 and r.json()["size_bytes"] == 6
    again = client.post("/device/v1/events", json=ev, headers=_bearer(cred)).json()
    assert again["snapshot_upload"] is None  # stored: nothing left to upload
    r = client.post(f"/device/v1/events/{ev['id']}/media/clip/finalise", headers=_bearer(cred))
    assert r.status_code == 409 and r.json()["error"]["code"] == "media_not_expected"


def test_events_only_site_gets_no_upload_forms(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    with system_session(sessions) as db:
        site = db.get(m.Site, a.site_id)
        assert site is not None
        site.events_only = True
        db.commit()
    cred = enrol_device(client, sessions, a)
    r = client.post(
        "/device/v1/events", json=event(a, clip_key="media/c.mp4"), headers=_bearer(cred)
    )
    assert r.status_code == 201
    assert r.json()["snapshot_upload"] is None and r.json()["clip_upload"] is None


def test_validation_and_site_checks(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    naive = event(a, triggered_at="2026-11-02T09:30:00")
    r = client.post("/device/v1/events", json=naive, headers=_bearer(cred))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_event"
    r = client.post("/device/v1/events", json=event(a, site_id="elsewhere"), headers=_bearer(cred))
    assert r.status_code == 422 and r.json()["error"]["code"] == "site_mismatch"
    r = client.post("/device/v1/events", json=event(a, camera_id="nope"), headers=_bearer(cred))
    assert r.json()["error"]["code"] == "unknown_camera"
    r = client.post("/device/v1/events", json=event(a, id="not-a-uuid"), headers=_bearer(cred))
    assert r.json()["error"]["code"] == "invalid_id"
    r = client.post("/device/v1/events", json=event(a, surprise=1), headers=_bearer(cred))
    assert r.status_code == 422  # the shared schema forbids unknown fields
    # A rule deleted in the cloud while the box still runs it: kept, with the rule key.
    r = client.post("/device/v1/events", json=event(a, rule_id="old_rule"), headers=_bearer(cred))
    assert r.status_code == 201
    assert _count(sessions) == 1


def test_event_id_of_another_organisation_is_refused(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    b = make_tenant(sessions, "org-b")
    cred_a = enrol_device(client, sessions, a)
    cred_b = enrol_device(client, sessions, b)
    ev_id = str(uuid.uuid4())
    assert (
        client.post(
            "/device/v1/events", json=event(a, id=ev_id), headers=_bearer(cred_a)
        ).status_code
        == 201
    )
    r = client.post("/device/v1/events", json=event(b, id=ev_id), headers=_bearer(cred_b))
    assert r.status_code == 409 and r.json()["error"]["code"] == "id_conflict"
    with system_session(sessions) as db:
        row = db.get(m.EventRow, uuid.UUID(ev_id))
        assert row is not None and row.organisation_id == a.org_id
    # B cannot finalise A's event either.
    r = client.post(f"/device/v1/events/{ev_id}/media/snapshot/finalise", headers=_bearer(cred_b))
    assert r.status_code == 404


def test_batch_rejects_items_individually(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    good = event(a)
    cleared = {**good, "state": "cleared", "cleared_at": (T0 + timedelta(minutes=1)).isoformat()}
    batch = [good, event(a, camera_id="nope"), {"garbage": True}, cleared, good]
    r = client.post("/device/v1/events/batch", json={"events": batch}, headers=_bearer(cred))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["status"] for x in body["receipts"]] == ["created", "updated", "duplicate"]
    assert [(x["index"], x["code"]) for x in body["rejected"]] == [
        (1, "unknown_camera"),
        (2, "invalid_event"),
    ]
    assert _count(sessions) == 1


def test_ten_thousand_event_burst(
    client: TestClient, app: Any, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    size = app.state.settings.max_batch_events
    events = [event(a) for _ in range(10_000)]
    started = time.monotonic()
    created = 0
    for i in range(0, len(events), size):
        r = client.post(
            "/device/v1/events/batch", json={"events": events[i : i + size]}, headers=_bearer(cred)
        )
        assert r.status_code == 200, r.text
        assert r.json()["rejected"] == []
        created += sum(x["status"] == "created" for x in r.json()["receipts"])
    elapsed = time.monotonic() - started
    assert created == 10_000 and _count(sessions) == 10_000
    # Replaying the whole burst (outbox retry after a lost response) adds nothing.
    for i in range(0, len(events), size):
        r = client.post(
            "/device/v1/events/batch", json={"events": events[i : i + size]}, headers=_bearer(cred)
        )
        assert {x["status"] for x in r.json()["receipts"]} == {"duplicate"}
    assert _count(sessions) == 10_000
    assert elapsed < 120, f"burst took {elapsed:.1f}s"


def test_batch_size_limit(client: TestClient, app: Any, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    too_many = [event(a) for _ in range(app.state.settings.max_batch_events + 1)]
    r = client.post("/device/v1/events/batch", json={"events": too_many}, headers=_bearer(cred))
    assert r.status_code == 413


def test_aggregates_upsert(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    minute = T0.replace(second=0).isoformat()
    body = {
        "site_id": a.site_key,
        "items": [
            {"camera_id": "counter", "minute": minute, "occupancy_max": 4, "entries": 3},
            {"camera_id": "ghost", "minute": minute, "entries": 1},
        ],
    }
    r = client.post("/device/v1/aggregates", json=body, headers=_bearer(cred))
    assert r.status_code == 200 and r.json()["accepted"] == 1
    body["items"][0]["entries"] = 5
    client.post("/device/v1/aggregates", json=body, headers=_bearer(cred))
    with system_session(sessions) as db:
        rows = db.query(m.AggregateMinute).all()
    assert len(rows) == 1 and rows[0].entries == 5
    bad = {
        "site_id": a.site_key,
        "items": [{"camera_id": "counter", "minute": T0.replace(second=7).isoformat()}],
    }
    assert client.post("/device/v1/aggregates", json=bad, headers=_bearer(cred)).status_code == 422


def test_shared_event_model_round_trips(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    """What `vision_shared.schemas.Event.model_dump_json()` produces on the edge is accepted as is."""
    from vision_shared.schemas import Event, RuleType, Severity

    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    ev = Event(
        site_id=a.site_key,
        camera_id="counter",
        rule_id="counter_unattended",
        rule_type=RuleType.ZONE_EMPTY,
        severity=Severity.CRITICAL,
        condition_started_at=T0,
        triggered_at=T0,
        value=0,
    )
    r = client.post(
        "/device/v1/events",
        content=ev.model_dump_json(),
        headers={**_bearer(cred), "Content-Type": "application/json"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["snapshot_upload"] is None  # no snapshot_key on the edge: nothing to upload
