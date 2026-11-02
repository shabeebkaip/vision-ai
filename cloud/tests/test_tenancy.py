"""CLD-02: a user of organisation A cannot read any row of organisation B through any endpoint."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import Tenant, add_user, auth, enrol_device, login, make_tenant
from vision_cloud import models as m
from vision_cloud.db import set_context, system_session


def _event(tenant: Tenant, **kw: Any) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "site_id": tenant.site_key,
        "camera_id": "counter",
        "rule_id": "queue",
        "rule_type": "queue_length_over",
        "severity": "warning",
        "condition_started_at": now,
        "triggered_at": now,
        "value": 5,
        "message": "5 people waiting",
        "snapshot_key": "media/x.jpg",
        **kw,
    }


@pytest.fixture()
def two_orgs(
    client: TestClient, sessions: sessionmaker[Session]
) -> tuple[Tenant, Tenant, dict[str, uuid.UUID]]:
    a = make_tenant(sessions, "org-a")
    b = make_tenant(sessions, "org-b")
    # Give B one of everything so a leak would show up.
    cred = enrol_device(client, sessions, b)
    ev = _event(b)
    r = client.post("/device/v1/events", json=ev, headers={"Authorization": f"Bearer {cred}"})
    assert r.status_code == 201, r.text
    b_member = add_user(sessions, b, "viewer@org-b.test", "viewer")
    with system_session(sessions) as db:
        device = db.query(m.Device).filter(m.Device.organisation_id == b.org_id).one()
        db.add(
            m.Invitation(
                organisation_id=b.org_id,
                email="x@org-b.test",
                role=m.Role.VIEWER,
                site_ids=[],
                token_hash="0" * 64,
                expires_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    ids = {
        "org_id": b.org_id,
        "site_id": b.site_id,
        "camera_id": b.camera_id,
        "event_id": uuid.UUID(ev["id"]),
        "device_id": device.id,
        "user_id": b_member,
    }
    return a, b, ids


def test_rls_hides_every_row_of_other_organisations(
    two_orgs: tuple[Tenant, Tenant, dict[str, uuid.UUID]], sessions: sessionmaker[Session]
) -> None:
    """Raw SQL, no WHERE clause: the database itself returns nothing of organisation B."""
    a, b, _ = two_orgs
    with sessions() as db:
        set_context(db, org_id=a.org_id, user_id=a.owner_id)
        for table in m.TENANT_TABLES:
            leaked = db.execute(
                text(f"SELECT count(*) FROM {table} WHERE organisation_id = :b"), {"b": b.org_id}
            ).scalar_one()
            assert leaked == 0, f"{table} leaks rows of another organisation"
        orgs = db.execute(text("SELECT id FROM organisations")).scalars().all()
        assert orgs == [a.org_id]
        users = set(db.execute(text("SELECT id FROM users")).scalars().all())
        assert users == {a.owner_id}
        # Writes into another organisation are refused too.
        updated = db.execute(
            text("UPDATE sites SET name = 'x' WHERE id = :s RETURNING id"), {"s": b.site_id}
        ).all()
        assert updated == []
        with pytest.raises(Exception, match="row-level security"):
            db.execute(
                text(
                    "INSERT INTO sites (id, organisation_id, key, name, address, timezone, "
                    "opening_hours, events_only, clip_retention_days) VALUES "
                    "(gen_random_uuid(), :b, 'evil', '', '', 'UTC', '[]', false, 30)"
                ),
                {"b": b.org_id},
            )
        db.rollback()

    # Without any context nothing is visible at all.
    with sessions() as db:
        for table in (*m.TENANT_TABLES, "organisations", "users"):
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table


def _get_paths(app: Any) -> list[str]:
    """Every GET path of the dashboard API, from the OpenAPI document (covers nested routers)."""
    app.openapi_schema = None
    paths = app.openapi()["paths"]
    return sorted(p for p, ops in paths.items() if "get" in ops and p.startswith("/api/v1/"))


def test_no_endpoint_returns_another_organisations_data(
    client: TestClient,
    app: Any,
    sessions: sessionmaker[Session],
    two_orgs: tuple[Tenant, Tenant, dict[str, uuid.UUID]],
) -> None:
    """Calls every GET route with organisation B's ids, as each role of organisation A."""
    a, b, b_ids = two_orgs
    add_user(sessions, a, "manager@org-a.test", "manager")
    add_user(sessions, a, "viewer@org-a.test", "viewer")
    users = [a.owner_email, "manager@org-a.test", "viewer@org-a.test"]
    b_values = {str(v) for v in b_ids.values()}

    for email in users:
        headers = auth(login(client, email))
        paths = _get_paths(app)
        # Guard against this test silently checking nothing.
        assert len([p for p in paths if p.startswith("/api/v1/orgs/")]) >= 9, paths
        for route_path in paths:
            params = re.findall(r"{(\w+)}", route_path)
            if params == ["token"]:
                continue  # unauthenticated invitation preview, keyed by secret token
            for org_choice in ("own", "other"):
                values = {p: str(b_ids.get(p, uuid.uuid4())) for p in params}
                if "org_id" in values and org_choice == "own":
                    values["org_id"] = str(a.org_id)
                path = route_path.format(**values)
                r = client.get(path, headers=headers)
                assert r.status_code in {200, 403, 404}, (path, r.status_code, r.text)
                body = r.text
                for leaked in b_values:
                    assert leaked not in body, f"{email} GET {path} leaked {leaked}"
                if r.status_code == 200 and "org_id" in values and org_choice == "other":
                    pytest.fail(f"{email} could read {path}")
                # Query-string filters with B's ids return nothing either.
                if route_path.endswith(("/events", "/cameras")) and org_choice == "own":
                    r = client.get(path, params={"site_id": str(b.site_id)}, headers=headers)
                    assert r.status_code == 200
                    assert all(v not in r.text for v in b_values)


