"""Dashboard read models (CLD-07): site summaries, the site overview, and rules with recipients.

Shapes follow the dashboard's API contract (web/README.md). Times are computed in each site's
timezone: "today" is the site's local day.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vision_cloud.api.deps import DbDep, Principal, PrincipalDep, StateDep
from vision_cloud.api.manage import (
    _apply_rule,
    _audit,
    _validate_site,
    get_camera,
    get_site,
    rule_out,
)
from vision_cloud.db import new_id, utcnow
from vision_cloud.errors import AppError
from vision_cloud.models import (
    AggregateMinute,
    Alert,
    Camera,
    EventRow,
    Recipient,
    RecipientRule,
    Role,
    RuleRow,
    Site,
)
from vision_cloud.schemas import RuleIn, RuleOut, SiteOut
from vision_shared.schemas import Rule

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

ONLINE = "online"


def local_day(day: date, timezone: str) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day, as UTC datetimes."""
    tz = ZoneInfo(timezone)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(ZoneInfo("UTC")), (start + timedelta(days=1)).astimezone(ZoneInfo("UTC"))


def today_in(timezone: str) -> date:
    return utcnow().astimezone(ZoneInfo(timezone)).date()


# --------------------------------------------------------------------------- site summaries


class SiteSummaryOut(SiteOut):
    cameras_total: int
    cameras_online: int
    alerts_today: int


def _camera_counts(db: Session, site_ids: list[str]) -> dict[str, tuple[int, int]]:
    rows = db.execute(
        select(Camera.site_id, Camera.status, func.count(Camera.id))
        .where(Camera.site_id.in_(site_ids), Camera.enabled.is_(True))
        .group_by(Camera.site_id, Camera.status)
    ).all()
    counts: dict[str, tuple[int, int]] = {}
    for site_id, status, n in rows:
        total, online = counts.get(site_id, (0, 0))
        counts[site_id] = (total + n, online + (n if status == ONLINE else 0))
    return counts


def _alerts_between(db: Session, site_id: str, start: datetime, end: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(Alert.id)).where(
                Alert.site_id == site_id, Alert.opened_at >= start, Alert.opened_at < end
            )
        )
        or 0
    )


@router.get("/sites", response_model=list[SiteSummaryOut], tags=["sites"])
def list_sites(principal: PrincipalDep, db: DbDep) -> list[SiteSummaryOut]:
    """Every site the caller may see, with camera counts and today's alerts (site time)."""
    sites = db.scalars(
        select(Site)
        .where(Site.organisation_id == principal.organisation_id, principal.site_filter(Site.id))
        .order_by(Site.name, Site.id)
    ).all()
    counts = _camera_counts(db, [s.id for s in sites])
    out = []
    for s in sites:
        total, online = counts.get(s.id, (0, 0))
        start, end = local_day(today_in(s.timezone), s.timezone)
        out.append(
            SiteSummaryOut(
                **SiteOut.model_validate(s).model_dump(),
                cameras_total=total,
                cameras_online=online,
                alerts_today=_alerts_between(db, s.id, start, end),
            )
        )
    return out


# --------------------------------------------------------------------------- site overview


class HourlyFootfall(BaseModel):
    hour: int = Field(ge=0, le=23, description="local hour of day")
    in_: int = Field(alias="in", serialization_alias="in")
    out: int

    model_config = {"populate_by_name": True}


class SiteOverview(BaseModel):
    site_id: str
    date: date
    alerts_total: int
    alerts_by_type: dict[str, int]
    false_alert_rate_7d: float | None = Field(
        description="share of reviewed events marked false alarm in the 7 days to `date`"
    )
    reviewed_7d: int
    footfall_by_hour: list[HourlyFootfall]
    cameras_online: int
    cameras_total: int


@router.get(
    "/sites/{site_id}/overview",
    response_model=SiteOverview,
    response_model_by_alias=True,
    tags=["sites"],
)
def site_overview(
    site_id: str,
    principal: PrincipalDep,
    db: DbDep,
    day: Annotated[date | None, Query(alias="date", description="local date; default today")] = None,
) -> SiteOverview:
    site = get_site(db, principal, site_id)
    tz = site.timezone
    day = day or today_in(tz)
    start, end = local_day(day, tz)

    by_type = Counter(
        dict(
            db.execute(
                select(Alert.rule_type, func.count(Alert.id))
                .where(Alert.site_id == site.id, Alert.opened_at >= start, Alert.opened_at < end)
                .group_by(Alert.rule_type)
            )
            .tuples()
            .all()
        )
    )

    week_start = start - timedelta(days=6)
    reviewed = dict(
        db.execute(
            select(EventRow.verified, func.count(EventRow.id))
            .where(
                EventRow.site_id == site.id,
                EventRow.triggered_at >= week_start,
                EventRow.triggered_at < end,
                EventRow.verified.is_not(None),
            )
            .group_by(EventRow.verified)
        )
        .tuples()
        .all()
    )
    n_reviewed = int(sum(reviewed.values()))
    false_rate = round(reviewed.get(False, 0) / n_reviewed, 4) if n_reviewed else None

    hours: dict[int, list[int]] = {h: [0, 0] for h in range(24)}
    rows = db.execute(
        select(AggregateMinute.minute, AggregateMinute.metric, AggregateMinute.value).where(
            AggregateMinute.site_id == site.id,
            AggregateMinute.minute >= start,
            AggregateMinute.minute < end,
            AggregateMinute.metric.in_(("count_in", "count_out")),
        )
    ).all()
    zone = ZoneInfo(tz)
    for minute, metric, value in rows:
        hour = minute.astimezone(zone).hour
        hours[hour][0 if metric == "count_in" else 1] += round(value)

    total, online = _camera_counts(db, [site.id]).get(site.id, (0, 0))
    return SiteOverview(
        site_id=site.id,
        date=day,
        alerts_total=sum(by_type.values()),
        alerts_by_type=dict(by_type),
        false_alert_rate_7d=false_rate,
        reviewed_7d=n_reviewed,
        footfall_by_hour=[HourlyFootfall(hour=h, **{"in": v[0]}, out=v[1]) for h, v in hours.items()],
        cameras_online=online,
        cameras_total=total,
    )


