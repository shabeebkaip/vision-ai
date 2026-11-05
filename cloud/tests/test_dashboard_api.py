"""CLD-07: the endpoints the dashboard reads (site summaries, site overview, rules with
recipients, event filters), in the shapes of the dashboard's API contract (web/README.md)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI

from vision_cloud.db import system_session
from vision_cloud.models import Alert, Camera, EventRow

from .conftest import T0, World, auth, make_event

RIYADH = timezone(timedelta(hours=3))


def add_alert(
    app: FastAPI, world: World, at: datetime, rule_type: str = "queue_length_over"
) -> None:
    a = world.a
    with system_session(app.state.vision.sessions) as db:
        db.add(
            Alert(
                organisation_id=a.org_id,
                site_id=a.site_ids[0],
                camera_id=a.camera_ids[0],
                rule_id=a.rule_id,
                rule_type=rule_type,
                severity="warning",
                first_event_id="e",
                last_event_id="e",
                opened_at=at,
                last_event_at=at,
            )
        )
        db.commit()


def test_site_summaries(world: World, app: FastAPI) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    r = c.patch(
        f"/api/v1/sites/{a.site_ids[0]}",
        json={"name_ar": "فرع العليا", "industry": "restaurant", "city": "Riyadh"},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert (
        c.patch(
            f"/api/v1/sites/{a.site_ids[0]}", json={"industry": "spaceport"}, headers=owner
        ).status_code
        == 422
    )
    with system_session(app.state.vision.sessions) as db:
        cam = db.get(Camera, a.camera_ids[0])
        assert cam is not None
        cam.status = "online"
        db.commit()
    now = datetime.now(timezone.utc)
    add_alert(app, world, now)
    add_alert(app, world, now - timedelta(days=2))  # not today

    sites = {s["id"]: s for s in c.get("/api/v1/sites", headers=owner).json()}
    s1 = sites[a.site_ids[0]]
    assert (s1["name_ar"], s1["industry"], s1["city"]) == ("فرع العليا", "restaurant", "Riyadh")
    assert (s1["cameras_total"], s1["cameras_online"], s1["alerts_today"]) == (1, 1, 1)
    assert sites[a.site_ids[1]]["cameras_online"] == 0

    viewer = auth(world.invite(a, "v@alpha.test", "viewer", [a.site_ids[1]]))
    assert [s["id"] for s in c.get("/api/v1/sites", headers=viewer).json()] == [a.site_ids[1]]


def test_site_overview(world: World, app: FastAPI) -> None:
    c, a = world.client, world.a
    owner, dev = auth(a.owner_token), auth(a.device_token)
    day = datetime(2026, 11, 1, tzinfo=RIYADH)  # T0 = 12:00 Riyadh on this day
    add_alert(app, world, day + timedelta(hours=9))
    add_alert(app, world, day + timedelta(hours=15), "zone_empty")
    add_alert(app, world, day + timedelta(hours=23, minutes=30))
    add_alert(app, world, day - timedelta(minutes=30))  # 23:30 the day before: excluded
    add_alert(app, world, day + timedelta(days=1))  # midnight after: excluded

    # Reviewed events over the 7 days to that date: 2 correct, 1 false alarm, 1 unreviewed.
    ids = []
    for i, at in enumerate([T0, T0 - timedelta(days=3), T0 - timedelta(days=6), T0]):
        ev = make_event(a.site_ids[0], a.camera_ids[0], a.rule_id, at=at, id=f"ov-{i}")
        assert c.post("/device/v1/events", json=ev, headers=dev).status_code == 201
        ids.append(ev["id"])
    for eid, is_true in zip(ids[:3], [True, True, False], strict=True):
        c.post(f"/api/v1/events/{eid}/feedback", json={"is_true": is_true}, headers=owner)
    old = make_event(a.site_ids[0], a.camera_ids[0], a.rule_id, at=T0 - timedelta(days=8), id="old")
    c.post("/device/v1/events", json=old, headers=dev)
    c.post("/api/v1/events/old/feedback", json={"is_true": False}, headers=owner)  # too old

    # Footfall from the edge's per-minute counts: 09:xx and 18:xx Riyadh time.
    rows: list[dict[str, Any]] = []
    for hh, n_in, n_out in ((9, 3, 1), (18, 5, 4)):
        for m in range(2):
            minute = (day + timedelta(hours=hh, minutes=m)).astimezone(timezone.utc)
            for metric, value in (("count_in", n_in), ("count_out", n_out)):
                rows.append(
                    {
                        "camera_id": a.camera_ids[0],
                        "minute": minute.isoformat(),
                        "metric": metric,
                        "target": "door",
                        "value": float(value),
                    }
                )
    assert c.post("/device/v1/aggregates", json={"rows": rows}, headers=dev).status_code == 200

    r = c.get(f"/api/v1/sites/{a.site_ids[0]}/overview?date=2026-11-01", headers=owner)
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["date"] == "2026-11-01" and ov["alerts_total"] == 3
    assert ov["alerts_by_type"] == {"queue_length_over": 2, "zone_empty": 1}
    assert ov["reviewed_7d"] == 3 and abs(ov["false_alert_rate_7d"] - 1 / 3) < 0.001
    by_hour = {h["hour"]: (h["in"], h["out"]) for h in ov["footfall_by_hour"]}
    assert len(by_hour) == 24 and by_hour[9] == (6, 2) and by_hour[18] == (10, 8)
    assert by_hour[12] == (0, 0)
    assert (ov["cameras_total"], ov["cameras_online"]) == (1, 0)

    empty = c.get(f"/api/v1/sites/{a.site_ids[1]}/overview?date=2026-11-01", headers=owner).json()
    assert empty["false_alert_rate_7d"] is None and empty["alerts_by_type"] == {}
    assert (
        c.get(
            f"/api/v1/sites/{a.site_ids[0]}/overview", headers=auth(world.b.owner_token)
        ).status_code
        == 404
    )


def recipient(world: World, **kw: Any) -> str:
    body = {"name": "x", "channel": "telegram", "address": "123456", **kw}
    r = world.client.post("/api/v1/recipients", json=body, headers=auth(world.a.owner_token))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_rules_with_recipients(world: World) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    everyone = recipient(world, name="all rules")
    limited = recipient(world, name="limited", site_id=a.site_ids[0], rule_ids=[a.rule_id])
    critical_only = recipient(world, name="critical only", min_severity="critical")
    recipient(world, name="disabled", enabled=False)
    other_site = recipient(world, name="site 2", site_id=a.site_ids[1])

    [listed] = c.get(f"/api/v1/sites/{a.site_ids[0]}/rules", headers=owner).json()
    assert listed["rule"]["id"] == a.rule_id
    assert listed["recipient_ids"] == sorted([everyone, limited])

    rule = {
        "type": "zone_occupancy_over",
        "camera_id": a.camera_ids[0],
        "zone_id": "desk",
        "threshold": 4,
        "min_duration_s": 10,
        "severity": "critical",
        "name": "crowd at desk",
    }
    r = c.post(
        f"/api/v1/sites/{a.site_ids[0]}/rules",
        json={"rule": rule, "recipient_ids": [limited, everyone]},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["rule"]["id"]
    assert r.json()["recipient_ids"] == sorted([everyone, limited, critical_only])
    # The limited recipient now follows both rules; the unlimited one still follows every rule.
    got = c.get(f"/api/v1/recipients/{limited}", headers=owner).json()["rule_ids"]
    assert sorted(got) == sorted([a.rule_id, new_id])
    assert c.get(f"/api/v1/recipients/{everyone}", headers=owner).json()["rule_ids"] == []

    bad = [
        ({"rule": rule, "recipient_ids": [other_site]}, 422),  # recipient of another site
        ({"rule": {**rule, "zone_id": "nope"}, "recipient_ids": []}, 422),  # invalid rule
        ({"rule": {**rule, "camera_id": a.camera_ids[1]}, "recipient_ids": []}, 422),
        ({"rule": {**rule, "camera_id": world.b.camera_ids[0]}, "recipient_ids": []}, 404),
    ]
    for payload, code in bad:
        r = c.post(f"/api/v1/sites/{a.site_ids[0]}/rules", json=payload, headers=owner)
        assert r.status_code == code, (payload, r.text)
    viewer = auth(world.invite(a, "v2@alpha.test", "viewer", [a.site_ids[0]]))
    r = c.post(
        f"/api/v1/sites/{a.site_ids[0]}/rules",
        json={"rule": rule, "recipient_ids": []},
        headers=viewer,
    )
    assert r.status_code == 403
    assert len(c.get(f"/api/v1/sites/{a.site_ids[0]}/rules", headers=viewer).json()) == 2


def test_event_filters_by_rule_type_and_verdict(world: World, app: FastAPI) -> None:
    c, a = world.client, world.a
    owner, dev = auth(a.owner_token), auth(a.device_token)
    for i, rule_type in enumerate(["zone_empty", "zone_empty", "queue_length_over"]):
        ev = make_event(
            a.site_ids[0],
            a.camera_ids[0],
            a.rule_id,
            rule_type=rule_type,
            at=T0 + timedelta(minutes=i),
            id=f"f-{i}",
        )
        assert c.post("/device/v1/events", json=ev, headers=dev).status_code == 201
    c.post("/api/v1/events/f-0/feedback", json={"is_true": True}, headers=owner)
    c.post("/api/v1/events/f-1/feedback", json={"is_true": False}, headers=owner)

    def ids(query: str) -> set[str]:
        items = c.get(f"/api/v1/events?{query}", headers=owner).json()["items"]
        return {e["id"] for e in items if e["id"].startswith("f-")}

    assert ids("rule_type=zone_empty") == {"f-0", "f-1"}
    assert ids("verdict=correct") == {"f-0"}
    assert ids("verdict=false_alarm") == {"f-1"}
    assert ids("verdict=none") == {"f-2"}
    assert ids("rule_type=zone_empty&verdict=none") == set()
    assert c.get("/api/v1/events?verdict=maybe", headers=owner).status_code == 422
    with system_session(app.state.vision.sessions) as db:
        assert db.get(EventRow, "f-2") is not None