def test_admin_routes_need_platform_admin(
    client: TestClient, two_orgs: tuple[Tenant, Tenant, dict[str, uuid.UUID]]
) -> None:
    a, _, _ = two_orgs
    headers = auth(login(client, a.owner_email))
    assert client.get("/api/v1/admin/devices", headers=headers).status_code == 403


def test_site_limited_member_sees_only_their_sites(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    with system_session(sessions) as db:
        other = m.Site(organisation_id=a.org_id, key="second", name="Second branch")
        db.add(other)
        db.commit()
        other_id = other.id
    add_user(sessions, a, "sm@org-a.test", "site_manager", site_ids=[other_id])
    headers = auth(login(client, "sm@org-a.test"))
    sites = client.get(f"/api/v1/orgs/{a.org_id}/sites", headers=headers).json()
    assert [s["id"] for s in sites] == [str(other_id)]
    assert (
        client.get(f"/api/v1/orgs/{a.org_id}/sites/{a.site_id}", headers=headers).status_code == 404
    )
    assert client.get(f"/api/v1/orgs/{a.org_id}/cameras", headers=headers).json() == []


def test_viewer_cannot_invite_and_manager_cannot_invite_owner(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    add_user(sessions, a, "viewer@org-a.test", "viewer")
    add_user(sessions, a, "manager@org-a.test", "manager")
    url = f"/api/v1/orgs/{a.org_id}/invitations"
    viewer = auth(login(client, "viewer@org-a.test"))
    r = client.post(url, json={"email": "new@x.test", "role": "viewer"}, headers=viewer)
    assert r.status_code == 403
    manager = auth(login(client, "manager@org-a.test"))
    r = client.post(url, json={"email": "new@x.test", "role": "owner"}, headers=manager)
    assert r.status_code == 403
    r = client.post(url, json={"email": "new@x.test", "role": "viewer"}, headers=manager)
    assert r.status_code == 201


def test_removed_member_loses_access_immediately(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    uid = add_user(sessions, a, "viewer@org-a.test", "viewer")
    viewer = auth(login(client, "viewer@org-a.test"))
    assert client.get(f"/api/v1/orgs/{a.org_id}/sites", headers=viewer).status_code == 200
    owner = auth(login(client, a.owner_email))
    r = client.delete(f"/api/v1/orgs/{a.org_id}/members/{uid}", headers=owner)
    assert r.status_code == 204
    assert client.get(f"/api/v1/orgs/{a.org_id}/sites", headers=viewer).status_code == 404
    # ...and the last owner cannot be removed.
    r = client.delete(f"/api/v1/orgs/{a.org_id}/members/{a.owner_id}", headers=owner)
    assert r.status_code == 409


def test_platform_admin_can_read_any_organisation(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    b = make_tenant(sessions, "org-b")
    add_user(sessions, a, "ops@code-ox.test", "", platform_admin=True)
    headers = auth(login(client, "ops@code-ox.test"))
    for t in (a, b):
        r = client.get(f"/api/v1/orgs/{t.org_id}/sites", headers=headers)
        assert r.status_code == 200 and r.json()[0]["id"] == str(t.site_id)
