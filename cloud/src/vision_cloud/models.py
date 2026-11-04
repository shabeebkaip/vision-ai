"""ORM models: the core data model of docs/development-task-plan.md, Phase 4 (CLD-01).

Ids are UUID strings: they double as the `id` fields of the shared `SiteConfig`, `CameraConfig` and
`Rule`, so an edge box and the cloud speak about the same objects. Zone and line ids are per-camera
keys (e.g. "desk"), as in the shared schema. Every customer-owned table carries `organisation_id`
(via `TenantMixin`). Not tenant-owned: `users` (a person can belong to several organisations),
`refresh_tokens` (per user) and `model_releases` (global).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vision_cloud.db import Base, JSONType, TenantMixin, new_id, utcnow


class Role(str, Enum):
    """Roles inside one organisation. The Code-Ox admin role is `users.is_platform_admin`."""

    OWNER = "owner"
    MANAGER = "manager"
    SITE_MANAGER = "site_manager"
    VIEWER = "viewer"


ROLE_RANK = {Role.VIEWER: 0, Role.SITE_MANAGER: 1, Role.MANAGER: 2, Role.OWNER: 3}
SITE_SCOPED_ROLES = {Role.SITE_MANAGER, Role.VIEWER}


class DeviceStatus(str, Enum):
    PENDING = "pending"  # created, waiting for enrolment
    ACTIVE = "active"
    REVOKED = "revoked"


class EventStatus(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


def _id_col() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(default=utcnow)


# --------------------------------------------------------------------------- tenants and people


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[str] = _id_col()
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(32), default="starter")
    language: Mapped[str] = mapped_column(String(8), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh")
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _id_col()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    password_hash: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None]


class Membership(TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organisation_id", "user_id"),)

    id: Mapped[str] = _id_col()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(lazy="joined")
    site_access: Mapped[list[MembershipSite]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class MembershipSite(TenantMixin, Base):
    """Per-site access for site managers and viewers."""

    __tablename__ = "membership_sites"
    __table_args__ = (UniqueConstraint("membership_id", "site_id"),)

    id: Mapped[str] = _id_col()
    membership_id: Mapped[str] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)


class Invitation(TenantMixin, Base):
    __tablename__ = "invitations"

    id: Mapped[str] = _id_col()
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(32))
    site_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _created()


class RefreshToken(Base):
    """Opaque rotating refresh tokens (only the SHA-256 is stored)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = _id_col()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organisation_id: Mapped[str] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    replaced_by: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = _created()


# --------------------------------------------------------------------------- sites, devices, cameras


class Site(TenantMixin, Base):
    __tablename__ = "sites"

    id: Mapped[str] = _id_col()
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Riyadh")
    address: Mapped[str] = mapped_column(Text, default="")
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    events_only: Mapped[bool] = mapped_column(Boolean, default=False)
    camera_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Device(TenantMixin, Base):
    __tablename__ = "devices"

    id: Mapped[str] = _id_col()
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    hardware_tier: Mapped[str] = mapped_column(String(32), default="standard")
    status: Mapped[str] = mapped_column(String(16), default=DeviceStatus.PENDING.value)
    enrolment_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    enrolment_expires_at: Mapped[datetime | None]
    credential_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    enrolled_at: Mapped[datetime | None]
    last_heartbeat_at: Mapped[datetime | None]
    last_heartbeat: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    software_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    applied_config_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class Camera(TenantMixin, Base):
    __tablename__ = "cameras"

    id: Mapped[str] = _id_col()
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    stream_url_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    fps: Mapped[float] = mapped_column(Float, default=5.0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    status_at: Mapped[datetime | None]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    snapshot_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    zones: Mapped[list[Zone]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Zone.key"
    )
    lines: Mapped[list[LineRow]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="LineRow.key"
    )


class Zone(TenantMixin, Base):
    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("camera_id", "key"),)

    id: Mapped[str] = _id_col()
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    polygon: Mapped[list[list[float]]] = mapped_column(JSONType)


class LineRow(TenantMixin, Base):
    __tablename__ = "lines"
    __table_args__ = (UniqueConstraint("camera_id", "key"),)

    id: Mapped[str] = _id_col()
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    start: Mapped[list[float]] = mapped_column(JSONType)
    end: Mapped[list[float]] = mapped_column(JSONType)


class RuleRow(TenantMixin, Base):
    """One rule. `definition` is the shared `Rule` (validated) minus `id` and `camera_id`;
    the columns next to it exist for filtering."""

    __tablename__ = "rules"

    id: Mapped[str] = _id_col()
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# --------------------------------------------------------------------------- events


