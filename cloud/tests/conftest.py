"""Cloud tests run against a real PostgreSQL 16 (row-level security cannot be faked).

Set VISION_TEST_DATABASE_URL to a server where the role may CREATE DATABASE, e.g.
    postgresql+psycopg://vision:vision@localhost:5432/postgres
Each test session creates a throw-away database, migrates it with Alembic and drops it at the end.
Tests are skipped when no server is reachable. The role must NOT be a superuser (RLS is tested).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("VISION_JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("VISION_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("VISION_STORAGE_BACKEND", "memory")
os.environ.setdefault("VISION_MAIL_BACKEND", "memory")
os.environ.setdefault("VISION_ENVIRONMENT", "test")
os.environ.pop("VISION_REDIS_URL", None)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://vision:vision@localhost:5432/postgres"
ADMIN_URL = os.environ.get("VISION_TEST_DATABASE_URL", DEFAULT_URL)


def _server_available() -> str | None:
    try:
        engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            ).one()
        engine.dispose()
    except Exception as exc:
        return f"no PostgreSQL for tests at {make_url(ADMIN_URL).render_as_string()}: {exc}"
    if row.rolsuper or row.rolbypassrls:
        return "test role must not be a superuser or BYPASSRLS (row-level security is under test)"
    return None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    problem = _server_available()
    if problem:
        pytest.skip(problem)
    name = f"vision_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    os.environ["VISION_DATABASE_URL"] = url
    from vision_cloud.cli import migrate
    from vision_cloud.settings import get_settings

    get_settings.cache_clear()
    migrate("head", url=url)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def app_and_parts(database_url: str) -> Iterator[Any]:
    from vision_cloud.app import create_app
    from vision_cloud.mailer import MemoryMailer
    from vision_cloud.ratelimit import MemoryRateLimiter
    from vision_cloud.settings import get_settings
    from vision_cloud.storage import MemoryStore

    store, mailer = MemoryStore(), MemoryMailer()
    app = create_app(get_settings(), store=store, mailer=mailer, limiter=MemoryRateLimiter())
    yield app, store, mailer


@pytest.fixture()
def app(app_and_parts: Any) -> Any:
    from vision_cloud.ratelimit import MemoryRateLimiter

    application, store, mailer = app_and_parts
    store.objects.clear()
    mailer.outbox.clear()
    application.state.limiter = MemoryRateLimiter()
    return application


@pytest.fixture()
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sessions(app: Any) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = app.state.sessionmaker
    return factory


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "database_url" not in request.fixturenames:
        return
    url = request.getfixturevalue("database_url")
    engine = create_engine(url)
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    engine.dispose()


# --------------------------------------------------------------------------- builders


PASSWORD = "correct horse battery"


@dataclass
class Tenant:
    org_id: uuid.UUID
    site_id: uuid.UUID
    site_key: str
    camera_id: uuid.UUID
    owner_id: uuid.UUID
    owner_email: str


def make_tenant(sessions: sessionmaker[Session], slug: str) -> Tenant:
    from vision_cloud import models as m
    from vision_cloud.db import system_session
    from vision_cloud.security import hash_password
    from vision_cloud.seed import DEMO_SITE
    from vision_cloud.siteconfig import import_site_config
    from vision_shared.schemas import SiteConfig

    with system_session(sessions) as db:
        org = m.Organisation(name=f"Org {slug}", slug=slug, language=m.Language.EN)
        db.add(org)
        db.flush()
        owner = m.User(
            email=f"owner@{slug}.test", name=f"Owner {slug}", password_hash=hash_password(PASSWORD)
        )
        db.add(owner)
        db.flush()
        db.add(m.Membership(organisation_id=org.id, user_id=owner.id, role=m.Role.OWNER))
        site = import_site_config(db, org.id, SiteConfig.model_validate(DEMO_SITE))
        cam = db.query(m.Camera).filter(m.Camera.site_id == site.id).one()
        db.commit()
        return Tenant(org.id, site.id, site.key, cam.id, owner.id, owner.email)


def add_user(
    sessions: sessionmaker[Session],
    tenant: Tenant,
    email: str,
    role: str,
    site_ids: list[uuid.UUID] | None = None,
    platform_admin: bool = False,
) -> uuid.UUID:
    from vision_cloud import models as m
    from vision_cloud.db import system_session
    from vision_cloud.security import hash_password

    with system_session(sessions) as db:
        user = m.User(
            email=email, password_hash=hash_password(PASSWORD), is_platform_admin=platform_admin
        )
        db.add(user)
        db.flush()
        if role:
            ms = m.Membership(
                organisation_id=tenant.org_id,
                user_id=user.id,
                role=m.Role(role),
                all_sites=not site_ids,
            )
            db.add(ms)
            db.flush()
            for sid in site_ids or []:
                db.add(
                    m.MembershipSite(
                        membership_id=ms.id, site_id=sid, organisation_id=tenant.org_id
                    )
                )
        db.commit()
        return user.id


def login(client: TestClient, email: str, password: str = PASSWORD, **extra: Any) -> dict[str, Any]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


def auth(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def enrol_device(client: TestClient, sessions: sessionmaker[Session], tenant: Tenant) -> str:
    """Enrol an edge box for the tenant's site; returns its bearer credential."""
    from datetime import datetime, timedelta, timezone

    from vision_cloud import crypto
    from vision_cloud import models as m
    from vision_cloud.db import system_session

    token = "enr_" + crypto.new_token()
    with system_session(sessions) as db:
        db.add(
            m.EnrolmentToken(
                organisation_id=tenant.org_id,
                site_id=tenant.site_id,
                token_hash=crypto.hash_token(token),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        db.commit()
    r = client.post("/device/v1/enrol", json={"token": token, "name": "box"})
    assert r.status_code == 201, r.text
    credential: str = r.json()["credential"]
    return credential
