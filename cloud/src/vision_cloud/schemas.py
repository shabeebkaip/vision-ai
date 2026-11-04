"""Dashboard-facing API payloads (CLD-03, CLD-07).

Where a shared contract exists it is reused: zones and lines are `vision_shared.schemas.Zone/Line`,
rules extend `Rule`, events extend `Event`. Device payloads live in `vision_shared.api`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from vision_cloud.models import Role
from vision_shared.schemas import Event, Line, Rule, Severity, Zone


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _check_tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unknown timezone {v!r}") from exc
    return v


def _email(v: str) -> str:
    v = v.strip().lower()
    local, _, domain = v.partition("@")
    if not local or "." not in domain or " " in v or len(v) > 320:
        raise ValueError("invalid email address")
    return v


Email = Annotated[str, AfterValidator(_email)]
TimezoneName = Annotated[str, AfterValidator(_check_tz)]


# --------------------------------------------------------------------------- auth


class LoginRequest(_In):
    email: Email
    password: str = Field(min_length=1, max_length=1024)
    organisation_id: str | None = None


class RefreshRequest(_In):
    refresh_token: str = Field(min_length=8, max_length=256)
    organisation_id: str | None = Field(
        default=None, description="switch the active organisation while refreshing"
    )


class LogoutRequest(_In):
    refresh_token: str = Field(min_length=8, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_token: str
    organisation_id: str
    role: Role


class OrganisationSummary(BaseModel):
    id: str
    name: str
    role: Role


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    is_platform_admin: bool
    organisation_id: str
    role: Role
    site_ids: list[str] | None = Field(description="null = every site of the organisation")
    organisations: list[OrganisationSummary]


class InvitationCreate(_In):
    email: Email
    role: Role
    site_ids: list[str] = Field(default_factory=list, max_length=500)


class InvitationCreated(BaseModel):
    id: str
    email: str
    role: Role
    site_ids: list[str]
    expires_at: datetime
    token: str = Field(description="one-time token; shown once. Email delivery is a follow-up.")


class AcceptInvitation(_In):
    token: str = Field(min_length=16, max_length=256)
    password: str = Field(min_length=1, max_length=1024)
    full_name: str = Field(default="", max_length=200)


class MemberOut(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: Role
    site_ids: list[str] | None


# --------------------------------------------------------------------------- organisations


class OrganisationCreate(_In):
    name: str = Field(min_length=1, max_length=200)
    plan: str = Field(default="starter", max_length=32)
    language: str = Field(default="en", max_length=8)
    timezone: TimezoneName = "Asia/Riyadh"
    owner_email: Email


class OrganisationOut(_Out):
    id: str
    name: str
    plan: str
    language: str
    timezone: str


class OrganisationCreated(BaseModel):
    organisation: OrganisationOut
    owner_invitation: InvitationCreated


# --------------------------------------------------------------------------- sites


class SiteCreate(_In):
    name: str = Field(min_length=1, max_length=200)
    timezone: TimezoneName = "Asia/Riyadh"
    address: str = Field(default="", max_length=1000)
    opening_hours: dict[str, Any] = Field(default_factory=dict)
    events_only: bool = False


class SiteUpdate(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: TimezoneName | None = None
    address: str | None = Field(default=None, max_length=1000)
    opening_hours: dict[str, Any] | None = None
    events_only: bool | None = None


class SiteOut(_Out):
    id: str
    name: str
    timezone: str
    address: str
    opening_hours: dict[str, Any]
    events_only: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- cameras


class CameraCreate(_In):
    name: str = Field(default="", max_length=200)
    source: str = Field(min_length=1, max_length=2000, description="rtsp:// URL; stored encrypted")
    fps: float = Field(default=5.0, gt=0, le=30)
    zones: list[Zone] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    enabled: bool = True


class CameraUpdate(_In):
    name: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, min_length=1, max_length=2000)
    fps: float | None = Field(default=None, gt=0, le=30)
    zones: list[Zone] | None = None
    lines: list[Line] | None = None
    enabled: bool | None = None


class CameraOut(BaseModel):
    id: str
    site_id: str
    name: str
    source_redacted: str = Field(description="stream URL without credentials")
    fps: float
    width: int | None
    height: int | None
    status: str
    status_at: datetime | None
    enabled: bool
    zones: list[Zone]
    lines: list[Line]


# --------------------------------------------------------------------------- rules


class RuleIn(Rule):
    """A shared `Rule` whose id is assigned by the cloud."""

    id: str | None = Field(default=None, max_length=64)  # type: ignore[assignment]


class RuleOut(Rule):
    site_id: str
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- devices


class DeviceCreate(_In):
    name: str = Field(default="", max_length=200)
    hardware_tier: str = Field(default="standard", max_length=32)


class DeviceOut(_Out):
    id: str
    site_id: str
    name: str
    hardware_tier: str
    status: str
    enrolled_at: datetime | None
    last_heartbeat_at: datetime | None
    software_version: str | None
    model_version: str | None
    applied_config_version: int | None


class DeviceCreated(BaseModel):
    device: DeviceOut
    enrolment_token: str = Field(description="one-time token for `vision-edge enrol`; shown once")
    enrolment_expires_at: datetime


# --------------------------------------------------------------------------- events


class EventOut(Event):
    status: str
    verified: bool | None
    received_at: datetime
    updated_at: datetime


class FeedbackIn(_In):
    is_true: bool = Field(description="true = correct alert, false = false alarm")
    comment: str = Field(default="", max_length=2000)


class FeedbackOut(_Out):
    id: str
    event_id: str
    user_id: str | None
    is_true: bool
    channel: str
    comment: str
    created_at: datetime


class EventDetail(EventOut):
    snapshot_url: str | None = None
    clip_url: str | None = None
    media_url_expires_at: datetime | None = None
    feedback: list[FeedbackOut] = Field(default_factory=list)


class EventPage(BaseModel):
    items: list[EventOut]
    next_cursor: str | None = Field(description="pass as `cursor` to get the next page")


# --------------------------------------------------------------------------- recipients (CLD-08)

Channel = Literal["whatsapp", "telegram", "email"]
_ADDRESS = {
    "whatsapp": (re.compile(r"^\+[1-9]\d{7,14}$"), "an international number like +9665XXXXXXXX"),
    "telegram": (re.compile(r"^-?\d{4,20}$"), "a numeric Telegram chat id"),
    "email": (re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), "an email address"),
}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _hhmm(v: str | None) -> str | None:
    if v is not None and not _HHMM.match(v):
        raise ValueError("use HH:MM, 24-hour")
    return v


HHMM = Annotated[str | None, AfterValidator(_hhmm)]


def check_address(channel: str, address: str) -> None:
    pattern, hint = _ADDRESS[channel]
    if not pattern.match(address):
        raise ValueError(f"{channel} address must be {hint}")


def check_quiet_hours(start: str | None, end: str | None) -> None:
    if (start is None) != (end is None):
        raise ValueError("set both quiet_hours_start and quiet_hours_end, or neither")
    if start is not None and start == end:
        raise ValueError("quiet hours must not start and end at the same time")


class RecipientIn(_In):
    site_id: str | None = Field(default=None, description="None = every site (managers only)")
    name: str = Field(min_length=1, max_length=200)
    name_ar: str = Field(default="", max_length=200)
    channel: Channel
    address: str = Field(min_length=3, max_length=320)
    language: Literal["en", "ar"] = "en"
    min_severity: Severity = Severity.WARNING
    quiet_hours_start: HHMM = None
    quiet_hours_end: HHMM = None
    daily_cap: int = Field(default=50, ge=1, le=1000)
    escalation_rank: int | None = Field(
        default=None, ge=1, le=20, description="order in the escalation chain; None = not in it"
    )
    rule_ids: list[str] = Field(
        default_factory=list, max_length=200, description="empty = every rule of the site(s)"
    )
    enabled: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> RecipientIn:
        check_address(self.channel, self.address)
        check_quiet_hours(self.quiet_hours_start, self.quiet_hours_end)
        return self


class RecipientUpdate(_In):
    """PATCH: only the fields sent change. `site_id` cannot change (create a new recipient)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    channel: Channel | None = None
    address: str | None = Field(default=None, min_length=3, max_length=320)
    language: Literal["en", "ar"] | None = None
    min_severity: Severity | None = None
    quiet_hours_start: HHMM = None
    quiet_hours_end: HHMM = None
    daily_cap: int | None = Field(default=None, ge=1, le=1000)
    escalation_rank: int | None = Field(default=None, ge=1, le=20)
    rule_ids: list[str] | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class RecipientOut(_Out):
    id: str
    site_id: str | None
    name: str
    name_ar: str
    channel: str
    address: str
    language: str
    min_severity: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    daily_cap: int
    escalation_rank: int | None
    rule_ids: list[str]
    enabled: bool
    opted_in_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RecipientSummary(_Out):
    """What the dashboard's rule builder needs; no address (personal data)."""

    id: str
    name: str
    name_ar: str
    channel: str
