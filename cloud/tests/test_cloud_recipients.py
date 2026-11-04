"""CLD-08 (part 1): alert recipients API, validation, permissions and tenant isolation."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import select

from vision_cloud.db import system_session
from vision_cloud.models import AuditLog

from .conftest import World, auth

PHONE = "+966501234567"


def body(**kw: Any) -> dict[str, Any]:
    return {"name": "Duty manager", "channel": "whatsapp", "address": PHONE, **kw}


def test_owner_manages_a_site_recipient(world: World, app: FastAPI) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    r = c.post(
        "/api/v1/recipients",
        json=body(
            site_id=a.site_ids[0],
            name_ar="مدير المناوبة",
            language="ar",
            min_severity="critical",
            quiet_hours_start="23:00",
            quiet_hours_end="07:00",
            daily_cap=20,
            escalation_rank=1,
            rule_ids=[a.rule_id],
        ),
        headers=owner,
    )
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["rule_ids"] == [a.rule_id] and rec["name_ar"] == "مدير المناوبة"
    assert (rec["quiet_hours_start"], rec["quiet_hours_end"]) == ("23:00", "07:00")

    r = c.patch(
        f"/api/v1/recipients/{rec['id']}",
        json={"quiet_hours_start": None, "quiet_hours_end": None, "rule_ids": [], "daily_cap": 5},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["quiet_hours_start"] is None and r.json()["rule_ids"] == []
    assert r.json()["daily_cap"] == 5

    listed = c.get(f"/api/v1/recipients?site_id={a.site_ids[0]}", headers=owner).json()
    assert [x["id"] for x in listed] == [rec["id"]]
    assert c.get(f"/api/v1/recipients?site_id={a.site_ids[1]}", headers=owner).json() == []

    assert c.delete(f"/api/v1/recipients/{rec['id']}", headers=owner).status_code == 204
    assert c.get(f"/api/v1/recipients/{rec['id']}", headers=owner).status_code == 404

    with system_session(app.state.vision.sessions) as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.entity_id == rec["id"])).all()
    assert [log.action for log in logs] == [
        "recipient.created",
        "recipient.updated",
        "recipient.deleted",
    ]
    assert all(PHONE not in str(log.details) for log in logs)  # no personal data in the audit log


def test_validation(world: World) -> None:
    c, a, b = world.client, world.a, world.b
    owner = auth(a.owner_token)
    bad = [
        body(address="0501234567"),  # not international
        body(channel="telegram", address="@someone"),  # Telegram needs the numeric chat id
        body(channel="email", address="not-an-email"),
        body(quiet_hours_start="23:00"),  # only one end
        body(quiet_hours_start="25:00", quiet_hours_end="06:00"),
        body(quiet_hours_start="08:00", quiet_hours_end="08:00"),
        body(daily_cap=0),
        body(site_id=a.site_ids[1], rule_ids=[a.rule_id]),  # rule of another site
        body(rule_ids=[b.rule_id]),  # another tenant's rule
        body(site_id=b.site_ids[0]),  # another tenant's site
        body(unknown_field=1),
    ]
    for payload in bad:
        r = c.post("/api/v1/recipients", json=payload, headers=owner)
        assert r.status_code in (404, 422), (payload, r.status_code, r.text)

    ok = c.post("/api/v1/recipients", json=body(site_id=a.site_ids[0]), headers=owner).json()
    r = c.patch(f"/api/v1/recipients/{ok['id']}", json={"channel": "telegram"}, headers=owner)
    assert r.status_code == 422  # a phone number is not a Telegram chat id
    r = c.patch(
        f"/api/v1/recipients/{ok['id']}",
        json={"channel": "telegram", "address": "123456789"},
        headers=owner,
    )
    assert r.status_code == 200 and r.json()["channel"] == "telegram"
    assert (
        c.patch(f"/api/v1/recipients/{ok['id']}", json={"name": None}, headers=owner).status_code
        == 422
    )


def test_roles_and_sites(world: World) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    org_wide = c.post("/api/v1/recipients", json=body(name="Owner"), headers=owner).json()
    site2 = c.post(
        "/api/v1/recipients", json=body(name="Site 2", site_id=a.site_ids[1]), headers=owner
    ).json()

    sm = auth(world.invite(a, "sm@alpha.test", "site_manager", [a.site_ids[0]]))
    mine = c.post("/api/v1/recipients", json=body(site_id=a.site_ids[0]), headers=sm)
    assert mine.status_code == 201
    assert c.post("/api/v1/recipients", json=body(), headers=sm).status_code == 403  # org-wide
    seen = {x["id"] for x in c.get("/api/v1/recipients", headers=sm).json()}
    assert seen == {org_wide["id"], mine.json()["id"]}  # not site 2's
    assert c.get(f"/api/v1/recipients/{site2['id']}", headers=sm).status_code == 404
    assert (
        c.patch(
            f"/api/v1/recipients/{org_wide['id']}", json={"daily_cap": 1}, headers=sm
        ).status_code
        == 403
    )  # may read, not change, organisation-wide recipients

    viewer = auth(world.invite(a, "v@alpha.test", "viewer", [a.site_ids[0]]))
    assert c.get("/api/v1/recipients", headers=viewer).status_code == 403
    summary = c.get(f"/api/v1/sites/{a.site_ids[0]}/recipients", headers=viewer)
    assert summary.status_code == 200
    assert {x["id"] for x in summary.json()} == {org_wide["id"], mine.json()["id"]}
    assert all(set(x) == {"id", "name", "name_ar", "channel"} for x in summary.json())
    assert c.get(f"/api/v1/sites/{a.site_ids[1]}/recipients", headers=viewer).status_code == 404


def test_other_tenants_cannot_see_or_touch(world: World) -> None:
    c, a, b = world.client, world.a, world.b
    rec = c.post("/api/v1/recipients", json=body(), headers=auth(a.owner_token)).json()
    other = auth(b.owner_token)
    assert c.get(f"/api/v1/recipients/{rec['id']}", headers=other).status_code == 404
    assert (
        c.patch(f"/api/v1/recipients/{rec['id']}", json={"daily_cap": 1}, headers=other).status_code
        == 404
    )
    assert c.delete(f"/api/v1/recipients/{rec['id']}", headers=other).status_code == 404
    assert c.get("/api/v1/recipients", headers=other).json() == []


def test_disabled_recipients_and_deleted_rules(world: World) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    rec = c.post(
        "/api/v1/recipients",
        json=body(site_id=a.site_ids[0], rule_ids=[a.rule_id], enabled=False),
        headers=owner,
    ).json()
    assert c.get(f"/api/v1/sites/{a.site_ids[0]}/recipients", headers=owner).json() == []
    assert c.delete(f"/api/v1/rules/{a.rule_id}", headers=owner).status_code == 204
    assert c.get(f"/api/v1/recipients/{rec['id']}", headers=owner).json()["rule_ids"] == []
