"""Event list, detail and feedback for the dashboard (CLD-07 minimal, CLD-11 storage of answers)."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from vision_cloud.api.deps import DbDep, Principal, PrincipalDep, StateDep, audit
from vision_cloud.errors import AppError, not_found
from vision_cloud.models import Alert, EventFeedback, EventRow, EventStatus, Role
from vision_cloud.schemas import EventDetail, EventOut, EventPage, FeedbackIn, FeedbackOut
from vision_cloud.services.dispatch import acknowledge
from vision_shared.schemas import EventState, Severity

router = APIRouter(prefix="/api/v1", tags=["events"])


def event_fields(row: EventRow) -> dict[str, object]:
    return {
        "id": row.id,
        "site_id": row.site_id,
        "camera_id": row.camera_id,
        "rule_id": row.rule_id,
        "rule_type": row.rule_type,
        "severity": row.severity,
        "state": row.state,
        "schema_version": row.schema_version,
        "condition_started_at": row.condition_started_at,
        "triggered_at": row.triggered_at,
        "cleared_at": row.cleared_at,
        "value": row.value,
        "message": row.message,
        "attributes": row.attributes,
        "snapshot_key": row.snapshot_key,
        "clip_key": row.clip_key,
        "needs_verification": row.needs_verification,
        "created_at": row.edge_created_at,
        "status": row.status,
        "verified": row.verified,
        "received_at": row.received_at,
        "updated_at": row.updated_at,
    }


def _encode_cursor(row: EventRow) -> str:
    raw = f"{row.triggered_at.isoformat()}|{row.id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        ts, event_id = raw.split("|", 1)
        at = datetime.fromisoformat(ts)
    except (ValueError, binascii.Error) as exc:
        raise AppError(422, "invalid cursor") from exc
    if at.tzinfo is None:
        raise AppError(422, "invalid cursor")
    return at, event_id


def _aware(name: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise AppError(422, f"`{name}` must include a timezone offset (e.g. Z or +03:00)")


@router.get("/events", response_model=EventPage)
def list_events(
    principal: PrincipalDep,
    db: DbDep,
    site_id: Annotated[str | None, Query()] = None,
    camera_id: Annotated[str | None, Query()] = None,
    rule_id: Annotated[str | None, Query()] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    state: Annotated[EventState | None, Query()] = None,
    status: Annotated[EventStatus | None, Query()] = None,
    verified: Annotated[bool | None, Query()] = None,
    from_: Annotated[
        datetime | None, Query(alias="from", description="triggered at or after")
    ] = None,
    to: Annotated[datetime | None, Query(description="triggered before")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> EventPage:
    """Newest first, keyset pagination by (triggered_at, id)."""
    _aware("from", from_)
    _aware("to", to)
    stmt = select(EventRow).where(
        EventRow.organisation_id == principal.organisation_id,
        principal.site_filter(EventRow.site_id),
    )
    if site_id:
        stmt = stmt.where(EventRow.site_id == site_id)
    if camera_id:
        stmt = stmt.where(EventRow.camera_id == camera_id)
    if rule_id:
        stmt = stmt.where(EventRow.rule_id == rule_id)
    if severity:
        stmt = stmt.where(EventRow.severity.in_([s.value for s in severity]))
    if state:
        stmt = stmt.where(EventRow.state == state.value)
    if status:
        stmt = stmt.where(EventRow.status == status.value)
    if verified is not None:
        stmt = stmt.where(EventRow.verified.is_(verified))
    if from_:
        stmt = stmt.where(EventRow.triggered_at >= from_)
    if to:
        stmt = stmt.where(EventRow.triggered_at < to)
    if cursor:
        at, last_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                EventRow.triggered_at < at,
                and_(EventRow.triggered_at == at, EventRow.id < last_id),
            )
        )
    rows = db.scalars(
        stmt.order_by(EventRow.triggered_at.desc(), EventRow.id.desc()).limit(limit + 1)
    ).all()
    page = list(rows[:limit])
    return EventPage(
        items=[EventOut.model_validate(event_fields(r)) for r in page],
        next_cursor=_encode_cursor(page[-1]) if len(rows) > limit else None,
    )


def get_event(db: Session, principal: Principal, event_id: str) -> EventRow:
    row = db.scalar(
        select(EventRow).where(
            EventRow.id == event_id,
            EventRow.organisation_id == principal.organisation_id,
            principal.site_filter(EventRow.site_id),
        )
    )
    if row is None:
        raise not_found("event")
    return row


@router.get("/events/{event_id}", response_model=EventDetail)
def read_event(
    event_id: str, principal: PrincipalDep, db: DbDep, state: StateDep, request: Request
) -> EventDetail:
    """Event with snapshot/clip view URLs (valid `VISION_CLOUD_VIEW_URL_TTL_S`, default 5 min)."""
    row = get_event(db, principal, event_id)
    feedback = db.scalars(
        select(EventFeedback)
        .where(
            EventFeedback.event_id == row.id,
            EventFeedback.organisation_id == principal.organisation_id,
        )
        .order_by(EventFeedback.created_at)
    ).all()
    detail = EventDetail.model_validate(
        {**event_fields(row), "feedback": [FeedbackOut.model_validate(f) for f in feedback]}
    )
    ttl = state.settings.view_url_ttl_s
    if row.snapshot_key:
        signed = state.storage.presign_get(row.snapshot_key, ttl)
        detail.snapshot_url, detail.media_url_expires_at = signed.url, signed.expires_at
    if row.clip_key:
        signed = state.storage.presign_get(row.clip_key, ttl)
        detail.clip_url, detail.media_url_expires_at = signed.url, signed.expires_at
        audit(
            db,
            request,
            organisation_id=principal.organisation_id,
            user_id=principal.user_id,
            action="clip.viewed",
            entity_type="event",
            entity_id=row.id,
        )
        db.commit()
    return detail


@router.post("/events/{event_id}/feedback", response_model=FeedbackOut, status_code=201)
def give_feedback(
    event_id: str, body: FeedbackIn, principal: PrincipalDep, db: DbDep
) -> EventFeedback:
    """Mark an event as correct (true) or a false alarm (false). The latest answer wins."""
    principal.require(Role.SITE_MANAGER)
    row = get_event(db, principal, event_id)
    fb = EventFeedback(
        organisation_id=principal.organisation_id,
        event_id=row.id,
        user_id=principal.user_id,
        is_true=body.is_true,
        channel="dashboard",
        comment=body.comment,
    )
    db.add(fb)
    row.verified = body.is_true
    if row.alert_id:  # answering for an event acknowledges its alert (stops escalation)
        alert = db.get(Alert, row.alert_id)
        if alert is not None:
            acknowledge(alert, principal.email)
    db.commit()
    return fb
