"""Initial schema: the core data model of Phase 4 (CLD-01)

Generated from `vision_cloud.models` and reviewed; timestamps are `timestamptz`, JSON columns are
JSONB on PostgreSQL. Row-level security is added in 0002.

Revision ID: 0001
Revises:
Create Date: 2026-11-02 15:28:48.670655+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("hardware_tier", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_releases")),
        sa.UniqueConstraint(
            "hardware_tier", "version", name=op.f("uq_model_releases_hardware_tier_version")
        ),
    )
    op.create_table(
        "organisations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisations")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_audit_log_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_audit_log_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        op.f("ix_audit_log_organisation_id"), "audit_log", ["organisation_id"], unique=False
    )

    op.create_table(
        "invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "site_ids",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_invitations_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(
        op.f("ix_invitations_organisation_id"), "invitations", ["organisation_id"], unique=False
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_memberships_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint(
            "organisation_id", "user_id", name=op.f("uq_memberships_organisation_id_user_id")
        ),
    )
    op.create_index(
        op.f("ix_memberships_organisation_id"), "memberships", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_refresh_tokens_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "sites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column(
            "opening_hours",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("events_only", sa.Boolean(), nullable=False),
        sa.Column("camera_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_sites_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sites")),
    )
    op.create_index(op.f("ix_sites_organisation_id"), "sites", ["organisation_id"], unique=False)

    op.create_table(
        "cameras",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("stream_url_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("fps", sa.Float(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("snapshot_key", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_cameras_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_cameras_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cameras")),
    )
    op.create_index(
        op.f("ix_cameras_organisation_id"), "cameras", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_cameras_site_id"), "cameras", ["site_id"], unique=False)

    op.create_table(
        "config_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=64), nullable=False),
        sa.Column(
            "config",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_config_versions_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_config_versions_site_id_sites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_versions")),
        sa.UniqueConstraint("site_id", "version", name=op.f("uq_config_versions_site_id_version")),
    )
    op.create_index(
        op.f("ix_config_versions_organisation_id"),
        "config_versions",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_config_versions_site_id"), "config_versions", ["site_id"], unique=False
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hardware_tier", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("enrolment_token_hash", sa.String(length=64), nullable=True),
        sa.Column("enrolment_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credential_hash", sa.String(length=64), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_heartbeat",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("software_version", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("applied_config_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_devices_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_devices_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.UniqueConstraint("credential_hash", name=op.f("uq_devices_credential_hash")),
        sa.UniqueConstraint("enrolment_token_hash", name=op.f("uq_devices_enrolment_token_hash")),
    )
    op.create_index(
        op.f("ix_devices_organisation_id"), "devices", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_devices_site_id"), "devices", ["site_id"], unique=False)

    op.create_table(
        "membership_sites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name=op.f("fk_membership_sites_membership_id_memberships"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_membership_sites_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_membership_sites_site_id_sites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_sites")),
        sa.UniqueConstraint(
            "membership_id", "site_id", name=op.f("uq_membership_sites_membership_id_site_id")
        ),
    )
    op.create_index(
        op.f("ix_membership_sites_membership_id"),
        "membership_sites",
        ["membership_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_membership_sites_organisation_id"),
        "membership_sites",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_membership_sites_site_id"), "membership_sites", ["site_id"], unique=False
    )

    op.create_table(
        "recipients",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("min_severity", sa.String(length=16), nullable=False),
        sa.Column("opted_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_recipients_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_recipients_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipients")),
    )
    op.create_index(
        op.f("ix_recipients_organisation_id"), "recipients", ["organisation_id"], unique=False
    )

    op.create_table(
        "aggregates_minute",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("minute", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name=op.f("fk_aggregates_minute_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_aggregates_minute_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name=op.f("fk_aggregates_minute_site_id_sites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aggregates_minute")),
        sa.UniqueConstraint(
            "camera_id",
            "minute",
            "metric",
            "target",
            name=op.f("uq_aggregates_minute_camera_id_minute_metric_target"),
        ),
    )
    op.create_index(
        op.f("ix_aggregates_minute_organisation_id"),
        "aggregates_minute",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_aggregates_minute_site_id"), "aggregates_minute", ["site_id"], unique=False
    )

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("condition_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("snapshot_key", sa.String(length=512), nullable=True),
        sa.Column("clip_key", sa.String(length=512), nullable=True),
        sa.Column("needs_verification", sa.Boolean(), nullable=False),
        sa.Column(
            "vlm_verdict",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("edge_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name=op.f("fk_events_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_events_device_id_devices"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_events_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_events_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index(op.f("ix_events_camera_id"), "events", ["camera_id"], unique=False)
    op.create_index(
        "ix_events_org_triggered", "events", ["organisation_id", "triggered_at", "id"], unique=False
    )
    op.create_index(op.f("ix_events_organisation_id"), "events", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_events_rule_id"), "events", ["rule_id"], unique=False)
    op.create_index("ix_events_site_triggered", "events", ["site_id", "triggered_at"], unique=False)

    op.create_table(
        "lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "start",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "end",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name=op.f("fk_lines_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_lines_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lines")),
        sa.UniqueConstraint("camera_id", "key", name=op.f("uq_lines_camera_id_key")),
    )
    op.create_index(op.f("ix_lines_camera_id"), "lines", ["camera_id"], unique=False)
    op.create_index(op.f("ix_lines_organisation_id"), "lines", ["organisation_id"], unique=False)

    op.create_table(
        "rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "definition",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name=op.f("fk_rules_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_rules_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_rules_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rules")),
    )
    op.create_index(op.f("ix_rules_camera_id"), "rules", ["camera_id"], unique=False)
    op.create_index(op.f("ix_rules_organisation_id"), "rules", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_rules_site_id"), "rules", ["site_id"], unique=False)

    op.create_table(
        "zones",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "polygon",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name=op.f("fk_zones_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_zones_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zones")),
        sa.UniqueConstraint("camera_id", "key", name=op.f("uq_zones_camera_id_key")),
    )
    op.create_index(op.f("ix_zones_camera_id"), "zones", ["camera_id"], unique=False)
    op.create_index(op.f("ix_zones_organisation_id"), "zones", ["organisation_id"], unique=False)

    op.create_table(
        "event_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("is_true", sa.Boolean(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_feedback_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_event_feedback_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_event_feedback_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_feedback")),
    )
    op.create_index(
        op.f("ix_event_feedback_event_id"), "event_feedback", ["event_id"], unique=False
    )
    op.create_index(
        op.f("ix_event_feedback_organisation_id"),
        "event_feedback",
        ["organisation_id"],
        unique=False,
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("recipient_id", sa.String(length=36), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_notifications_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_notifications_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["recipients.id"],
            name=op.f("fk_notifications_recipient_id_recipients"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_event_id"), "notifications", ["event_id"], unique=False)
    op.create_index(
        op.f("ix_notifications_organisation_id"), "notifications", ["organisation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_organisation_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_event_id"), table_name="notifications")

    op.drop_table("notifications")
    op.drop_index(op.f("ix_event_feedback_organisation_id"), table_name="event_feedback")
    op.drop_index(op.f("ix_event_feedback_event_id"), table_name="event_feedback")

    op.drop_table("event_feedback")
    op.drop_index(op.f("ix_zones_organisation_id"), table_name="zones")
    op.drop_index(op.f("ix_zones_camera_id"), table_name="zones")

    op.drop_table("zones")
    op.drop_index(op.f("ix_rules_site_id"), table_name="rules")
    op.drop_index(op.f("ix_rules_organisation_id"), table_name="rules")
    op.drop_index(op.f("ix_rules_camera_id"), table_name="rules")

    op.drop_table("rules")
    op.drop_index(op.f("ix_lines_organisation_id"), table_name="lines")
    op.drop_index(op.f("ix_lines_camera_id"), table_name="lines")

    op.drop_table("lines")
    op.drop_index("ix_events_site_triggered", table_name="events")
    op.drop_index(op.f("ix_events_rule_id"), table_name="events")
    op.drop_index(op.f("ix_events_organisation_id"), table_name="events")
    op.drop_index("ix_events_org_triggered", table_name="events")
    op.drop_index(op.f("ix_events_camera_id"), table_name="events")

    op.drop_table("events")
    op.drop_index(op.f("ix_aggregates_minute_site_id"), table_name="aggregates_minute")
    op.drop_index(op.f("ix_aggregates_minute_organisation_id"), table_name="aggregates_minute")

    op.drop_table("aggregates_minute")
    op.drop_index(op.f("ix_recipients_organisation_id"), table_name="recipients")

    op.drop_table("recipients")
    op.drop_index(op.f("ix_membership_sites_site_id"), table_name="membership_sites")
    op.drop_index(op.f("ix_membership_sites_organisation_id"), table_name="membership_sites")
    op.drop_index(op.f("ix_membership_sites_membership_id"), table_name="membership_sites")

    op.drop_table("membership_sites")
    op.drop_index(op.f("ix_devices_site_id"), table_name="devices")
    op.drop_index(op.f("ix_devices_organisation_id"), table_name="devices")

    op.drop_table("devices")
    op.drop_index(op.f("ix_config_versions_site_id"), table_name="config_versions")
    op.drop_index(op.f("ix_config_versions_organisation_id"), table_name="config_versions")

    op.drop_table("config_versions")
    op.drop_index(op.f("ix_cameras_site_id"), table_name="cameras")
    op.drop_index(op.f("ix_cameras_organisation_id"), table_name="cameras")

    op.drop_table("cameras")
    op.drop_index(op.f("ix_sites_organisation_id"), table_name="sites")

    op.drop_table("sites")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")

    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_organisation_id"), table_name="memberships")

    op.drop_table("memberships")
    op.drop_index(op.f("ix_invitations_organisation_id"), table_name="invitations")

    op.drop_table("invitations")
    op.drop_index(op.f("ix_audit_log_organisation_id"), table_name="audit_log")

    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("organisations")
    op.drop_table("model_releases")
