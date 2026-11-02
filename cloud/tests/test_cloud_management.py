"""CLD-07 minimal: sites, cameras, rules CRUD and the event list / detail / feedback."""

from __future__ import annotations

from datetime import timedelta

from .conftest import T0, World, auth, make_event


def test_event_filters_and_pagination(world: World) -> None:
    c, a = world.client, world.a
    dev, owner = auth(a.device_token), auth(a.owner_token)
    events = [
        make_event(
            a.site_ids[0],
            a.camera_ids[0],
            "r-crit" if i % 3 == 0 else "r-warn",
            id=f"ev-{i:02d}",
            severity="critical" if i % 3 == 0 else "warning",
            at=T0 + timedelta(hours=1, minutes=i),
        )
        for i in range(12)
    ]
    r = c.post("/device/v1/events/batch", json={"events": events}, headers=dev)
    assert r.status_code == 200

    page = c.get("/api/v1/events?limit=5", headers=owner).json()
    assert [e["id"] for e in page["items"]] == ["ev-11", "ev-10", "ev-09", "ev-08", "ev-07"]
    seen = [e["id"] for e in page["items"]]
    while page["next_cursor"]:
        page = c.get(f"/api/v1/events?limit=5&cursor={page['next_cursor']}", headers=owner).json()
        seen += [e["id"] for e in page["items"]]
    assert len(seen) == 13 and len(set(seen)) == 13  # 12 + the fixture's event

    crit = c.get("/api/v1/events?severity=critical", headers=owner).json()["items"]
    assert {e["id"] for e in crit} == {"ev-00", "ev-03", "ev-06", "ev-09"}
    both = c.get("/api/v1/events?severity=critical&severity=warning", headers=owner).json()
    assert len(both["items"]) == 13
    by_rule = c.get("/api/v1/events?rule_id=r-crit", headers=owner).json()["items"]
    assert len(by_rule) == 4
    window = c.get(
        "/api/v1/events",
        params={
            "from": (T0 + timedelta(hours=1, minutes=2)).isoformat(),
            "to": (T0 + timedelta(hours=1, minutes=5)).isoformat(),
        },
        headers=owner,
    ).json()["items"]
    assert [e["id"] for e in window] == ["ev-04", "ev-03", "ev-02"]
    naive = c.get("/api/v1/events?from=2026-11-01T09:00:00", headers=owner)
    assert naive.status_code == 422
    assert c.get("/api/v1/events?cursor=%%%", headers=owner).status_code == 422
    by_cam = c.get(f"/api/v1/events?camera_id={a.camera_ids[1]}", headers=owner).json()
    assert by_cam["items"] == []
    assert c.get("/api/v1/events?state=cleared", headers=owner).json()["items"] == []
    assert len(c.get("/api/v1/events?status=new&limit=200", headers=owner).json()["items"]) == 13


def test_feedback_sets_verified(world: World) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    r = c.post(
        f"/api/v1/events/{a.event_id}/feedback",
        json={"is_true": False, "comment": "a mannequin"},
        headers=owner,
    )
    assert r.status_code == 201 and r.json()["channel"] == "dashboard"
    detail = c.get(f"/api/v1/events/{a.event_id}", headers=owner).json()
    assert detail["verified"] is False
    assert [f["comment"] for f in detail["feedback"]] == ["a mannequin"]
    assert len(c.get("/api/v1/events?verified=false", headers=owner).json()["items"]) == 1
    assert c.get("/api/v1/events?verified=true", headers=owner).json()["items"] == []


