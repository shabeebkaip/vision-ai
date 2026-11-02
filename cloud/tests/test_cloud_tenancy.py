"""CLD-02 done-when: a user of organisation A cannot read any row of organisation B through any
endpoint. Runs on SQLite (query-layer lock) and on PostgreSQL (query layer + RLS)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from vision_cloud.db import system_session, tenant_session
from vision_cloud.models import Camera, EventRow, Site, tenant_tables

from .conftest import World, auth, make_event

pytestmark = pytest.mark.usefixtures("world")


def _b_ids(world: World) -> set[str]:
    b = world.b
    return {
        b.org_id,
        *b.site_ids,
        *b.camera_ids,
        b.rule_id,
        b.device_id,
        b.event_id,
    }


def test_lists_only_show_own_rows(world: World) -> None:
    c, a, b = world.client, world.a, world.b
    h = auth(a.owner_token)
    sites = c.get("/api/v1/sites", headers=h).json()
    assert {s["id"] for s in sites} == set(a.site_ids)
    cams = c.get("/api/v1/cameras", headers=h).json()
    assert {x["id"] for x in cams} == set(a.camera_ids)
    events = c.get("/api/v1/events", headers=h).json()["items"]
    assert {e["id"] for e in events} == {a.event_id}
    rules = c.get("/api/v1/rules", headers=h).json()
    assert {r["id"] for r in rules} == {a.rule_id}
    devices = c.get("/api/v1/devices", headers=h).json()
    assert {d["id"] for d in devices} == {a.device_id}
    # Filtering by another tenant's id yields nothing rather than its rows.
    for path in (
        f"/api/v1/cameras?site_id={b.site_ids[0]}",
        f"/api/v1/rules?site_id={b.site_ids[0]}",
        f"/api/v1/rules?camera_id={b.camera_ids[0]}",
        f"/api/v1/devices?site_id={b.site_ids[0]}",
    ):
        assert c.get(path, headers=h).json() == [], path
    for q in ("site_id", "camera_id"):
        value = b.site_ids[0] if q == "site_id" else b.camera_ids[0]
        r = c.get(f"/api/v1/events?{q}={value}", headers=h)
        assert r.json()["items"] == []
    assert c.get(f"/api/v1/events?rule_id={b.rule_id}", headers=h).json()["items"] == []


def _concrete_paths(template: str, world: World) -> list[str]:
    """Fill every path parameter with B's id of the matching kind."""
    b = world.b
    values = {
        "site_id": b.site_ids[0],
        "camera_id": b.camera_ids[0],
        "rule_id": b.rule_id,
        "device_id": b.device_id,
        "event_id": b.event_id,
    }
    params = re.findall(r"{(\w+)}", template)
    if any(p not in values for p in params):
        return []
    path = template
    for p in params:
        path = path.replace("{" + p + "}", values[p])
    return [path]


def test_no_endpoint_reveals_another_tenant(world: World) -> None:
    """Walk every user-facing route (GET, and writes with an empty body) with organisation B's ids
    while signed in to A: nothing of B may come back, and nothing of B may change."""
    c = world.client
    h = auth(world.a.owner_token)
    secret_ids = _b_ids(world)
    checked = 0
    spec = c.get("/openapi.json").json()
    for template, operations in spec["paths"].items():
        if not template.startswith("/api/v1"):
            continue
        if template.startswith(("/api/v1/auth", "/api/v1/admin")):
            continue
        for path in _concrete_paths(template, world):
            for method in (m.upper() for m in operations):
                if method == "GET":
                    r = c.get(path, headers=h)
                else:
                    r = c.request(method, path, headers=h, json={})
                body = r.text
                leaked = [i for i in secret_ids if i in body]
                assert not leaked, f"{method} {path} leaked {leaked}: {body[:300]}"
                if any(i in path for i in secret_ids):
                    assert r.status_code in (404, 422), f"{method} {path} -> {r.status_code}"
                checked += 1
    assert checked >= 15

    # B's data is unchanged (none of the write attempts above touched it).
    hb = auth(world.b.owner_token)
    assert len(c.get("/api/v1/rules", headers=hb).json()) == 1
    detail = c.get(f"/api/v1/events/{world.b.event_id}", headers=hb).json()
    assert detail["feedback"] == []


