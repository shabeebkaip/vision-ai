"""Fixtures for the cloud tests.

Every API test runs twice: on SQLite (always) and on PostgreSQL 16 (marker `postgres`) when
`VISION_CLOUD_TEST_POSTGRES_URL` points at a throwaway database, e.g.
    postgresql+psycopg://postgres:postgres@localhost:5432/vision_test
The PostgreSQL run applies the Alembic migrations (including row-level security) and connects the
API as a freshly created role without superuser or BYPASSRLS, so RLS is really enforced.
`.github/workflows/cloud.yml` sets VISION_CLOUD_REQUIRE_POSTGRES=1 so a missing server fails
instead of skipping.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, select, text

from vision_cloud.app import create_app
from vision_cloud.cli import alembic_config
from vision_cloud.db import Base, make_engine, system_session
from vision_cloud.jobs import InMemoryQueue
from vision_cloud.models import Notification, User
from vision_cloud.security import generate_field_key, hash_password
from vision_cloud.services import channels
from vision_cloud.services.channels import DryRunChannel
from vision_cloud.settings import CloudSettings
from vision_cloud.worker import HANDLERS, WorkerContext, _load_handlers

PG_URL = os.environ.get("VISION_CLOUD_TEST_POSTGRES_URL", "")
REQUIRE_PG = os.environ.get("VISION_CLOUD_REQUIRE_POSTGRES") == "1"
APP_ROLE = "vision_app_test"
PASSWORD = "correct-horse-battery-staple"  # test users only, never a real credential

BACKENDS = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param("postgres", id="postgres", marks=pytest.mark.postgres),
]


@dataclass
class PgDatabase:
    admin_url: str
    app_url: str


@pytest.fixture(scope="session")
def pg_database() -> Iterator[PgDatabase]:
    if not PG_URL:
        if REQUIRE_PG:
            pytest.fail(
                "VISION_CLOUD_TEST_POSTGRES_URL is required (VISION_CLOUD_REQUIRE_POSTGRES=1)"
            )
        pytest.skip("PostgreSQL tests need VISION_CLOUD_TEST_POSTGRES_URL")
    admin = create_engine(PG_URL, isolation_level="AUTOCOMMIT")
    role_password = secrets.token_urlsafe(16)
    with admin.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE})
        verb = "ALTER" if exists else "CREATE"
        conn.execute(
            text(f"{verb} ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{role_password}'")
        )
    command.upgrade(alembic_config(PG_URL), "head")
    with admin.connect() as conn:
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        conn.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
            )
        )
        # Like deploy/postgres-init: tables created later by migrations (including tests that
        # migrate down and up again) are granted to the API role too.
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
            )
        )
    app_url = make_url(PG_URL).set(username=APP_ROLE, password=role_password)
    yield PgDatabase(admin_url=PG_URL, app_url=app_url.render_as_string(hide_password=False))
    admin.dispose()


def _truncate_all(admin_url: str) -> None:
    engine = create_engine(admin_url)
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
    engine.dispose()


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def db_url(backend: str, tmp_path: Path, request: pytest.FixtureRequest) -> str:
    if backend == "postgres":
        pg: PgDatabase = request.getfixturevalue("pg_database")
        _truncate_all(pg.admin_url)
        return pg.app_url
    url = f"sqlite:///{tmp_path / 'cloud.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def settings(db_url: str, tmp_path: Path) -> CloudSettings:
    return CloudSettings(
        environment="test",
        database_url=db_url,
        jwt_secret=secrets.token_urlsafe(48),
        field_encryption_key=generate_field_key(),
        storage_backend="local",
        storage_local_dir=tmp_path / "storage",
        public_base_url="http://testserver",
        log_json=False,
        alert_media_wait_s=0,  # tests post events without snapshots; test_telegram covers waiting
    )


@pytest.fixture
def queue() -> InMemoryQueue:
    return InMemoryQueue()


@pytest.fixture
def app(settings: CloudSettings, queue: InMemoryQueue) -> Iterator[FastAPI]:
    application = create_app(settings, queue=queue)
    yield application
    application.state.vision.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- scenario helpers


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


def make_event(site_id: str, camera_id: str, rule_id: str = "rule-x", **kw: Any) -> dict[str, Any]:
    at = kw.pop("at", T0)
    body: dict[str, Any] = {
        "id": kw.pop("id", secrets.token_hex(8)),
        "site_id": site_id,
        "camera_id": camera_id,
        "rule_id": rule_id,
        "rule_type": "zone_occupancy_over",
        "severity": kw.pop("severity", "warning"),
        "condition_started_at": (at - timedelta(seconds=30)).isoformat(),
        "triggered_at": at.isoformat(),
        "value": 5,
        "message": "too many people",
    }
    body.update(kw)
    return body


@dataclass
class Tenant:
    """One organisation built through the API: owner, two sites, a camera per site, a rule,
    an enrolled device on site 1 and one event."""

    org_id: str
    owner_token: str
    site_ids: list[str]
    camera_ids: list[str]
    rule_id: str
    device_id: str
    device_token: str
    event_id: str
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class World:
    client: TestClient
    admin_token: str
    a: Tenant
    b: Tenant

    def login(self, email: str, password: str = PASSWORD, org: str | None = None) -> str:
        body: dict[str, Any] = {"email": email, "password": password}
        if org:
            body["organisation_id"] = org
        r = self.client.post("/api/v1/auth/login", json=body)
        assert r.status_code == 200, r.text
        return str(r.json()["access_token"])

    def invite(self, tenant: Tenant, email: str, role: str, site_ids: list[str]) -> str:
        r = self.client.post(
            "/api/v1/invitations",
            json={"email": email, "role": role, "site_ids": site_ids},
            headers=auth(tenant.owner_token),
        )
        assert r.status_code == 201, r.text
        r = self.client.post(
            "/api/v1/auth/accept-invitation",
            json={"token": r.json()["token"], "password": PASSWORD, "full_name": email},
        )
        assert r.status_code == 200, r.text
        return str(r.json()["access_token"])


def create_admin(app: FastAPI, email: str = "ops@codeox.test") -> None:
    with system_session(app.state.vision.sessions) as db:
        db.add(User(email=email, password_hash=hash_password(PASSWORD), is_platform_admin=True))
        db.commit()


def build_tenant(client: TestClient, admin_token: str, name: str) -> Tenant:
    r = client.post(
        "/api/v1/admin/organisations",
        json={"name": name, "owner_email": f"owner@{name.lower()}.test"},
        headers=auth(admin_token),
    )
    assert r.status_code == 201, r.text
    org_id = r.json()["organisation"]["id"]
    r = client.post(
        "/api/v1/auth/accept-invitation",
        json={"token": r.json()["owner_invitation"]["token"], "password": PASSWORD},
    )
    assert r.status_code == 200, r.text
    owner = auth(r.json()["access_token"])
    site_ids, camera_ids = [], []
    for i in (1, 2):
        r = client.post("/api/v1/sites", json={"name": f"{name} site {i}"}, headers=owner)
        assert r.status_code == 201, r.text
        site_ids.append(r.json()["id"])
        r = client.post(
            f"/api/v1/sites/{site_ids[-1]}/cameras",
            json={
                "name": f"{name} cam {i}",
                "source": f"rtsp://admin:secret{i}@10.0.0.{i}:554/Streaming/Channels/102",
                "zones": [
                    {"id": "desk", "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]]}
                ],
                "lines": [{"id": "door", "start": [0.1, 0.9], "end": [0.9, 0.9]}],
            },
            headers=owner,
        )
        assert r.status_code == 201, r.text
        camera_ids.append(r.json()["id"])
    r = client.post(
        "/api/v1/rules",
        json={
            "type": "zone_occupancy_over",
            "camera_id": camera_ids[0],
            "zone_id": "desk",
            "threshold": 3,
            "min_duration_s": 10,
            "name": "crowd",
        },
        headers=owner,
    )
    assert r.status_code == 201, r.text
    rule_id = r.json()["id"]
    r = client.post(f"/api/v1/sites/{site_ids[0]}/devices", json={"name": "box"}, headers=owner)
    assert r.status_code == 201, r.text
    device_id = r.json()["device"]["id"]
    r = client.post(
        "/device/v1/enrol",
        json={"enrolment_token": r.json()["enrolment_token"], "software_version": "0.1.0"},
    )
    assert r.status_code == 200, r.text
    device_token = r.json()["device_token"]
    event = make_event(site_ids[0], camera_ids[0], rule_id)
    r = client.post("/device/v1/events", json=event, headers=auth(device_token))
    assert r.status_code == 201, r.text
    return Tenant(
        org_id=org_id,
        owner_token=owner["Authorization"].split(" ", 1)[1],
        site_ids=site_ids,
        camera_ids=camera_ids,
        rule_id=rule_id,
        device_id=device_id,
        device_token=device_token,
        event_id=event["id"],
    )


def _bootstrap_admin_org(app: FastAPI) -> None:
    """Admins act inside an organisation; give them a 'Code-Ox' organisation to sign in to."""
    from vision_cloud.models import Membership, Organisation, Role

    with system_session(app.state.vision.sessions) as db:
        org = Organisation(name="Code-Ox")
        db.add(org)
        db.flush()
        admin = db.query(User).filter(User.email == "ops@codeox.test").one()
        db.add(Membership(organisation_id=org.id, user_id=admin.id, role=Role.OWNER.value))
        db.commit()


@pytest.fixture
def world(app: FastAPI, client: TestClient) -> World:
    create_admin(app)
    r = client.post("/api/v1/auth/login", json={"email": "ops@codeox.test", "password": PASSWORD})
    # A platform admin without memberships must name an organisation; none exists yet.
    assert r.status_code == 403, r.text
    _bootstrap_admin_org(app)
    r = client.post("/api/v1/auth/login", json={"email": "ops@codeox.test", "password": PASSWORD})
    assert r.status_code == 200, r.text
    admin_token = r.json()["access_token"]
    return World(
        client=client,
        admin_token=admin_token,
        a=build_tenant(client, admin_token, "Alpha"),
        b=build_tenant(client, admin_token, "Bravo"),
    )


# --------------------------------------------------------------------------- alerting (CLD-08)


@pytest.fixture
def ctx(app: FastAPI, queue: InMemoryQueue) -> Iterator[WorkerContext]:
    """A worker context on the test app's database, with a fresh dry-run channel that records
    what people would have received."""
    _load_handlers()
    st = app.state.vision
    original = channels._dry_run
    channels._dry_run = DryRunChannel()
    yield WorkerContext(st.settings, st.sessions, st.storage, queue, st.cipher)
    channels._dry_run = original


@pytest.fixture
def clean_queue(queue: InMemoryQueue, world: World, ctx: WorkerContext) -> InMemoryQueue:
    """The world's queue after its own setup event was dispatched and forgotten."""
    while queue.jobs:
        name, payload = queue.jobs.pop(0)
        HANDLERS[name](ctx, payload)
    queue.delayed.clear()
    channels._dry_run.sent.clear()
    with system_session(ctx.sessions) as db:
        for n in db.scalars(select(Notification)).all():
            db.delete(n)
        db.commit()
    return queue
