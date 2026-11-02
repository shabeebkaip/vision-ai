"""PostgreSQL row-level security on every customer-owned table (CLD-02, second lock)

Each tenant table gets RLS enabled *and forced* (so the table owner is filtered too) and one policy
for all commands:

    organisation_id = current_setting('app.current_org', true)
    OR current_setting('app.bypass_rls', true) = 'on'

The API sets both settings transaction-locally at the start of every transaction
(`vision_cloud.db`). With no setting, `current_setting(..., true)` is NULL and no row matches.
Superusers and roles with BYPASSRLS skip all policies: the API must connect as a plain role.

The table list is frozen here on purpose; `test_rls_covers_every_tenant_table` fails when a new
tenant table is added without a migration that protects it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT_TABLES = (
    "aggregates_minute",
    "audit_log",
    "cameras",
    "config_versions",
    "devices",
    "event_feedback",
    "events",
    "invitations",
    "lines",
    "membership_sites",
    "memberships",
    "notifications",
    "recipients",
    "refresh_tokens",
    "rules",
    "sites",
    "zones",
)
_BYPASS = "current_setting('app.bypass_rls', true) = 'on'"


def _condition(column: str) -> str:
    return f"({column} = current_setting('app.current_org', true) OR {_BYPASS})"


def _protect(table: str, column: str) -> None:
    cond = _condition(column)
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} FOR ALL USING {cond} WITH CHECK {cond}")


def _unprotect(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite (tests, local experiments) has no RLS; the query layer still filters
    for table in TENANT_TABLES:
        _protect(table, "organisation_id")
    _protect("organisations", "id")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _unprotect("organisations")
    for table in TENANT_TABLES:
        _unprotect(table)