# --------------------------------------------------------------------------- rules with recipients


class RuleWithRecipients(BaseModel):
    rule: RuleOut
    recipient_ids: list[str]


class RuleWithRecipientsIn(BaseModel):
    rule: RuleIn
    recipient_ids: list[str] = Field(default_factory=list, max_length=100)


SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def alerted_by(db: Session, site_id: str, rules: list[RuleRow]) -> dict[str, list[str]]:
    """Who each rule alerts: enabled recipients of the site (or every site) at or below the rule's
    severity, limited to the rule or not limited at all. Same selection as the dispatcher, without
    the escalation ranks (ranks 2+ are alerted too, later)."""
    people = db.scalars(
        select(Recipient).where(
            Recipient.enabled.is_(True),
            (Recipient.site_id.is_(None)) | (Recipient.site_id == site_id),
        )
    ).all()
    out: dict[str, list[str]] = {}
    for rule in rules:
        sev = SEVERITY_RANK.get(rule.severity, 1)
        out[rule.id] = sorted(
            p.id
            for p in people
            if SEVERITY_RANK.get(p.min_severity, 1) <= sev
            and (not p.rules or any(rr.rule_id == rule.id for rr in p.rules))
        )
    return out


@router.get("/sites/{site_id}/rules", response_model=list[RuleWithRecipients], tags=["rules"])
def site_rules(site_id: str, principal: PrincipalDep, db: DbDep) -> list[RuleWithRecipients]:
    """The site's rules, each with the recipients it alerts."""
    site = get_site(db, principal, site_id)
    rows = db.scalars(
        select(RuleRow).where(RuleRow.site_id == site.id).order_by(RuleRow.created_at, RuleRow.id)
    ).all()
    who = alerted_by(db, site.id, list(rows))
    return [RuleWithRecipients(rule=rule_out(r), recipient_ids=who[r.id]) for r in rows]


def _check_recipients(
    db: Session, principal: Principal, site_id: str, recipient_ids: list[str]
) -> list[Recipient]:
    ids = sorted(set(recipient_ids))
    if not ids:
        return []
    found = db.scalars(
        select(Recipient).where(
            Recipient.id.in_(ids), Recipient.organisation_id == principal.organisation_id
        )
    ).all()
    usable = [r for r in found if r.site_id in (None, site_id)]
    missing = sorted(set(ids) - {r.id for r in usable})
    if missing:
        raise AppError(422, f"unknown recipient(s) for this site: {', '.join(missing[:5])}")
    return list(usable)


@router.post(
    "/sites/{site_id}/rules", response_model=RuleWithRecipients, status_code=201, tags=["rules"]
)
def create_site_rule(
    site_id: str,
    body: RuleWithRecipientsIn,
    principal: PrincipalDep,
    db: DbDep,
    state: StateDep,
    request: Request,
) -> RuleWithRecipients:
    """Create a rule and make sure the chosen recipients get it, in one transaction. A recipient
    limited to some rules gets this one added; one without limits already gets every rule and is
    left as is (adding a limit would silently take their other rules away)."""
    principal.require(Role.SITE_MANAGER)
    site = get_site(db, principal, site_id)
    cam = get_camera(db, principal, body.rule.camera_id)
    if cam.site_id != site.id:
        raise AppError(422, "the rule's camera belongs to another site")
    recipients = _check_recipients(db, principal, site.id, body.recipient_ids)
    rule_id = new_id()
    rule = Rule.model_validate({**body.rule.model_dump(exclude={"id"}), "id": rule_id})
    row = RuleRow(id=rule_id, organisation_id=principal.organisation_id, site_id=site.id)
    _apply_rule(row, rule)
    db.add(row)
    db.flush()
    _validate_site(db, state, site.id, principal)
    for r in recipients:
        if r.rules:  # limited to some rules: add this one
            db.add(
                RecipientRule(
                    organisation_id=principal.organisation_id, recipient_id=r.id, rule_id=rule_id
                )
            )
    _audit(db, request, principal, "rule.created", "rule", row.id,
           {"type": row.type, "recipients": len(recipients)})
    db.commit()
    db.expire_all()
    return RuleWithRecipients(rule=rule_out(row), recipient_ids=alerted_by(db, site.id, [row])[row.id])