def test_writes_to_another_tenant_are_404(world: World) -> None:
    c, a, b = world.client, world.a, world.b
    h = auth(a.owner_token)
    assert (
        c.patch(f"/api/v1/sites/{b.site_ids[0]}", json={"name": "x"}, headers=h).status_code == 404
    )
    assert (
        c.patch(f"/api/v1/cameras/{b.camera_ids[0]}", json={"name": "x"}, headers=h).status_code
        == 404
    )
    r = c.post(f"/api/v1/events/{b.event_id}/feedback", json={"is_true": False}, headers=h)
    assert r.status_code == 404
    assert c.delete(f"/api/v1/rules/{b.rule_id}", headers=h).status_code == 404
    assert c.post(f"/api/v1/devices/{b.device_id}/revoke", headers=h).status_code == 404
    r = c.post(
        "/api/v1/rules",
        json={"type": "zone_empty", "camera_id": b.camera_ids[0], "zone_id": "desk"},
        headers=h,
    )
    assert r.status_code == 404
    r = c.post(f"/api/v1/sites/{b.site_ids[0]}/cameras", json={"source": "rtsp://x"}, headers=h)
    assert r.status_code == 404
    r = c.post(
        "/api/v1/invitations",
        json={"email": "spy@example.test", "role": "viewer", "site_ids": [b.site_ids[0]]},
        headers=h,
    )
    assert r.status_code == 422


def test_device_cannot_touch_another_tenant(world: World) -> None:
    c, a, b = world.client, world.a, world.b
    dev = auth(a.device_token)
    # Event claiming B's site / camera.
    r = c.post("/device/v1/events", json=make_event(b.site_ids[0], b.camera_ids[0]), headers=dev)
    assert r.status_code == 422
    r = c.post("/device/v1/events", json=make_event(a.site_ids[0], b.camera_ids[0]), headers=dev)
    assert r.status_code == 422
    # Re-using B's event id is a conflict, and B's event is untouched.
    r = c.post(
        "/device/v1/events",
        json=make_event(a.site_ids[0], a.camera_ids[0], id=b.event_id),
        headers=dev,
    )
    assert r.status_code == 409
    r = c.post(f"/device/v1/events/{b.event_id}/uploads", json={"kinds": ["snapshot"]}, headers=dev)
    assert r.status_code == 404
    r = c.post(f"/device/v1/events/{b.event_id}/finalise", json={"snapshot": True}, headers=dev)
    assert r.status_code == 404
    config = c.get("/device/v1/config", headers=dev).json()
    assert config["id"] == a.site_ids[0]
    assert all(cam["id"] in a.camera_ids for cam in config["cameras"])


def test_query_layer_filters_without_explicit_where(world: World) -> None:
    """The tenant session adds the organisation filter to every ORM query by itself."""
    sessions = world.client.app.state.vision.sessions  # type: ignore[attr-defined]
    with tenant_session(sessions, world.a.org_id) as db:
        assert set(db.scalars(select(Site.id)).all()) == set(world.a.site_ids)
        assert set(db.scalars(select(Camera.id)).all()) == set(world.a.camera_ids)
        assert db.scalar(select(func.count()).select_from(EventRow)) == 1
        assert db.scalar(select(EventRow).where(EventRow.id == world.b.event_id)) is None
    with system_session(sessions) as db:
        assert db.scalar(select(func.count()).select_from(Site)) == 4


def test_session_without_tenant_sees_nothing(world: World) -> None:
    sessions = world.client.app.state.vision.sessions  # type: ignore[attr-defined]
    with sessions() as db:
        assert db.scalars(select(Site)).all() == []


@pytest.mark.postgres
@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
def test_postgres_rls_is_the_second_lock(world: World) -> None:
    """Raw SQL bypasses the ORM filter; row-level security must still hide B's rows."""
    sessions = world.client.app.state.vision.sessions  # type: ignore[attr-defined]
    with tenant_session(sessions, world.a.org_id) as db:
        for table in tenant_tables():
            others = db.execute(
                text(f"SELECT count(*) FROM {table} WHERE organisation_id <> :a"),
                {"a": world.a.org_id},
            ).scalar_one()
            assert others == 0, table
        assert db.execute(text("SELECT count(*) FROM sites")).scalar_one() == 2
        assert db.execute(text("SELECT count(*) FROM organisations")).scalar_one() == 1
        with pytest.raises(DBAPIError, match="row-level security"):
            db.execute(
                text(
                    "INSERT INTO sites (id, organisation_id, name, timezone, address, "
                    "opening_hours, events_only, created_at, updated_at) VALUES "
                    "('x', :b, 'evil', 'UTC', '', '{}', false, now(), now())"
                ),
                {"b": world.b.org_id},
            )
    with sessions() as db:  # no tenant context at all
        assert db.execute(text("SELECT count(*) FROM events")).scalar_one() == 0
