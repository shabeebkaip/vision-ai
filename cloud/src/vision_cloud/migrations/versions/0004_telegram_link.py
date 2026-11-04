"""Telegram link codes on recipients (CLD-10)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES: tuple[str, ...] = ()  # no new tables


def upgrade() -> None:
    with op.batch_alter_table("recipients") as b:
        b.add_column(sa.Column("telegram_link_code_hash", sa.String(length=64), nullable=True))
        b.add_column(
            sa.Column("telegram_link_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        b.create_unique_constraint(
            op.f("uq_recipients_telegram_link_code_hash"), ["telegram_link_code_hash"]
        )


def downgrade() -> None:
    with op.batch_alter_table("recipients") as b:
        b.drop_constraint(op.f("uq_recipients_telegram_link_code_hash"), type_="unique")
        b.drop_column("telegram_link_expires_at")
        b.drop_column("telegram_link_code_hash")
