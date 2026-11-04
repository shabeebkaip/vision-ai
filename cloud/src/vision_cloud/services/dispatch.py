"""Alert dispatcher (CLD-08): from stored events to messages people receive.

`event.created` (queued by ingest for every new event):
1. Grouping. An open alert of the same camera and rule within `alert_group_window_s` (120 s) of
   this event, on either side of its span (events can arrive out of order), absorbs it: its count
   goes up and nobody is messaged again. Otherwise a new alert opens. A burst of 30 events in
   2 minutes is one alert.
2. Recipients of a new alert: enabled, for this site or every site, at or above their minimum
   severity, following this rule (or every rule), and not waiting for escalation (no rank or
   rank 1; ranks 2+ are the escalation chain, CLD-08c).
3. Each recipient gets a row in the delivery log (`notifications`). Quiet hours (at the event's
   time, site timezone) and the daily cap (messages queued or sent since local midnight today)
   mark it `suppressed` with the reason; critical alerts are never suppressed.
   The others are `queued` and a `notification.send` job is queued for each.

`notification.send` renders the message in the recipient's language and sends it through the
channel. Failures are retried by the job queue; after the last retry the row is `failed` with the
error. Both handlers are idempotent: running a job twice changes nothing the second time.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from vision_cloud.db import tenant_session, utcnow
from vision_cloud.models import (
    Alert,
    AlertStatus,
    Camera,
    EventRow,
    Notification,
    NotificationStatus,
    Recipient,
    RecipientRule,
    RuleRow,
    Site,
)
from vision_cloud.services.channels import ChannelError, channel_for
from vision_cloud.services.messages import render
from vision_cloud.worker import WorkerContext, handler

log = structlog.get_logger(__name__)

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
COUNTED = (
    NotificationStatus.QUEUED.value,
    NotificationStatus.SENT.value,
    NotificationStatus.DELIVERED.value,
)


# --------------------------------------------------------------------------- rules of thumb


def in_quiet_hours(start: str | None, end: str | None, at: datetime, timezone: str) -> bool:
    """True when `at` falls in [start, end) in the site's time; handles windows over midnight."""
    if not start or not end:
        return False
    now = at.astimezone(ZoneInfo(timezone)).time()
    s, e = time.fromisoformat(start), time.fromisoformat(end)
    return s <= now < e if s < e else now >= s or now < e


def local_day_start(at: datetime, timezone: str) -> datetime:
    local = at.astimezone(ZoneInfo(timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))


# --------------------------------------------------------------------------- event.created