def test_site_and_camera_crud(world: World) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    r = c.patch(
        f"/api/v1/sites/{a.site_ids[0]}",
        json={"name": "Olaya branch", "timezone": "Asia/Dubai"},
        headers=owner,
    )
    assert r.status_code == 200 and r.json()["timezone"] == "Asia/Dubai"
    bad_tz = c.patch(
        f"/api/v1/sites/{a.site_ids[0]}", json={"timezone": "Mars/Base"}, headers=owner
    )
    assert bad_tz.status_code == 422

    cam = c.get(f"/api/v1/cameras/{a.camera_ids[0]}", headers=owner).json()
    assert cam["source_redacted"] == "rtsp://***@10.0.0.1:554/Streaming/Channels/102"
    assert "secret" not in str(cam)
    # Out-of-range coordinates are refused by the shared Zone schema.
    r = c.patch(
        f"/api/v1/cameras/{a.camera_ids[0]}",
        json={"zones": [{"id": "desk", "polygon": [[0, 0], [2, 0], [1, 1]]}]},
        headers=owner,
    )
    assert r.status_code == 422
    # Removing a zone a rule depends on is refused (the site config would be invalid).
    r = c.patch(f"/api/v1/cameras/{a.camera_ids[0]}", json={"zones": []}, headers=owner)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_site_config"
    # Editing the zone in place keeps the rule valid.
    r = c.patch(
        f"/api/v1/cameras/{a.camera_ids[0]}",
        json={
            "zones": [
                {"id": "desk", "name": "Desk", "polygon": [[0.2, 0.2], [0.6, 0.2], [0.6, 0.6]]},
                {"id": "queue", "polygon": [[0.6, 0.6], [0.9, 0.6], [0.9, 0.9]]},
            ],
            "source": "rtsp://viewer:new@10.0.0.9/stream",
        },
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert [z["id"] for z in r.json()["zones"]] == ["desk", "queue"]
    assert r.json()["source_redacted"] == "rtsp://***@10.0.0.9/stream"
    dup = c.patch(
        f"/api/v1/cameras/{a.camera_ids[0]}",
        json={"lines": [{"id": "desk", "start": [0, 0], "end": [1, 1]}]},
        headers=owner,
    )
    assert dup.status_code == 422


def test_rule_crud_uses_shared_validation(world: World) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    # presence_after_hours needs a schedule (shared Rule validator).
    r = c.post(
        "/api/v1/rules",
        json={"type": "presence_after_hours", "camera_id": a.camera_ids[1], "zone_id": "desk"},
        headers=owner,
    )
    assert r.status_code == 422
    # Unknown zone on the camera.
    r = c.post(
        "/api/v1/rules",
        json={"type": "zone_empty", "camera_id": a.camera_ids[1], "zone_id": "nope"},
        headers=owner,
    )
    assert r.status_code == 422
    r = c.post(
        "/api/v1/rules",
        json={
            "type": "line_crossing",
            "camera_id": a.camera_ids[1],
            "line_id": "door",
            "direction": "in",
            "threshold": 20,
            "window_s": 3600,
            "severity": "info",
        },
        headers=owner,
    )
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["site_id"] == a.site_ids[1] and rule["direction"] == "in"
    listed = c.get(f"/api/v1/rules?site_id={a.site_ids[1]}", headers=owner).json()
    assert [x["id"] for x in listed] == [rule["id"]]
    # Moving a rule to a camera of another site is refused.
    body = {k: v for k, v in rule.items() if k not in ("site_id", "created_at", "updated_at")}
    body["camera_id"] = a.camera_ids[0]
    assert c.put(f"/api/v1/rules/{rule['id']}", json=body, headers=owner).status_code == 422
    assert c.delete(f"/api/v1/rules/{rule['id']}", headers=owner).status_code == 204
    assert c.get(f"/api/v1/rules/{rule['id']}", headers=owner).status_code == 404


def test_audit_log_records_changes(world: World) -> None:
    from sqlalchemy import select

    from vision_cloud.db import tenant_session
    from vision_cloud.models import AuditLog

    c, a = world.client, world.a
    c.patch(f"/api/v1/sites/{a.site_ids[0]}", json={"name": "x"}, headers=auth(a.owner_token))
    with tenant_session(c.app.state.vision.sessions, a.org_id) as db:  # type: ignore[attr-defined]
        actions = set(db.scalars(select(AuditLog.action)).all())
    assert {
        "site.created",
        "camera.created",
        "rule.created",
        "device.enrolled",
        "site.updated",
    } <= actions