class EventRow(TenantMixin, Base):
    """An event from an edge box. `id` is the edge-generated `Event.id` (idempotency key)."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_org_triggered", "organisation_id", "triggered_at", "id"),
        Index("ix_events_site_triggered", "site_id", "triggered_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    schema_version: Mapped[str] = mapped_column(String(16))
    condition_started_at: Mapped[datetime]
    triggered_at: Mapped[datetime]
    cleared_at: Mapped[datetime | None]
    value: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    snapshot_key: Mapped[str | None] = mapped_column(String(512))
    clip_key: Mapped[str | None] = mapped_column(String(512))
    alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), index=True
    )
    needs_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    vlm_verdict: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(16), default=EventStatus.NEW.value)
    verified: Mapped[bool | None] = mapped_column(Boolean)  # latest feedback: true / false alarm
    edge_created_at: Mapped[datetime]
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class EventFeedback(TenantMixin, Base):
    __tablename__ = "event_feedback"

    id: Mapped[str] = _id_col()
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_true: Mapped[bool] = mapped_column(Boolean)
    channel: Mapped[str] = mapped_column(String(16), default="dashboard")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class Recipient(TenantMixin, Base):
    """Who gets alerts (CLD-08). `site_id` None = every site of the organisation. Without rows in
    `recipient_rules` the recipient gets every rule of those sites (at or above `min_severity`)."""

    __tablename__ = "recipients"

    id: Mapped[str] = _id_col()
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), default="")
    name_ar: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(16))  # whatsapp | telegram | email
    address: Mapped[str] = mapped_column(String(320))
    language: Mapped[str] = mapped_column(String(8), default="en")
    min_severity: Mapped[str] = mapped_column(String(16), default="warning")
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5))  # "HH:MM", site timezone
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5))
    daily_cap: Mapped[int] = mapped_column(Integer, default=50)
    escalation_rank: Mapped[int | None] = mapped_column(Integer)  # 1 = first to escalate to
    # Telegram linking (CLD-10): the hash of a one-time code the person sends to the bot.
    telegram_link_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    telegram_link_expires_at: Mapped[datetime | None]
    opted_in_at: Mapped[datetime | None]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    rules: Mapped[list[RecipientRule]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class RecipientRule(TenantMixin, Base):
    """Limits a recipient to these rules (CLD-08)."""

    __tablename__ = "recipient_rules"

    recipient_id: Mapped[str] = mapped_column(
        ForeignKey("recipients.id", ondelete="CASCADE"), primary_key=True
    )
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class AlertStatus(str, Enum):
    OPEN = "open"  # still collecting events of the same camera and rule
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class Alert(TenantMixin, Base):
    """What a person is told about (CLD-08): events of one camera and rule close together in time,
    grouped so a burst of 30 events is one message with a count."""

    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_group", "camera_id", "rule_id", "last_event_at"),)

    id: Mapped[str] = _id_col()
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(String(64))
    rule_type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    first_event_id: Mapped[str] = mapped_column(String(64))
    last_event_id: Mapped[str] = mapped_column(String(64))
    event_count: Mapped[int] = mapped_column(Integer, default=1)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=AlertStatus.OPEN.value)
    opened_at: Mapped[datetime]
    last_event_at: Mapped[datetime]
    acknowledged_at: Mapped[datetime | None]
    acknowledged_by: Mapped[str | None] = mapped_column(String(200))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class NotificationStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"  # accepted by the provider
    DELIVERED = "delivered"  # provider confirmed delivery (WhatsApp/Telegram status callbacks)
    FAILED = "failed"  # gave up after retries
    SUPPRESSED = "suppressed"  # not sent on purpose: quiet hours, daily cap (see `reason`)


class Notification(TenantMixin, Base):
    """The delivery log (CLD-08): one row per alert, recipient and message kind."""

    __tablename__ = "notifications"

    id: Mapped[str] = _id_col()
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[str | None] = mapped_column(
        ForeignKey("recipients.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), default="alert")  # alert | escalation | update
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=NotificationStatus.QUEUED.value)
    reason: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _created()


class AggregateMinute(TenantMixin, Base):
    """Per-camera, per-minute counts (occupancy, in/out, queue, dwell) from the edge."""

    __tablename__ = "aggregates_minute"
    __table_args__ = (UniqueConstraint("camera_id", "minute", "metric", "target"),)

    id: Mapped[str] = _id_col()
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    minute: Mapped[datetime]
    metric: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(64), default="")  # zone or line key, "" = camera
    value: Mapped[float] = mapped_column(Float)


class ConfigVersion(TenantMixin, Base):
    """Every distinct SiteConfig ever served to a site's devices."""

    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("site_id", "version"),)

    id: Mapped[str] = _id_col()
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    etag: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created()


class ModelRelease(Base):
    """Detector model builds that devices should run (global, not tenant-owned)."""

    __tablename__ = "model_releases"
    __table_args__ = (UniqueConstraint("hardware_tier", "version"),)

    id: Mapped[str] = _id_col()
    hardware_tier: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class AuditLog(TenantMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = _id_col()
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    device_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()


def tenant_tables() -> list[str]:
    """Every table with an `organisation_id` column; each must have an RLS policy (migrations 0002
    and later)."""
    return sorted(
        table.name for table in Base.metadata.sorted_tables if "organisation_id" in table.c
    )
