"""Request and response bodies of the dashboard-facing API (the web client is generated from them)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vision_cloud.models import (
    CameraStatus,
    DeviceStatus,
    EventStatus,
    Language,
    MediaState,
    Plan,
    Role,
)
from vision_shared.schemas import EventState, RuleType, Severity


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _email(v: str) -> str:
    v = v.strip()
    local, _, domain = v.rpartition("@")
    if not local or "." not in domain or " " in v or len(v) > 320:
        raise ValueError("not a valid email address")
    return v.lower()


# --------------------------------------------------------------------------- auth


class LoginIn(_In):
    email: str
    password: str = Field(max_length=256)
    otp: str | None = Field(default=None, max_length=12, description="authenticator-app code")

    _e = field_validator("email")(_email)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(_In):
    refresh_token: str = Field(min_length=16, max_length=256)


class InvitationPreview(BaseModel):
    organisation_name: str
    email: str
    role: Role
    existing_account: bool
    expires_at: datetime


class AcceptInvitationIn(_In):
    token: str = Field(min_length=16, max_length=256)
    password: str = Field(max_length=256)
    name: str = Field(default="", max_length=200)


class PasswordResetRequestIn(_In):
    email: str

    _e = field_validator("email")(_email)


class PasswordResetConfirmIn(_In):
    token: str = Field(min_length=16, max_length=256)
    password: str = Field(max_length=256)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(_In):
    code: str = Field(min_length=6, max_length=12)


class TotpDisableIn(_In):
    code: str = Field(min_length=6, max_length=12)
    password: str = Field(max_length=256)


# --------------------------------------------------------------------------- people


class MembershipOut(BaseModel):
    organisation_id: uuid.UUID
    organisation_name: str
    role: Role
    all_sites: bool
    site_ids: list[uuid.UUID] = Field(default_factory=list)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    language: Language
    is_platform_admin: bool
    totp_enabled: bool
    memberships: list[MembershipOut]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: Role
    all_sites: bool
    site_ids: list[uuid.UUID]


class InvitationIn(_In):
    email: str
    role: Role
    site_ids: list[uuid.UUID] = Field(
        default_factory=list, description="empty: all sites (not allowed for site_manager)"
    )

    _e = field_validator("email")(_email)


class InvitationOut(_Out):
    id: uuid.UUID
    email: str
    role: Role
    site_ids: list[str]
    expires_at: datetime
    accepted_at: datetime | None


# --------------------------------------------------------------------------- tenant resources


class OrganisationOut(_Out):
    id: uuid.UUID
    name: str
    slug: str
    plan: Plan
    language: Language
    timezone: str
    created_at: datetime


class SiteOut(_Out):
    id: uuid.UUID
    key: str
    name: str
    address: str
    timezone: str
    events_only: bool
    clip_retention_days: int


class CameraOut(_Out):
    """Never includes the stream URL: it carries the NVR password and stays server-side."""

    id: uuid.UUID
    site_id: uuid.UUID
    key: str
    name: str
    fps: float
    resolution: str | None
    status: CameraStatus
    last_frame_at: datetime | None
    enabled: bool


class DeviceOut(_Out):
    id: uuid.UUID
    organisation_id: uuid.UUID
    site_id: uuid.UUID
    name: str
    status: DeviceStatus
    software_version: str | None
    model_version: str | None
    applied_config_version: int | None
    last_heartbeat_at: datetime | None
    enrolled_at: datetime


class EventOut(_Out):
    id: uuid.UUID
    site_id: uuid.UUID
    camera_id: uuid.UUID
    rule_id: uuid.UUID | None
    rule_key: str
    rule_type: RuleType
    severity: Severity
    state: EventState
    status: EventStatus
    condition_started_at: datetime
    triggered_at: datetime
    cleared_at: datetime | None
    value: float
    message: str
    attributes: dict[str, Any]
    snapshot_state: MediaState
    clip_state: MediaState
    verified: bool | None
    received_at: datetime


class EventPage(BaseModel):
    items: list[EventOut]
    next_before: datetime | None = Field(
        description="pass as `before` to get the next (older) page; null at the end"
    )


# --------------------------------------------------------------------------- Code-Ox admin


class OrganisationIn(_In):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    plan: Plan = Plan.STARTER
    language: Language = Language.AR
    timezone: str = "Asia/Riyadh"
    owner_email: str

    _e = field_validator("owner_email")(_email)


class EnrolmentTokenIn(_In):
    organisation_id: uuid.UUID
    site_id: uuid.UUID
    device_name: str = Field(default="", max_length=200)
    ttl_s: int | None = Field(default=None, gt=0, le=7 * 24 * 3600)


class EnrolmentTokenOut(BaseModel):
    token: str = Field(description="shown once; type it into the edge box installer")
    expires_at: datetime


class ModelReleaseIn(_In):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    channel: str = Field(pattern=r"^(dev|staging|canary|stable)$")
    file_key: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    notes: str = ""


class ModelReleaseOut(_Out):
    id: uuid.UUID
    name: str
    version: str
    channel: str
    sha256: str
    size_bytes: int
    created_at: datetime
