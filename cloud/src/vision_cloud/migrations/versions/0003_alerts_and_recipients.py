"""Alerts and recipient settings for the alert dispatcher (CLD-08)

- `alerts`: events of one camera and rule close in time, grouped into what a person is told about
- `recipient_rules`: limits a recipient to some rules
- `recipients`: Arabic name, quiet hours, daily cap, escalation rank, updated_at
- `events.alert_id`, `notifications.alert_id`, `notifications.kind`, `notifications.reason`

Row-level security for the two new tenant tables, as in 0002.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("alerts", "recipient_rules")
POLICY = "tenant_isolation"
_COND = (
    "(organisation_id = current_setting('app.current_org', true) "
    "OR current_setting('app.bypass_rls', true) = 'on')"
)


def _org_column(table: str) -> list[sa.Column[str] | sa.ForeignKeyConstraint]:
    return [
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f(f"fk_{table}_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("first_event_id", sa.String(length=64), nullable=False),
        sa.Column("last_event_id", sa.String(length=64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=200), nullable=True),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *_org_column("alerts"),
        sa.ForeignKeyConstraint(
            ["camera_id"],
            ["cameras.id"],
            name=op.f("fk_alerts_camera_id_cameras"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], name=op.f("fk_alerts_site_id_sites"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index("ix_alerts_group", "alerts", ["camera_id", "rule_id", "last_event_at"])
    op.create_index(op.f("ix_alerts_organisation_id"), "alerts", ["organisation_id"])
    op.create_index(op.f("ix_alerts_site_id"), "alerts", ["site_id"])

    op.create_table(
        "recipient_rules",
        sa.Column("recipient_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        *_org_column("recipient_rules"),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["recipients.id"],
            name=op.f("fk_recipient_rules_recipient_id_recipients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["rules.id"],
            name=op.f("fk_recipient_rules_rule_id_rules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("recipient_id", "rule_id", name=op.f("pk_recipient_rules")),
    )
    op.create_index(
        op.f("ix_recipient_rules_organisation_id"), "recipient_rules", ["organisation_id"]
    )
    op.create_index(op.f("ix_recipient_rules_rule_id"), "recipient_rules", ["rule_id"])

    with op.batch_alter_table("recipients") as b:
        b.add_column(sa.Column("name_ar", sa.String(length=200), nullable=False, server_default=""))
        b.add_column(sa.Column("quiet_hours_start", sa.String(length=5), nullable=True))
        b.add_column(sa.Column("quiet_hours_end", sa.String(length=5), nullable=True))
        b.add_column(sa.Column("daily_cap", sa.Integer(), nullable=False, server_default="50"))
        b.add_column(sa.Column("escalation_rank", sa.Integer(), nullable=True))
        b.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
        )

    with op.batch_alter_table("events") as b:
        b.add_column(sa.Column("alert_id", sa.String(length=36), nullable=True))
        b.create_foreign_key(
            op.f("fk_events_alert_id_alerts"), "alerts", ["alert_id"], ["id"], ondelete="SET NULL"
        )
        b.create_index(op.f("ix_events_alert_id"), ["alert_id"])

    with op.batch_alter_table("notifications") as b:
        b.add_column(sa.Column("alert_id", sa.String(length=36), nullable=True))
        b.add_column(
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="alert")
        )
        b.add_column(sa.Column("reason", sa.String(length=64), nullable=True))
        b.create_foreign_key(
            op.f("fk_notifications_alert_id_alerts"),
            "alerts",
            ["alert_id"],
            ["id"],
            ondelete="CASCADE",
        )
        b.create_index(op.f("ix_notifications_alert_id"), ["alert_id"])

    if op.get_bind().dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {POLICY} ON {table} FOR ALL USING {_COND} WITH CHECK {_COND}"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    with op.batch_alter_table("notifications") as b:
        b.drop_index(op.f("ix_notifications_alert_id"))
        b.drop_constraint(op.f("fk_notifications_alert_id_alerts"), type_="foreignkey")
        b.drop_column("reason")
        b.drop_column("kind")
        b.drop_column("alert_id")
    with op.batch_alter_table("events") as b:
        b.drop_index(op.f("ix_events_alert_id"))
        b.drop_constraint(op.f("fk_events_alert_id_alerts"), type_="foreignkey")
        b.drop_column("alert_id")
    with op.batch_alter_table("recipients") as b:
        for col in (
            "updated_at",
            "escalation_rank",
            "daily_cap",
            "quiet_hours_end",
            "quiet_hours_start",
            "name_ar",
        ):
            b.drop_column(col)
    op.drop_index(op.f("ix_recipient_rules_rule_id"), table_name="recipient_rules")
    op.drop_index(op.f("ix_recipient_rules_organisation_id"), table_name="recipient_rules")
    op.drop_table("recipient_rules")
    op.drop_index(op.f("ix_alerts_site_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_organisation_id"), table_name="alerts")
    op.drop_index("ix_alerts_group", table_name="alerts")
    op.drop_table("alerts")
