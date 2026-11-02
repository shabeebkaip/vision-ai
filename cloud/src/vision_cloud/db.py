"""Database plumbing: declarative base, portable column types and tenant-scoped sessions (CLD-02).

Tenant isolation has two locks:

1. **Query layer.** A session opened with `tenant_session(org_id)` adds
   `organisation_id = :org` to every ORM SELECT/UPDATE/DELETE that touches a `TenantMixin` table
   (`with_loader_criteria`), including relationship loads. A session with no organisation and no
   explicit bypass matches nothing (fail closed).
2. **PostgreSQL row-level security.** At the start of every transaction the session sets the
   transaction-local settings `app.current_org` / `app.bypass_rls`; the policies created by
   migration 0002 compare `organisation_id` against them. The API role must not be a superuser and
   must not have BYPASSRLS, otherwise PostgreSQL skips the policies.

`system_session()` is the only way to read across organisations (login, device lookup by
credential, invitation acceptance, platform-admin tasks). Keep its uses few and obvious.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    ForeignKey,
    MetaData,
    String,
    create_engine,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    ORMExecuteState,
    Session,
    SessionTransaction,
    mapped_column,
    sessionmaker,
    with_loader_criteria,
)
from sqlalchemy.types import TypeDecorator

ORG_KEY = "vision_org_id"
BYPASS_KEY = "vision_bypass_rls"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend. Naive datetimes are refused on write;
    SQLite (which drops the offset) gets UTC re-attached on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime refused: use timezone-aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


JSONType = JSON().with_variant(JSONB(), "postgresql")


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: UTCDateTime()}


class TenantMixin:
    """Every customer-owned table: filtered by the session's organisation and protected by RLS."""

    organisation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="CASCADE"), index=True
    )


class TenantSession(Session):
    """Session class that carries the tenant context in `info`."""


@event.listens_for(TenantSession, "do_orm_execute")
def _add_tenant_criteria(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.session.info.get(BYPASS_KEY):
        return
    org = state.session.info.get(ORG_KEY) or ""  # no context: match nothing
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.organisation_id == org,
            include_aliases=True,
        )
    )


@event.listens_for(TenantSession, "after_begin")
def _set_rls_settings(session: Session, transaction: SessionTransaction, conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.execute(
        text(
            "SELECT set_config('app.current_org', :org, true), "
            "set_config('app.bypass_rls', :bypass, true)"
        ),
        {
            "org": session.info.get(ORG_KEY) or "",
            "bypass": "on" if session.info.get(BYPASS_KEY) else "off",
        },
    )


def make_engine(url: str, echo: bool = False) -> Engine:
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[TenantSession]:
    return sessionmaker(engine, class_=TenantSession, expire_on_commit=False)


@contextmanager
def tenant_session(factory: sessionmaker[TenantSession], org_id: str) -> Iterator[TenantSession]:
    if not org_id:
        raise ValueError("tenant session needs an organisation id")
    with factory() as session:
        session.info[ORG_KEY] = org_id
        yield session


@contextmanager
def system_session(factory: sessionmaker[TenantSession]) -> Iterator[TenantSession]:
    with factory() as session:
        session.info[BYPASS_KEY] = True
        yield session
