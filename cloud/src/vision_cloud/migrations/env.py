"""Alembic environment. The database URL comes from `-x url=...`, the Alembic config
(`sqlalchemy.url`, set by `vision-cloud migrate`) or `VISION_CLOUD_DATABASE_URL`."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

import vision_cloud.models  # noqa: F401  (registers the tables)
from vision_cloud.db import Base

config = context.config
target_metadata = Base.metadata

DEFAULT_URL = "postgresql+psycopg://vision:vision@localhost:5432/vision"


def _url() -> str:
    return (
        context.get_x_argument(as_dictionary=True).get("url")
        or config.get_main_option("sqlalchemy.url")
        or os.environ.get("VISION_CLOUD_DATABASE_URL")
        or DEFAULT_URL
    )


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            render_as_batch=conn.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