def _lock_group(db: Session, camera_id: str, rule_id: str) -> None:
    """Serialise workers grouping events of the same camera and rule (PostgreSQL only; SQLite
    allows one writer anyway)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{camera_id}:{rule_id}"}
        )


def _group(db: Session, event: EventRow, window_s: float) -> tuple[Alert, bool]:
    _lock_group(db, event.camera_id, event.rule_id)
    alert = db.scalar(
        select(Alert)
        .where(
            Alert.camera_id == event.camera_id,
            Alert.rule_id == event.rule_id,
            Alert.status != AlertStatus.CLOSED.value,
            # within the window on either side of the alert's span: events can arrive out of
            # order (concurrent workers, a box uploading its backlog after an outage)
            Alert.last_event_at >= event.triggered_at - timedelta(seconds=window_s),
            Alert.opened_at <= event.triggered_at + timedelta(seconds=window_s),
        )
        .order_by(Alert.last_event_at.desc())
        .limit(1)
    )
    if alert is not None:
        alert.event_count += 1
        if event.triggered_at >= alert.last_event_at:
            alert.last_event_at = event.triggered_at
            alert.last_event_id = event.id
            alert.message = event.message
        if event.triggered_at < alert.opened_at:
            alert.opened_at = event.triggered_at
            alert.first_event_id = event.id
        if SEVERITY_RANK.get(event.severity, 1) > SEVERITY_RANK.get(alert.severity, 1):
            alert.severity = event.severity
        return alert, False
    alert = Alert(
        organisation_id=event.organisation_id,
        site_id=event.site_id,
        camera_id=event.camera_id,
        rule_id=event.rule_id,
        rule_type=event.rule_type,
        severity=event.severity,
        first_event_id=event.id,
        last_event_id=event.id,
        event_count=1,
        message=event.message,
        opened_at=event.triggered_at,
        last_event_at=event.triggered_at,
    )
    db.add(alert)
    db.flush()
    return alert, True


def recipients_for(db: Session, alert: Alert) -> list[Recipient]:
    follows_rule = or_(
        ~Recipient.rules.any(),
        Recipient.rules.any(RecipientRule.rule_id == alert.rule_id),
    )
    rows = db.scalars(
        select(Recipient)
        .where(
            Recipient.organisation_id == alert.organisation_id,
            Recipient.enabled.is_(True),
            or_(Recipient.site_id.is_(None), Recipient.site_id == alert.site_id),
            or_(Recipient.escalation_rank.is_(None), Recipient.escalation_rank <= 1),
            follows_rule,
        )
        .order_by(Recipient.created_at, Recipient.id)
    ).all()
    sev = SEVERITY_RANK.get(alert.severity, 1)
    return [r for r in rows if SEVERITY_RANK.get(r.min_severity, 1) <= sev]


def _sent_today(db: Session, recipient: Recipient, since: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_id == recipient.id,
                Notification.status.in_(COUNTED),
                Notification.created_at >= since,
            )
        )
        or 0
    )


def plan_notifications(
    db: Session, alert: Alert, event: EventRow, timezone: str, kind: str = "alert"
) -> list[Notification]:
    critical = alert.severity == "critical"
    # The cap is about messages a person receives per day, so it counts by sending time (now),
    # not event time: hours-old events uploaded after an outage count towards today.
    day_start = local_day_start(utcnow(), timezone)
    rows = []
    for r in recipients_for(db, alert):
        status, reason = NotificationStatus.QUEUED, None
        if not critical and in_quiet_hours(
            r.quiet_hours_start, r.quiet_hours_end, event.triggered_at, timezone
        ):
            status, reason = NotificationStatus.SUPPRESSED, "quiet_hours"
        elif not critical and _sent_today(db, r, day_start) >= r.daily_cap:
            status, reason = NotificationStatus.SUPPRESSED, "daily_cap"
        n = Notification(
            organisation_id=alert.organisation_id,
            event_id=event.id,
            alert_id=alert.id,
            recipient_id=r.id,
            kind=kind,
            channel=r.channel,
            status=status.value,
            reason=reason,
        )
        db.add(n)
        rows.append(n)
    db.flush()
    return rows


@handler("event.created")
def on_event_created(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    to_send: list[str] = []
    with tenant_session(ctx.sessions, payload["organisation_id"]) as db:
        event = db.scalar(select(EventRow).where(EventRow.id == payload["event_id"]))
        if event is None:
            log.warning("dispatch.event_missing")
            return
        if event.alert_id is not None:
            return  # already dispatched (job ran twice)
        alert, opened = _group(db, event, ctx.settings.alert_group_window_s)
        event.alert_id = alert.id
        if opened:
            site = db.get(Site, event.site_id)
            tz = site.timezone if site else "Asia/Riyadh"
            planned = plan_notifications(db, alert, event, tz)
            to_send = [n.id for n in planned if n.status == NotificationStatus.QUEUED.value]
            log.info(
                "dispatch.alert_opened",
                alert_id=alert.id,
                recipients=len(planned),
                queued=len(to_send),
                suppressed=len(planned) - len(to_send),
            )
        else:
            log.info("dispatch.grouped", alert_id=alert.id, event_count=alert.event_count)
        db.commit()
    for notification_id in to_send:  # after the commit, so the job sees the row
        ctx.queue.enqueue(
            "notification.send",
            {"organisation_id": payload["organisation_id"], "notification_id": notification_id},
        )


@handler("event.cleared")
@handler("event.media_ready")
def on_event_update(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    """No message for these yet: Telegram (CLD-10) edits the sent alert to add the snapshot."""
    log.info("dispatch.update_ignored")


# --------------------------------------------------------------------------- notification.send


@handler("notification.send")
def on_notification_send(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    with tenant_session(ctx.sessions, payload["organisation_id"]) as db:
        n = db.scalar(select(Notification).where(Notification.id == payload["notification_id"]))
        if n is None or n.status != NotificationStatus.QUEUED.value:
            return  # deleted, or already sent by an earlier run of this job
        recipient = db.get(Recipient, n.recipient_id) if n.recipient_id else None
        alert = db.get(Alert, n.alert_id) if n.alert_id else None
        event = db.get(EventRow, n.event_id)
        if recipient is None or alert is None or event is None or not recipient.enabled:
            n.status, n.reason = NotificationStatus.SUPPRESSED.value, "recipient_removed"
            db.commit()
            return
        site = db.get(Site, alert.site_id)
        camera = db.get(Camera, alert.camera_id)
        rule = db.get(RuleRow, alert.rule_id)
        snapshot_url = None
        if event.snapshot_key:
            snapshot_url = ctx.storage.presign_get(event.snapshot_key, 24 * 3600).url
        message = render(
            language=recipient.language,
            rule_type=alert.rule_type,
            rule_name=rule.name if rule else "",
            severity=alert.severity,
            camera=(camera.name if camera else "") or alert.camera_id,
            site=site.name if site else "",
            timezone=site.timezone if site else "Asia/Riyadh",
            triggered_at=alert.opened_at,
            edge_message=event.message,
            event_count=alert.event_count,
            escalated=n.kind == "escalation",
            snapshot_url=snapshot_url,
        )
        n.attempts += 1
        try:
            channel = channel_for(recipient.channel, dry_run=ctx.settings.alert_dry_run)
            n.provider_message_id = channel.send(recipient, message)
        except ChannelError as exc:
            n.last_error = str(exc)[:2000]
            last_try = not exc.retry or n.attempts > ctx.settings.job_max_retries
            if last_try:
                n.status = NotificationStatus.FAILED.value
                db.commit()
                log.error("dispatch.send_failed", notification_id=n.id, error=str(exc))
                return
            db.commit()
            raise  # the job queue retries with backoff
        n.status = NotificationStatus.SENT.value
        n.sent_at = utcnow()
        if ctx.settings.alert_dry_run:
            n.reason = "dry_run"
        db.commit()
