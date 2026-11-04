"""Error format and request ids (CLD-19), storage backends (CLD-06), migrations and seed (CLD-01)."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from vision_cloud.cli import alembic_config, main
from vision_cloud.db import Base, make_engine, make_session_factory, system_session
from vision_cloud.models import Organisation, tenant_tables
from vision_cloud.security import FieldCipher, generate_field_key
from vision_cloud.services.config import build_site_config, redact_url
from vision_cloud.services.seed import seed_demo
from vision_cloud.storage import LocalStorage, S3Storage, event_media_key
from vision_shared.io import load_site

from .conftest import PASSWORD, PgDatabase

REPO = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- errors


def test_error_format_and_request_id(client: TestClient) -> None:
    r = client.get("/api/v1/sites", headers={"X-Request-ID": "req-12345678"})
    assert r.status_code == 401
    assert r.headers["X-Request-ID"] == "req-12345678"
    err = r.json()["error"]
    assert err["code"] == "unauthorized" and err["request_id"] == "req-12345678"

    r = client.get("/no/such/path")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    rid = r.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", rid) and r.json()["error"]["request_id"] == rid

    r = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and err["details"][0]["loc"][-1] == "email"

    # A hostile request id is replaced.
    r = client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert r.status_code == 200 and r.headers["X-Request-ID"] != "bad id\nwith newline"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


# --------------------------------------------------------------------------- storage


def test_media_key_layout() -> None:
    from datetime import datetime, timezone

    at = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)
    assert event_media_key("o", "s", "c", at, "e", "clip") == "o/s/c/2026/11/01/e/clip.mp4"
    with pytest.raises(ValueError):
        event_media_key("o", "s", "c", at.replace(tzinfo=None), "e", "clip")


def test_s3_presigned_urls_are_signed() -> None:
    storage = S3Storage(
        "vision-media",
        endpoint_url="http://minio.local:9000",
        access_key="AKIAEXAMPLE",
        secret_key="example-secret-key",
        sse="AES256",
    )
    put = storage.presign_put("o/s/c/2026/11/01/e/snapshot.jpg", "image/jpeg", 900)
    assert put.url.startswith("http://minio.local:9000/vision-media/o/s/c/2026/11/01/e/")
    assert "X-Amz-Signature=" in put.url and "X-Amz-Expires=900" in put.url
    assert put.headers["x-amz-server-side-encryption"] == "AES256"
    get = storage.presign_get("o/s/c/2026/11/01/e/snapshot.jpg", 300)
    assert "X-Amz-Expires=300" in get.url and get.method == "GET"
    # Inside docker compose the API talks to minio:9000 but hands out localhost:9000 URLs.
    split = S3Storage(
        "vision-media",
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://localhost:9000",
        access_key="AKIAEXAMPLE",
        secret_key="example-secret-key",
    )
    assert split.presign_get("k", 60).url.startswith("http://localhost:9000/vision-media/k?")


def test_local_storage_signatures(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, "http://x", "key")
    signed = storage.presign_get("a/b.jpg", 60)
    query = dict(p.split("=") for p in signed.url.split("?")[1].split("&"))
    assert storage.verify("GET", "a/b.jpg", query["expires"], query["signature"])
    assert not storage.verify("PUT", "a/b.jpg", query["expires"], query["signature"])
    assert not storage.verify("GET", "a/c.jpg", query["expires"], query["signature"])
    past = str(int(time.time()) - 1)
    assert not storage.verify("GET", "a/b.jpg", past, query["signature"])
    with pytest.raises(ValueError):
        storage.path_for("../outside.jpg")


def test_redact_url() -> None:
    assert redact_url("rtsp://u:p@host:554/x") == "rtsp://***@host:554/x"
    assert redact_url("rtsp://host/x") == "rtsp://host/x"
    assert redact_url("/videos/a.mp4") == "/videos/a.mp4"


# --------------------------------------------------------------------------- migrations


def _migration_diff(url: str) -> list[object]:
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    return list(diff)


def test_sqlite_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(alembic_config(url), "head")
    assert _migration_diff(url) == []
    command.downgrade(alembic_config(url), "base")
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_rls_covers_every_tenant_table() -> None:
    import importlib

    protected: set[str] = set()
    for name in ("0002_row_level_security", "0003_alerts_and_recipients"):
        protected |= set(
            importlib.import_module(f"vision_cloud.migrations.versions.{name}").TENANT_TABLES
        )
    assert sorted(protected) == tenant_tables()
    assert {"events", "sites", "alerts", "recipient_rules"} <= protected


@pytest.mark.postgres
def test_postgres_migrations_and_rls_catalogue(pg_database: PgDatabase) -> None:
    """Migrations ran in the session fixture (upgrade head); they must match the models and
    every tenant table must have RLS enabled, forced and a policy."""
    assert _migration_diff(pg_database.admin_url) == []
    engine = create_engine(pg_database.admin_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        ).all()
        role = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'vision_app_test'")
        ).one()
    engine.dispose()
    status = {r[0]: (r[1], r[2], r[3]) for r in rows}
    for table in [*tenant_tables(), "organisations"]:
        assert status[table] == (True, True, 1), table
    assert status["users"][0] is False  # users span organisations
    assert tuple(role) == (False, False)  # the API test role cannot skip RLS


@pytest.mark.postgres
def test_postgres_downgrade_and_upgrade_again(pg_database: PgDatabase) -> None:
    cfg = alembic_config(pg_database.admin_url)
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")
    engine = create_engine(pg_database.admin_url)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM pg_policies")).scalar_one()
    engine.dispose()
    assert n == len(tenant_tables()) + 1


# --------------------------------------------------------------------------- seed and CLI


def test_cli_migrate_and_seed_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path / 'seed.db'}"
    monkeypatch.setenv("VISION_CLOUD_DATABASE_URL", url)
    monkeypatch.setenv("VISION_CLOUD_JWT_SECRET", "x" * 48)
    key = generate_field_key()
    monkeypatch.setenv("VISION_CLOUD_FIELD_ENCRYPTION_KEY", key)
    monkeypatch.setenv("VISION_CLOUD_SEED_PASSWORD", PASSWORD)
    assert main(["migrate"]) == 0
    site_yaml = REPO / "examples" / "synthetic-restaurant" / "site.yaml"
    assert main(["seed-demo", "--owner-email", "demo@codeox.test", "--site", str(site_yaml)]) == 0
    engine = make_engine(url)
    with system_session(make_session_factory(engine)) as db:
        assert db.scalar(select(Organisation.name)) == "Demo organisation"
        from vision_cloud.models import Site

        site = db.scalars(select(Site)).one()
        config = build_site_config(db, site, FieldCipher(key))
    engine.dispose()
    original = load_site(site_yaml)
    assert len(config.cameras) == len(original.cameras)
    assert [r.type for r in config.rules] == [r.type for r in original.rules]
    assert config.cameras[0].zones == original.cameras[0].zones
    with pytest.raises(SystemExit):  # the seed runs once
        main(["seed-demo", "--owner-email", "demo@codeox.test", "--site", str(site_yaml)])


def test_seed_demo_function(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 's.db'}")
    Base.metadata.create_all(engine)
    cipher = FieldCipher(generate_field_key())
    with system_session(make_session_factory(engine)) as db:
        seeded = seed_demo(
            db,
            cipher,
            owner_email="Owner@Demo.test",
            owner_password=PASSWORD,
            config=load_site(REPO / "examples" / "office-hikvision" / "site.yaml"),
        )
        db.commit()
    engine.dispose()
    assert seeded.owner_email == "owner@demo.test"
    assert seeded.enrolment_token.startswith("cxe_")
