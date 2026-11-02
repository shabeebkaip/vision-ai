"""Database schema (task CLD-01).

Every customer-owned table carries `organisation_id`. Access is filtered on it in code and, as the
second lock, by PostgreSQL row-level security (policies are created in the Alembic migration; see
`vision_cloud.tenancy`). Child tables reference their parent with a composite foreign key
`(parent_id, organisation_id)` so a row can never point at another organisation's parent.

Rule, severity, direction and event-state values come from `vision_shared.schemas`, so the database
accepts exactly what the shared contract allows.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from vision_cloud import crypto
from vision_shared.schemas import Direction, EventState, RuleType, Severity

# --------------------------------------------------------------------------- helpers


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(cls: type[Enum], name: str) -> sa.Enum:
    """VARCHAR + CHECK constraint storing the enum *values* (no native PG enum: easier migrations)."""
    return sa.Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class EncryptedString(TypeDecorator[str]):
    """Text column encrypted with the service Fernet key."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: sa.Dialect) -> str | None:
        return None if value is None else crypto.encrypt(value)

    def process_result_value(self, value: str | None, dialect: sa.Dialect) -> str | None:
        return None if value is None else crypto.decrypt(value)


TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    metadata = sa.MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _org() -> Mapped[uuid.UUID]:
    return mapped_column(
        Uuid, ForeignKey("organisations.id", ondelete="CASCADE"), index=True, nullable=False
    )


def _created() -> Mapped[datetime]:
    return mapped_column(TZ, default=utcnow, server_default=sa.func.now(), nullable=False)


# --------------------------------------------------------------------------- cloud-side enums


class Plan(str, Enum):
    STARTER = "starter"
    STANDARD = "standard"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class Language(str, Enum):
    EN = "en"
    AR = "ar"


class Role(str, Enum):
    """Roles inside one organisation. The Code-Ox admin is `User.is_platform_admin`, not a role."""

    OWNER = "owner"
    MANAGER = "manager"
    SITE_MANAGER = "site_manager"
    VIEWER = "viewer"


class DeviceStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class HardwareTier(str, Enum):
    JETSON_ORIN_NANO = "jetson_orin_nano"
    JETSON_ORIN_NX = "jetson_orin_nx"
    MINI_PC = "mini_pc"
    OTHER = "other"


