"""Alerts for the dashboard (CLD-08): what people were told, the delivery log, and "I'm on it".

Acknowledging an alert stops its escalation. Giving feedback on one of its events
(`POST /events/{id}/feedback`) acknowledges it too, and the Telegram and WhatsApp buttons
(CLD-09/10) use the same `services.dispatch.acknowledge`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from vision_cloud.api.deps import DbDep, Principal, PrincipalDep
from vision_cloud.api.manage import _audit
from vision_cloud.errors import not_found
from vision_cloud.models import Alert, AlertStatus, Notification, Recipient
from vision_cloud.schemas import AlertDetail, AlertOut, DeliveryOut
from vision_cloud.services.dispatch import acknowledge

router = APIRouter(prefix="/api/v1", tags=["alerts"])


def get_alert(db: Session, principal: Principal, alert_id: str) -> Alert:
    alert = db.scalar(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.organisation_id == principal.organisation_id,
            principal.site_filter(Alert.site_id),
        )
    )
    if alert is None:
        raise not_found("alert")
    return alert


def _detail(db: Session, alert: Alert) -> AlertDetail:
    rows = db.execute(
        select(Notification, Recipient.name)
        .outerjoin(Recipient, Recipient.id == Notification.recipient_id)
        .where(Notification.alert_id == alert.id)
        .order_by(Notification.created_at, Notification.id)
    ).all()
    deliveries = [
        DeliveryOut(
            id=n.id,
            recipient_id=n.recipient_id,
            recipient_name=name or "",
            channel=n.channel,
            kind=n.kind,
            status=n.status,
            reason=n.reason,
            attempts=n.attempts,
            last_error=n.last_error,
            sent_at=n.sent_at,
            created_at=n.created_at,
        )
        for n, name in rows
    ]
    return AlertDetail(**AlertOut.model_validate(alert).model_dump(), deliveries=deliveries)


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    principal: PrincipalDep,
    db: DbDep,
    site_id: Annotated[str | None, Query()] = None,
    status: Annotated[AlertStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Alert]:
    stmt = select(Alert).where(
        Alert.organisation_id == principal.organisation_id, principal.site_filter(Alert.site_id)
    )
    if site_id:
        stmt = stmt.where(Alert.site_id == site_id)
    if status:
        stmt = stmt.where(Alert.status == status.value)
    stmt = stmt.order_by(Alert.last_event_at.desc(), Alert.id).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/alerts/{alert_id}", response_model=AlertDetail)
def read_alert(alert_id: str, principal: PrincipalDep, db: DbDep) -> AlertDetail:
    return _detail(db, get_alert(db, principal, alert_id))


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertDetail)
def acknowledge_alert(
    alert_id: str, principal: PrincipalDep, db: DbDep, request: Request
) -> AlertDetail:
    """ "I'm on it": anyone who can see the alert's site may acknowledge it. Repeating it keeps
    the first acknowledgement."""
    alert = get_alert(db, principal, alert_id)
    if acknowledge(alert, principal.email):
        _audit(db, request, principal, "alert.acknowledged", "alert", alert.id)
        db.commit()
    return _detail(db, alert)
