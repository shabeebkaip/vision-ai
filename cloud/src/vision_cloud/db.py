"""Engine, sessions and the tenant context that row-level security reads.

Every transaction starts by copying the session's tenant context into three transaction-local
PostgreSQL settings (`app.org_id`, `app.user_id`, `app.bypass_rls`). The RLS policies created in the
initial migration compare each row's `organisation_id` with `app.org_id`, so even a query that forgets
its `WHERE organisation_id = ...` cannot return another organisation's rows.

`bypass_rls` is only set by `system_session()`, used for the few lookups that must cross tenants
before we know the tenant: credential and token lookups, enrolment, seeding, Code-Ox admin.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

log = structlog.get_logger(__name__)

_CONTEXT_KEY = "tenant_context"
_SET_SQL = text(
    "SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :usr, true), "
    "set_config('app.bypass_rls', :bypass, true)"
)


@dataclass(frozen=True)
class TenantContext:
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    bypass_rls: bool = False

    def params(self) -> dict[str, str]:
        return {
            "org": str(self.org_id) if self.org_id else "",
            "usr": str(self.user_id) if self.user_id else "",
            "bypass": "on" if self.bypass_rls else "off",
        }


def make_engine(url: str, **kwargs: Any) -> Engine:
    return create_engine(url, pool_pre_ping=True, **kwargs)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _apply_context(session: Session, transaction: SessionTransaction, connection: Any) -> None:
    ctx: TenantContext = session.info.get(_CONTEXT_KEY, TenantContext())
    connection.execute(_SET_SQL, ctx.params())


def set_context(
    session: Session,
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    bypass_rls: bool = False,
) -> None:
    """Set the tenant context for this session (applies now and to every later transaction)."""
    ctx = TenantContext(org_id=org_id, user_id=user_id, bypass_rls=bypass_rls)
    session.info[_CONTEXT_KEY] = ctx
    if session.in_transaction():
        session.execute(_SET_SQL, ctx.params())


def get_context(session: Session) -> TenantContext:
    ctx: TenantContext = session.info.get(_CONTEXT_KEY, TenantContext())
    return ctx


@contextmanager
def system_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session that sees every tenant. Keep its use narrow and named."""
    with factory() as session:
        set_context(session, bypass_rls=True)
        yield session


def check_role_is_not_privileged(engine: Engine, strict: bool) -> None:
    """Superusers and BYPASSRLS roles ignore row-level security: refuse them outside dev."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
    if row.rolsuper or row.rolbypassrls:
        msg = (
            "database role is a superuser or has BYPASSRLS: row-level security is not enforced. "
            "Connect the API with an ordinary role (see cloud/README.md)."
        )
        if strict:
            raise SystemExit(msg)
        log.warning("db.rls_not_enforced", detail=msg)
