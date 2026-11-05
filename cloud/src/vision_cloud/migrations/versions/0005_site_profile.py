"""Site profile for the dashboard: Arabic name, industry, city (CLD-07)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES: tuple[str, ...] = ()  # no new tables


def upgrade() -> None:
    with op.batch_alter_table("sites") as b:
        b.add_column(sa.Column("name_ar", sa.String(length=200), nullable=False, server_default=""))
        b.add_column(
            sa.Column("industry", sa.String(length=32), nullable=False, server_default="other")
        )
        b.add_column(sa.Column("city", sa.String(length=100), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("sites") as b:
        b.drop_column("city")
        b.drop_column("industry")
        b.drop_column("name_ar")
