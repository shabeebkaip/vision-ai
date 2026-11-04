"""CLD-08 (part 2): grouping events into alerts, choosing recipients, quiet hours, daily caps,
retries and the delivery log.

Done-when from the plan: "30 events in 2 minutes from one camera produce one grouped alert".
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from vision_cloud.db import system_session
from vision_cloud.jobs import InMemoryQueue
from vision_cloud.models import Alert, EventRow, Notification, Recipient
from vision_cloud.services import channels
from vision_cloud.services.channels import ChannelError, DryRunChannel
from vision_cloud.services.dispatch import in_quiet_hours, local_day_start
from vision_cloud.services.messages import render
from vision_cloud.worker import HANDLERS, WorkerContext, _load_handlers

from .conftest import T0, World, auth, make_event

# T0 is 2026-11-01 09:00 UTC = 12:00 in Riyadh.


@pytest.fixture
def ctx(app: FastAPI, queue: InMemoryQueue) -> Iterator[WorkerContext]:
    _load_handlers()
    st = app.state.vision
    sent = DryRunChannel()
    original = channels._dry_run
    channels._dry_run = sent
    yield WorkerContext(st.settings, st.sessions, st.storage, queue, st.cipher)
    channels._dry_run = original


def sent_messages() -> list[tuple[str, str, Any]]:
    return channels._dry_run.sent  # type: ignore[attr-defined]


def run_jobs(ctx: WorkerContext, queue: InMemoryQueue) -> None:
    """Run queued jobs like the worker would, including jobs queued by jobs."""
    while queue.jobs:
        name, payload = queue.jobs.pop(0)
        HANDLERS[name](ctx, payload)


def recipient(world: World, **kw: Any) -> dict[str, Any]:
    body = {"name": "Manager", "channel": "whatsapp", "address": "+966501234567", **kw}
    r = world.client.post("/api/v1/recipients", json=body, headers=auth(world.a.owner_token))
    assert r.status_code == 201, r.text
    return dict(r.json())


def post_events(world: World, times: list[datetime], **kw: Any) -> list[str]:
    a = world.a
    ids = []
    camera = kw.pop("camera", a.camera_ids[0])
    rule_id = kw.pop("rule_id", a.rule_id)
    for at in times:
        ev = make_event(a.site_ids[0], camera, rule_id, at=at, **kw)
        r = world.client.post("/device/v1/events", json=ev, headers=auth(a.device_token))
        assert r.status_code == 201, r.text
        ids.append(ev["id"])
    return ids


def log_rows(app: FastAPI) -> list[Notification]:
    with system_session(app.state.vision.sessions) as db:
        return list(db.scalars(select(Notification).order_by(Notification.created_at)).all())


def alerts(app: FastAPI, org: str) -> list[Alert]:
    with system_session(app.state.vision.sessions) as db:
        return list(
            db.scalars(
                select(Alert).where(Alert.organisation_id == org).order_by(Alert.opened_at)
            ).all()
        )


@pytest.fixture
def clean_queue(queue: InMemoryQueue, world: World, ctx: WorkerContext) -> InMemoryQueue:
    run_jobs(ctx, queue)  # the event build_tenant posted
    sent_messages().clear()
    with system_session(ctx.sessions) as db:
        for n in db.scalars(select(Notification)).all():
            db.delete(n)
        db.commit()
    return queue


# --------------------------------------------------------------------------- done-when


def test_thirty_events_in_two_minutes_are_one_alert(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    rec = recipient(world, site_id=world.a.site_ids[0])
    start = T0 + timedelta(hours=1)
    ids = post_events(world, [start + timedelta(seconds=4 * i) for i in range(30)])  # 116 s
    run_jobs(ctx, clean_queue)

    [alert] = [x for x in alerts(app, world.a.org_id) if x.opened_at >= start]
    assert alert.event_count == 30
    assert (alert.first_event_id, alert.last_event_id) == (ids[0], ids[-1])
    rows = [n for n in log_rows(app) if n.alert_id == alert.id]
    assert [(n.recipient_id, n.status, n.reason) for n in rows] == [(rec["id"], "sent", "dry_run")]
    assert len(sent_messages()) == 1  # one message, not thirty
    with system_session(app.state.vision.sessions) as db:
        linked = db.scalars(select(EventRow.alert_id).where(EventRow.id.in_(ids))).all()
    assert set(linked) == {alert.id}


def test_a_gap_longer_than_the_window_opens_a_new_alert(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    recipient(world)
    start = T0 + timedelta(hours=2)
    # two bursts 3 minutes apart, and a slow trickle every 100 s (each within 120 s of the last)
    post_events(
        world, [start, start + timedelta(seconds=30), start + timedelta(minutes=3, seconds=31)]
    )
    trickle = start + timedelta(hours=1)
    post_events(world, [trickle + timedelta(seconds=100 * i) for i in range(5)])
    run_jobs(ctx, clean_queue)
    counts = [x.event_count for x in alerts(app, world.a.org_id) if x.opened_at >= start]
    assert counts == [2, 1, 5]
    assert len(sent_messages()) == 3


def test_other_rules_and_cameras_are_separate_alerts(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    a = world.a
    start = T0 + timedelta(hours=3)
    post_events(world, [start])
    ev = make_event(a.site_ids[0], a.camera_ids[0], "another-rule", at=start + timedelta(seconds=5))
    assert (
        world.client.post("/device/v1/events", json=ev, headers=auth(a.device_token)).status_code
        == 201
    )
    run_jobs(ctx, clean_queue)
    opened = [x for x in alerts(app, a.org_id) if x.opened_at >= start]
    assert sorted(x.rule_id for x in opened) == sorted([a.rule_id, "another-rule"])


# --------------------------------------------------------------------------- who is told


def test_recipient_selection(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    a = world.a
    everyone = recipient(world, name="org-wide")
    this_site = recipient(world, name="site 1", site_id=a.site_ids[0], rule_ids=[a.rule_id])
    first_in_chain = recipient(world, name="rank 1", escalation_rank=1)
    recipient(world, name="site 2", site_id=a.site_ids[1])
    recipient(world, name="critical only", min_severity="critical")
    recipient(world, name="disabled", enabled=False)
    recipient(world, name="rank 2, escalation only", escalation_rank=2)
    world.client.post(
        "/api/v1/recipients",
        json={"name": "other tenant", "channel": "telegram", "address": "123456"},
        headers=auth(world.b.owner_token),
    )
    post_events(world, [T0 + timedelta(hours=4)])
    run_jobs(ctx, clean_queue)
    told = {n.recipient_id for n in log_rows(app)}
    assert told == {everyone["id"], this_site["id"], first_in_chain["id"]}


def test_quiet_hours_and_critical(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    quiet = recipient(world, quiet_hours_start="11:00", quiet_hours_end="13:00")  # Riyadh time
    post_events(world, [T0 + timedelta(minutes=10)])  # 12:10 Riyadh: inside
    post_events(world, [T0 + timedelta(minutes=30)], severity="critical", rule_id="crit")
    run_jobs(ctx, clean_queue)
    rows = [(n.status, n.reason) for n in log_rows(app) if n.recipient_id == quiet["id"]]
    assert sorted(rows) == [("sent", "dry_run"), ("suppressed", "quiet_hours")]
    assert len(sent_messages()) == 1 and sent_messages()[0][2].severity == "critical"


def test_daily_cap(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    capped = recipient(world, daily_cap=2)
    day = T0 + timedelta(hours=5)
    post_events(world, [day + timedelta(minutes=10 * i) for i in range(3)])  # three alerts
    post_events(world, [day + timedelta(minutes=40)], severity="critical", rule_id="crit2")
    run_jobs(ctx, clean_queue)
    rows = [(n.status, n.reason) for n in log_rows(app) if n.recipient_id == capped["id"]]
    assert rows == [
        ("sent", "dry_run"),
        ("sent", "dry_run"),
        ("suppressed", "daily_cap"),  # the third alert of the day
        ("sent", "dry_run"),  # critical alerts ignore the cap
    ]
    # Tomorrow: what was sent yesterday no longer counts.
    with system_session(ctx.sessions) as db:
        for n in db.scalars(select(Notification)).all():
            n.created_at = n.created_at - timedelta(days=1)
        db.commit()
    post_events(world, [day + timedelta(minutes=50)])
    run_jobs(ctx, clean_queue)
    assert [(n.status, n.reason) for n in log_rows(app)][-1] == ("sent", "dry_run")


# --------------------------------------------------------------------------- sending


def test_messages_follow_the_recipient_language(
    world: World, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    recipient(world, name="en")
    recipient(world, name="ar", language="ar", channel="telegram", address="987654321")
    post_events(world, [T0 + timedelta(hours=6)])
    run_jobs(ctx, clean_queue)
    by_lang = {m.language: m for _, _, m in sent_messages()}
    assert "too many people" in by_lang["en"].text  # the edge's own message, English only
    assert "18:00" in by_lang["en"].text  # 15:00 UTC is 18:00 in Riyadh
    assert "الكاميرا" in by_lang["ar"].text and "too many people" not in by_lang["ar"].text


def test_jobs_are_idempotent(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    recipient(world)
    post_events(world, [T0 + timedelta(hours=7)])
    created = list(clean_queue.jobs)
    run_jobs(ctx, clean_queue)
    clean_queue.jobs.extend(created)  # the same event.created job delivered twice
    run_jobs(ctx, clean_queue)
    assert len(log_rows(app)) == 1 and len(sent_messages()) == 1


class FailingChannel(DryRunChannel):
    def __init__(self, failures: int, retry: bool = True) -> None:
        super().__init__()
        self.failures, self.retry = failures, retry

    def send(self, recipient: Recipient, message: Any) -> str:
        if self.failures > 0:
            self.failures -= 1
            raise ChannelError("provider timeout", retry=self.retry)
        return super().send(recipient, message)


@pytest.mark.parametrize(
    ("failures", "retry", "status", "attempts"),
    [(2, True, "sent", 3), (10, True, "failed", 4), (10, False, "failed", 1)],
)
def test_send_retries_then_fails_into_the_log(
    world: World,
    app: FastAPI,
    ctx: WorkerContext,
    clean_queue: InMemoryQueue,
    failures: int,
    retry: bool,
    status: str,
    attempts: int,
) -> None:
    recipient(world)
    post_events(world, [T0 + timedelta(hours=8)])
    HANDLERS["event.created"](ctx, clean_queue.jobs.pop(0)[1])
    [(job, payload)] = clean_queue.jobs
    channels._dry_run = FailingChannel(failures, retry)
    for _ in range(10):  # the job queue's retries
        try:
            HANDLERS[job](ctx, payload)
            break
        except ChannelError:
            continue
    [row] = log_rows(app)
    assert (row.status, row.attempts) == (status, attempts)
    assert (row.last_error == "provider timeout") == (failures > 0)


# --------------------------------------------------------------------------- helpers


def test_quiet_hours_over_midnight() -> None:
    def at(hh: int, mm: int = 0) -> datetime:  # Riyadh local time on 1 Nov 2026
        return datetime(2026, 11, 1, hh, mm, tzinfo=timezone(timedelta(hours=3)))

    assert in_quiet_hours("23:00", "07:00", at(23, 30), "Asia/Riyadh")
    assert in_quiet_hours("23:00", "07:00", at(6, 59), "Asia/Riyadh")
    assert not in_quiet_hours("23:00", "07:00", at(7), "Asia/Riyadh")
    assert not in_quiet_hours("23:00", "07:00", at(12), "Asia/Riyadh")
    assert in_quiet_hours("13:00", "14:00", at(13, 30), "Asia/Riyadh")
    assert not in_quiet_hours(None, None, at(3), "Asia/Riyadh")


def test_local_day_start_uses_the_site_timezone() -> None:
    late = datetime(2026, 11, 1, 22, 30, tzinfo=timezone.utc)  # 01:30 on 2 Nov in Riyadh
    assert local_day_start(late, "Asia/Riyadh") == datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc)


def test_render_counts_and_escalation() -> None:
    msg = render(
        language="en",
        rule_type="queue_length_over",
        rule_name="",
        severity="critical",
        camera="Counter",
        site="Olaya",
        timezone="Asia/Riyadh",
        triggered_at=T0,
        edge_message="Queue of 7",
        event_count=12,
        escalated=True,
    )
    assert msg.title == "🚨 Critical: Queue too long"
    assert "Escalated" in msg.body and "Events in this alert: 12" in msg.body


@pytest.mark.postgres
def test_concurrent_workers_open_one_alert(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue, backend: str
) -> None:
    """Eight workers handle eight events of one burst at the same moment: still one alert."""
    if backend != "postgres":
        pytest.skip("SQLite allows one writer at a time; the advisory lock is PostgreSQL's")
    recipient(world)
    start = T0 + timedelta(hours=9)
    post_events(world, [start + timedelta(seconds=i) for i in range(8)])
    jobs = [payload for _, payload in clean_queue.jobs]
    clean_queue.jobs.clear()
    barrier = threading.Barrier(len(jobs))
    errors: list[BaseException] = []

    def work(payload: dict[str, Any]) -> None:
        barrier.wait()
        try:
            HANDLERS["event.created"](ctx, payload)
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(p,)) for p in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    [alert] = [x for x in alerts(app, world.a.org_id) if x.opened_at >= start]
    assert alert.event_count == 8
    assert len([j for j, _ in clean_queue.jobs if j == "notification.send"]) == 1


def test_late_earlier_event_joins_the_alert(
    world: World, app: FastAPI, ctx: WorkerContext, clean_queue: InMemoryQueue
) -> None:
    """A box uploading its backlog out of order still produces one alert."""
    recipient(world)
    start = T0 + timedelta(hours=10)
    ids = post_events(world, [start + timedelta(seconds=s) for s in (60, 90, 0, 30)])
    run_jobs(ctx, clean_queue)
    [alert] = [x for x in alerts(app, world.a.org_id) if x.opened_at >= start]
    assert alert.event_count == 4
    assert (alert.opened_at, alert.first_event_id) == (start, ids[2])
    assert alert.last_event_id == ids[1]
    assert len(sent_messages()) == 1
