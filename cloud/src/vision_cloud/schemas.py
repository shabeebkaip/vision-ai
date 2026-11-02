"""Dashboard-facing API payloads (CLD-03, CLD-07).

Where a shared contract exists it is reused: zones and lines are `vision_shared.schemas.Zone/Line`,
rules extend `Rule`, events extend `Event`. Device payloads live in `vision_shared.api`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from vision_cloud.models import Role
from vision_shared.schemas import Event, Line, Rule, Zone


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