class CameraStatus(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"


class EventStatus(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"  # VLM second opinion said "no" (CLD-12)


class MediaState(str, Enum):
    NONE = "none"  # no media expected (events-only site, or edge sent none)
    PENDING = "pending"  # upload URL issued, not finalised
    STORED = "stored"  # finalised: object exists in storage


class Channel(str, Enum):
    DASHBOARD = "dashboard"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    EMAIL = "email"


class NotificationStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class ReleaseChannel(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    CANARY = "canary"
    STABLE = "stable"


# --------------------------------------------------------------------------- organisations, people


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[Plan] = mapped_column(_enum(Plan, "plan"), default=Plan.STARTER)
    language: Mapped[Language] = mapped_column(_enum(Language, "language"), default=Language.AR)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh")
    created_at: Mapped[datetime] = _created()


class User(Base):
    """A person. Global (one login across organisations); access comes from `memberships`."""

    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email_lower", sa.func.lower(sa.text("email")), unique=True),)

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[Language] = mapped_column(
        _enum(Language, "user_language"), default=Language.AR
    )
    totp_secret: Mapped[str | None] = mapped_column(EncryptedString)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organisation_id", "user_id"),
        UniqueConstraint("id", "organisation_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(_enum(Role, "role"))
    all_sites: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class MembershipSite(Base):
    """Sites a membership is limited to when `all_sites` is false."""

    __tablename__ = "membership_sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["membership_id", "organisation_id"],
            ["memberships.id", "memberships.organisation_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organisation_id: Mapped[uuid.UUID] = _org()


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(_enum(Role, "invitation_role"))
    site_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(TZ)
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created()


class RefreshToken(Base):
    """Rotating refresh tokens. Re-using a rotated token revokes the whole family."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(TZ)
    rotated_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created()


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(TZ)
    used_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- sites and devices


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("organisation_id", "key"),
        UniqueConstraint("id", "organisation_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    key: Mapped[str] = mapped_column(String(64), doc="SiteConfig.id seen by the edge")
    name: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh")
    opening_hours: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    events_only: Mapped[bool] = mapped_column(Boolean, default=False)
    clip_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = _created()


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[DeviceStatus] = mapped_column(
        _enum(DeviceStatus, "device_status"), default=DeviceStatus.ACTIVE
    )
    hardware_tier: Mapped[HardwareTier | None] = mapped_column(_enum(HardwareTier, "hardware_tier"))
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    model_channel: Mapped[ReleaseChannel] = mapped_column(
        _enum(ReleaseChannel, "device_model_channel"), default=ReleaseChannel.STABLE
    )
    pinned_model_release_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("model_releases.id", ondelete="SET NULL")
    )
    software_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(128))
    applied_config_version: Mapped[int | None] = mapped_column(Integer)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(TZ)
    last_heartbeat: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    logs_requested_at: Mapped[datetime | None] = mapped_column(TZ)
    enrolled_at: Mapped[datetime] = _created()


class EnrolmentToken(Base):
    __tablename__ = "enrolment_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    device_name: Mapped[str] = mapped_column(String(200), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(TZ)
    used_at: Mapped[datetime | None] = mapped_column(TZ)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        UniqueConstraint("site_id", "key"),
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    key: Mapped[str] = mapped_column(String(64), doc="CameraConfig.id seen by the edge")
    name: Mapped[str] = mapped_column(String(200), default="")
    stream_url: Mapped[str] = mapped_column(EncryptedString, doc="encrypted at rest")
    fps: Mapped[float] = mapped_column(Float, default=5.0)
    resolution: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[CameraStatus] = mapped_column(
        _enum(CameraStatus, "camera_status"), default=CameraStatus.UNKNOWN
    )
    last_frame_at: Mapped[datetime | None] = mapped_column(TZ)
    snapshot_key: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("camera_id", "key"),
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["camera_id", "organisation_id"],
            ["cameras.id", "cameras.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    camera_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    polygon: Mapped[list[list[float]]] = mapped_column(JSONB, doc="normalised 0..1 points")


class Line(Base):
    __tablename__ = "lines"
    __table_args__ = (
        UniqueConstraint("camera_id", "key"),
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["camera_id", "organisation_id"],
            ["cameras.id", "cameras.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    camera_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    start_point: Mapped[list[float]] = mapped_column(JSONB)
    end_point: Mapped[list[float]] = mapped_column(JSONB)


class Rule(Base):
    """Mirrors `vision_shared.schemas.Rule`; `key` is the rule id the edge sees."""

    __tablename__ = "rules"
    __table_args__ = (
        UniqueConstraint("site_id", "key"),
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["camera_id", "organisation_id"],
            ["cameras.id", "cameras.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    camera_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    type: Mapped[RuleType] = mapped_column(_enum(RuleType, "rule_type"))
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="RESTRICT")
    )
    line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("lines.id", ondelete="RESTRICT")
    )
    classes: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["person"])
    threshold: Mapped[int] = mapped_column(Integer, default=1)
    min_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    window_s: Mapped[float] = mapped_column(Float, default=60.0)
    direction: Mapped[Direction] = mapped_column(
        _enum(Direction, "direction"), default=Direction.ANY
    )
    clear_after_s: Mapped[float] = mapped_column(Float, default=10.0)
    cooldown_s: Mapped[float] = mapped_column(Float, default=300.0)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.4)
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    severity: Mapped[Severity] = mapped_column(
        _enum(Severity, "severity"), default=Severity.WARNING
    )
    verify: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        TZ, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )


# --------------------------------------------------------------------------- alerting


class Recipient(Base):
    __tablename__ = "recipients"
    __table_args__ = (UniqueConstraint("id", "organisation_id"),)

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[Language] = mapped_column(
        _enum(Language, "recipient_language"), default=Language.AR
    )
    whatsapp_number: Mapped[str | None] = mapped_column(String(32))
    whatsapp_opt_in_at: Mapped[datetime | None] = mapped_column(TZ)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(320))
    quiet_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    min_severity: Mapped[Severity] = mapped_column(
        _enum(Severity, "recipient_min_severity"), default=Severity.INFO
    )
    daily_cap: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class RuleRecipient(Base):
    __tablename__ = "rule_recipients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "organisation_id"],
            ["rules.id", "rules.organisation_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "organisation_id"],
            ["recipients.id", "recipients.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organisation_id: Mapped[uuid.UUID] = _org()
    escalation_order: Mapped[int] = mapped_column(Integer, default=0)


class EventRow(Base):
    """One alert event. `id` is the edge-generated UUID and doubles as the idempotency key."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["camera_id", "organisation_id"],
            ["cameras.id", "cameras.organisation_id"],
            ondelete="CASCADE",
        ),
        Index("ix_events_org_triggered", "organisation_id", sa.text("triggered_at DESC")),
        Index("ix_events_site_triggered", "site_id", sa.text("triggered_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    camera_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rules.id", ondelete="SET NULL"), index=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    rule_key: Mapped[str] = mapped_column(String(64), doc="rule id as sent by the edge")
    rule_type: Mapped[RuleType] = mapped_column(_enum(RuleType, "event_rule_type"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "event_severity"))
    state: Mapped[EventState] = mapped_column(_enum(EventState, "event_state"))
    status: Mapped[EventStatus] = mapped_column(
        _enum(EventStatus, "event_status"), default=EventStatus.NEW
    )
    condition_started_at: Mapped[datetime] = mapped_column(TZ)
    triggered_at: Mapped[datetime] = mapped_column(TZ)
    cleared_at: Mapped[datetime | None] = mapped_column(TZ)
    value: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    needs_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_version: Mapped[str] = mapped_column(String(16))
    snapshot_key: Mapped[str | None] = mapped_column(Text)
    snapshot_state: Mapped[MediaState] = mapped_column(
        _enum(MediaState, "snapshot_state"), default=MediaState.NONE
    )
    clip_key: Mapped[str | None] = mapped_column(Text)
    clip_state: Mapped[MediaState] = mapped_column(
        _enum(MediaState, "clip_state"), default=MediaState.NONE
    )
    vlm_verdict: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verified: Mapped[bool | None] = mapped_column(Boolean, doc="latest human feedback")
    edge_created_at: Mapped[datetime] = mapped_column(TZ)
    received_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        TZ, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )


class EventFeedback(Base):
    __tablename__ = "event_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "organisation_id"],
            ["events.id", "events.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "feedback_channel"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("recipients.id", ondelete="SET NULL")
    )
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class Notification(Base):
    """Every delivery attempt of an alert to one recipient on one channel."""

    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "organisation_id"],
            ["events.id", "events.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("recipients.id", ondelete="SET NULL")
    )
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "notification_channel"))
    status: Mapped[NotificationStatus] = mapped_column(
        _enum(NotificationStatus, "notification_status"), default=NotificationStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    group_count: Mapped[int] = mapped_column(Integer, default=1)
    provider_message_id: Mapped[str | None] = mapped_column(String(256))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        TZ, default=utcnow, onupdate=utcnow, server_default=sa.func.now()
    )


# --------------------------------------------------------------------------- counts, config, audit


class AggregateMinute(Base):
    """Counts per camera per minute (occupancy, in/out, queue, dwell) from the edge (EDG-10)."""

    __tablename__ = "aggregates_minute"
    __table_args__ = (
        UniqueConstraint("camera_id", "minute"),
        ForeignKeyConstraint(
            ["camera_id", "organisation_id"],
            ["cameras.id", "cameras.organisation_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
        Index("ix_aggregates_site_minute", "site_id", "minute"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    camera_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    minute: Mapped[datetime] = mapped_column(TZ)
    occupancy_avg: Mapped[float | None] = mapped_column(Float)
    occupancy_max: Mapped[int | None] = mapped_column(Integer)
    entries: Mapped[int | None] = mapped_column(Integer)
    exits: Mapped[int | None] = mapped_column(Integer)
    queue_length_max: Mapped[int | None] = mapped_column(Integer)
    dwell_avg_s: Mapped[float | None] = mapped_column(Float)
    dwell_max_s: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ConfigVersion(Base):
    """Every distinct SiteConfig published to a site's edge box; the latest one is served."""

    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("site_id", "version"),
        ForeignKeyConstraint(
            ["site_id", "organisation_id"],
            ["sites.id", "sites.organisation_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    organisation_id: Mapped[uuid.UUID] = _org()
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, doc="SiteConfig without stream URLs")
    created_at: Mapped[datetime] = _created()


class ModelRelease(Base):
    """Detector model builds (Code-Ox owned, not tenant data). Rollout is by device channel."""

    __tablename__ = "model_releases"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(64))
    channel: Mapped[ReleaseChannel] = mapped_column(_enum(ReleaseChannel, "release_channel"))
    file_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_created", "organisation_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("devices.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


# Tables protected by the plain tenant policy (organisation_id = current organisation).
TENANT_TABLES: tuple[str, ...] = (
    "memberships",
    "membership_sites",
    "invitations",
    "sites",
    "devices",
    "enrolment_tokens",
    "cameras",
    "zones",
    "lines",
    "rules",
    "recipients",
    "rule_recipients",
    "events",
    "event_feedback",
    "notifications",
    "aggregates_minute",
    "config_versions",
    "audit_log",
)
# Tables tied to a user rather than an organisation.
USER_TABLES: tuple[str, ...] = ("refresh_tokens", "password_resets")
