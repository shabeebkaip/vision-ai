"""CLD-08 (part 3): acknowledgement, escalation and the alerts API."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import FastAPI

from vision_cloud.jobs import InMemoryQueue
from vision_cloud.worker import HANDLERS, WorkerContext

from .alerting import alerts, log_rows, post_events, recipient, run_jobs, sent_messages
from .conftest import T0, World, auth


def run_due_escalation(ctx: WorkerContext, queue: InMemoryQueue) -> list[dict[str, Any]]:
    """Pretend the escalation delay passed: run the delayed escalation jobs, then their sends."""
    due = [(d, j, p) for d, j, p in queue.delayed if j == "alert.escalate"]
    queue.delayed.clear()
    for _, job, payload in due:
        HANDLERS[job](ctx, payload)
    run_jobs(ctx, queue)
    return [p for _, _, p in due]


def chain(world: World) -> dict[int | None, str]:
    return {
        None: recipient(world, name="duty manager")["id"],
        2: recipient(world, name="store manager", escalation_rank=2)["id"],
        3: recipient(world, name="area manager", escalation_rank=3)["id"],
    }


def test_unacknowledged_critical_alert_escalates_up_the_chain(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    people = chain(world)
    post_events(world, [T0 + timedelta(hours=11)], severity="critical")
    run_jobs(ctx, clean_queue)
    [alert] = [a for a in alerts(app, world.a.org_id) if a.severity == "critical"]
    assert alert.escalation_level == 0
    assert [(d, j) for d, j, _ in clean_queue.delayed] == [(600, "alert.escalate")]
    told = [(n.recipient_id, n.kind) for n in log_rows(app)]
    assert told == [(people[None], "alert")]

    assert run_due_escalation(ctx, clean_queue)[0]["rank"] == 2  # 10 minutes later
    assert [(n.recipient_id, n.kind) for n in log_rows(app)][-1] == (people[2], "escalation")
    assert "Escalated" in sent_messages()[-1][2].text
    run_due_escalation(ctx, clean_queue)  # 20 minutes
    assert [(n.recipient_id, n.kind) for n in log_rows(app)][-1] == (people[3], "escalation")
    run_due_escalation(ctx, clean_queue)  # nobody at rank 4: the chain ends
    assert clean_queue.delayed == []
    assert len(log_rows(app)) == 3
    assert alerts(app, world.a.org_id)[-1].escalation_level == 3


def test_acknowledging_stops_escalation(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    chain(world)
    post_events(world, [T0 + timedelta(hours=12)], severity="critical")
    run_jobs(ctx, clean_queue)
    [alert] = [a for a in alerts(app, world.a.org_id) if a.severity == "critical"]
    r = world.client.post(
        f"/api/v1/alerts/{alert.id}/acknowledge", headers=auth(world.a.owner_token)
    )
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert r.json()["acknowledged_by"] == "owner@alpha.test"
    run_due_escalation(ctx, clean_queue)
    assert [n.kind for n in log_rows(app)] == ["alert"]  # nobody else was disturbed
    assert clean_queue.delayed == []


def test_feedback_on_an_event_acknowledges_its_alert(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    chain(world)
    [event_id] = post_events(world, [T0 + timedelta(hours=13)], severity="critical")
    run_jobs(ctx, clean_queue)
    r = world.client.post(
        f"/api/v1/events/{event_id}/feedback",
        json={"is_true": False, "comment": "staff member"},
        headers=auth(world.a.owner_token),
    )
    assert r.status_code == 201
    run_due_escalation(ctx, clean_queue)
    assert [n.kind for n in log_rows(app)] == ["alert"]


def test_warnings_do_not_escalate_and_bursts_do_not_delay_escalation(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    chain(world)
    start = T0 + timedelta(hours=14)
    post_events(world, [start])  # warning
    run_jobs(ctx, clean_queue)
    assert clean_queue.delayed == []
    # A burst whose third event is critical: escalation is scheduled once, when the alert becomes
    # critical, not again for every later event (that would keep pushing it back).
    post_events(world, [start + timedelta(seconds=10)])
    post_events(world, [start + timedelta(seconds=20)], severity="critical")
    post_events(
        world, [start + timedelta(seconds=20 + 5 * i) for i in range(1, 6)], severity="critical"
    )
    run_jobs(ctx, clean_queue)
    assert [j for _, j, _ in clean_queue.delayed] == ["alert.escalate"]
    assert alerts(app, world.a.org_id)[-1].severity == "critical"


def test_escalation_job_twice_tells_people_once(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    chain(world)
    post_events(world, [T0 + timedelta(hours=15)], severity="critical")
    run_jobs(ctx, clean_queue)
    [(_, job, payload)] = clean_queue.delayed
    HANDLERS[job](ctx, payload)
    HANDLERS[job](ctx, payload)
    run_jobs(ctx, clean_queue)
    assert [n.kind for n in log_rows(app)] == ["alert", "escalation"]


def test_alerts_api(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    c, a = world.client, world.a
    recipient(world, name="Duty manager", address="+966500000001")
    post_events(world, [T0 + timedelta(hours=16) + timedelta(seconds=s) for s in (0, 10, 20)])
    run_jobs(ctx, clean_queue)
    owner = auth(a.owner_token)
    listed = c.get(f"/api/v1/alerts?site_id={a.site_ids[0]}&status=open", headers=owner).json()
    newest = listed[0]
    assert newest["event_count"] == 3 and newest["status"] == "open"
    detail = c.get(f"/api/v1/alerts/{newest['id']}", headers=owner).json()
    [delivery] = detail["deliveries"]
    assert delivery["recipient_name"] == "Duty manager" and delivery["status"] == "sent"
    assert "+966500000001" not in str(detail)  # no addresses in the alerts API

    viewer = auth(world.invite(a, "v2@alpha.test", "viewer", [a.site_ids[0]]))
    r = c.post(f"/api/v1/alerts/{newest['id']}/acknowledge", headers=viewer)
    assert r.status_code == 200 and r.json()["acknowledged_by"] == "v2@alpha.test"
    again = c.post(f"/api/v1/alerts/{newest['id']}/acknowledge", headers=owner).json()
    assert again["acknowledged_by"] == "v2@alpha.test"  # the first acknowledgement stays

    other_site = auth(world.invite(a, "v3@alpha.test", "viewer", [a.site_ids[1]]))
    assert c.get(f"/api/v1/alerts/{newest['id']}", headers=other_site).status_code == 404
    other_tenant = auth(world.b.owner_token)
    assert c.get(f"/api/v1/alerts/{newest['id']}", headers=other_tenant).status_code == 404
    assert (
        c.post(f"/api/v1/alerts/{newest['id']}/acknowledge", headers=other_tenant).status_code
        == 404
    )
