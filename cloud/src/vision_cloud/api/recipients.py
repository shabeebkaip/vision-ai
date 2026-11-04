"""Alert recipients (CLD-08): who is told about which rules, on which channel, and when not to.

Recipients hold personal data (phone numbers, chat ids), so managing them needs the site manager
role, recipients for every site need manager, and the audit log never records an address.
`GET /sites/{id}/recipients` is the address-free list the dashboard's rule builder reads.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from vision_cloud.api.deps import DbDep, Principal, PrincipalDep
from vision_cloud.api.manage import _audit, get_site
from vision_cloud.errors import AppError, not_found
from vision_cloud.models import Recipient, RecipientRule, Role, RuleRow
from vision_cloud.schemas import (
    RecipientIn,
    RecipientOut,
    RecipientSummary,
    RecipientUpdate,
    check_address,
    check_quiet_hours,
)

router = APIRouter(prefix="/api/v1", tags=["recipients"])


def recipient_out(r: Recipient) -> RecipientOut:
    return RecipientOut.model_validate(
        {
            **{c: getattr(r, c) for c in RecipientOut.model_fields if c != "rule_ids"},
            "rule_ids": sorted(rr.rule_id for rr in r.rules),
        }
    )


def _visible(principal: Principal) -> ColumnElement[bool]:
    """Recipients of the caller's sites plus the organisation-wide ones."""
    return or_(Recipient.site_id.is_(None), principal.site_filter(Recipient.site_id))


def get_recipient(db: Session, principal: Principal, recipient_id: str) -> Recipient:
    r = db.scalar(
        select(Recipient).where(
            Recipient.id == recipient_id,
            Recipient.organisation_id == principal.organisation_id,
            _visible(principal),
        )
    )
    if r is None:
        raise not_found("recipient")
    return r


def _may_edit(principal: Principal, r: Recipient | None, site_id: str | None) -> None:
    principal.require(Role.SITE_MANAGER)
    if site_id is None or (r is not None and r.site_id is None):
        principal.require(Role.MANAGER)  # organisation-wide recipients


def _set_rules(
    db: Session, principal: Principal, r: Recipient, site_id: str | None, rule_ids: list[str]
) -> None:
    ids = sorted(set(rule_ids))
    if ids:
        stmt = select(RuleRow.id, RuleRow.site_id).where(
            RuleRow.id.in_(ids),
            RuleRow.organisation_id == principal.organisation_id,
            principal.site_filter(RuleRow.site_id),
        )
        found = dict(db.execute(stmt).tuples().all())
        missing = [i for i in ids if i not in found]
        if missing:
            raise AppError(422, f"unknown rule(s): {', '.join(missing[:5])}")
        if site_id is not None and any(s != site_id for s in found.values()):
            raise AppError(422, "a site's recipient can only follow rules of that site")
    r.rules = [
        RecipientRule(organisation_id=principal.organisation_id, recipient_id=r.id, rule_id=i)
        for i in ids
    ]


@router.get("/recipients", response_model=list[RecipientOut])
def list_recipients(
    principal: PrincipalDep,
    db: DbDep,
    site_id: Annotated[str | None, Query(description="this site's plus organisation-wide")] = None,
) -> list[RecipientOut]:
    principal.require(Role.SITE_MANAGER)
    stmt = select(Recipient).where(
        Recipient.organisation_id == principal.organisation_id,
        _visible(principal),
    )
    if site_id:
        get_site(db, principal, site_id)
        stmt = stmt.where(or_(Recipient.site_id.is_(None), Recipient.site_id == site_id))
    rows = db.scalars(stmt.order_by(Recipient.name, Recipient.id)).all()
    return [recipient_out(r) for r in rows]


@router.get("/sites/{site_id}/recipients", response_model=list[RecipientSummary])
def site_recipients(site_id: str, principal: PrincipalDep, db: DbDep) -> list[Recipient]:
    get_site(db, principal, site_id)
    stmt = select(Recipient).where(
        Recipient.organisation_id == principal.organisation_id,
        or_(Recipient.site_id.is_(None), Recipient.site_id == site_id),
        Recipient.enabled.is_(True),
    )
    return list(db.scalars(stmt.order_by(Recipient.name, Recipient.id)).all())


@router.post("/recipients", response_model=RecipientOut, status_code=201)
def create_recipient(
    body: RecipientIn, principal: PrincipalDep, db: DbDep, request: Request
) -> RecipientOut:
    _may_edit(principal, None, body.site_id)
    if body.site_id is not None:
        get_site(db, principal, body.site_id)
    r = Recipient(
        organisation_id=principal.organisation_id,
        **body.model_dump(exclude={"rule_ids", "min_severity"}),
        min_severity=body.min_severity.value,
    )
    db.add(r)
    db.flush()
    _set_rules(db, principal, r, body.site_id, body.rule_ids)
    _audit(
        db,
        request,
        principal,
        "recipient.created",
        "recipient",
        r.id,
        {"channel": r.channel, "site_id": r.site_id},
    )
    db.commit()
    db.refresh(r)
    return recipient_out(r)


@router.get("/recipients/{recipient_id}", response_model=RecipientOut)
def read_recipient(recipient_id: str, principal: PrincipalDep, db: DbDep) -> RecipientOut:
    principal.require(Role.SITE_MANAGER)
    return recipient_out(get_recipient(db, principal, recipient_id))


@router.patch("/recipients/{recipient_id}", response_model=RecipientOut)
def update_recipient(
    recipient_id: str,
    body: RecipientUpdate,
    principal: PrincipalDep,
    db: DbDep,
    request: Request,
) -> RecipientOut:
    r = get_recipient(db, principal, recipient_id)
    _may_edit(principal, r, r.site_id)
    changes = body.model_dump(exclude_unset=True)
    rule_ids = changes.pop("rule_ids", None)
    if "min_severity" in changes and changes["min_severity"] is not None:
        changes["min_severity"] = changes["min_severity"].value
    for field in ("name", "channel", "address", "language", "min_severity", "daily_cap", "enabled"):
        if field in changes and changes[field] is None:
            raise AppError(422, f"{field} cannot be null")
    merged = {c: changes.get(c, getattr(r, c)) for c in ("channel", "address")}
    q_start = changes.get("quiet_hours_start", r.quiet_hours_start)
    q_end = changes.get("quiet_hours_end", r.quiet_hours_end)
    try:
        check_address(merged["channel"], merged["address"])
        check_quiet_hours(q_start, q_end)
    except (ValueError, ValidationError) as exc:
        raise AppError(422, str(exc)) from exc
    for field, value in changes.items():
        setattr(r, field, value)
    if rule_ids is not None:
        _set_rules(db, principal, r, r.site_id, rule_ids)
    fields = sorted([*changes, *(["rule_ids"] if rule_ids is not None else [])])
    _audit(db, request, principal, "recipient.updated", "recipient", r.id, {"fields": fields})
    db.commit()
    db.refresh(r)
    return recipient_out(r)


@router.delete("/recipients/{recipient_id}", status_code=204)
def delete_recipient(
    recipient_id: str, principal: PrincipalDep, db: DbDep, request: Request
) -> None:
    r = get_recipient(db, principal, recipient_id)
    _may_edit(principal, r, r.site_id)
    db.delete(r)
    _audit(db, request, principal, "recipient.deleted", "recipient", recipient_id)
    db.commit()
