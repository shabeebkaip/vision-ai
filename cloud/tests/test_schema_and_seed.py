"""CLD-01: `alembic upgrade head` builds the schema; the seed loads; config round-trips."""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from vision_cloud import models as m
from vision_cloud.db import system_session
from vision_cloud.seed import DEMO_SITE, seed_demo
from vision_cloud.siteconfig import build_site_config, current_config
from vision_shared.schemas import SiteConfig


def test_migration_matches_models(database_url: str) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = create_engine(database_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), m.Base.metadata)
        tables = set(inspect(conn).get_table_names())
    engine.dispose()
    assert diff == [], f"models and migrations differ: {diff}"
    expected = {t.name for t in m.Base.metadata.sorted_tables}
    assert expected <= tables


def test_every_customer_table_has_forced_rls(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace"
            )
        ).all()
    engine.dispose()
    state = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in rows}
    for table in (*m.TENANT_TABLES, *m.USER_TABLES, "organisations", "users"):
        assert state[table] == (True, True), table
    # Every table with an organisation_id column is in the tenant list.
    with_org = {t.name for t in m.Base.metadata.sorted_tables if "organisation_id" in t.c}
    assert with_org == set(m.TENANT_TABLES)


def test_seed_loads_once(sessions: sessionmaker[Session]) -> None:
    first = seed_demo(sessions, owner_password="a-long-demo-password")
    second = seed_demo(sessions)
    assert first.created and not second.created
    assert first.organisation_id == second.organisation_id
    with system_session(sessions) as db:
        assert db.query(m.Organisation).count() == 1
        assert db.query(m.Rule).count() == 2
        site = db.query(m.Site).one()
        built = build_site_config(db, site)
    expected = SiteConfig.model_validate(DEMO_SITE)
    expected.rules.sort(key=lambda r: r.id)  # the cloud serves rules in id order
    assert built.model_dump() == expected.model_dump()


def test_stream_url_is_encrypted_at_rest(sessions: sessionmaker[Session]) -> None:
    seed_demo(sessions, owner_password="a-long-demo-password")
    with system_session(sessions) as db:
        raw = db.execute(text("SELECT stream_url FROM cameras")).scalar_one()
        cam = db.query(m.Camera).one()
    assert "rtsp://" not in raw
    assert cam.stream_url.startswith("rtsp://")


def test_config_version_only_moves_on_change(sessions: sessionmaker[Session]) -> None:
    seed_demo(sessions, owner_password="a-long-demo-password")
    with system_session(sessions) as db:
        site = db.query(m.Site).one()
        _, v1 = current_config(db, site)
        _, v2 = current_config(db, site)
        assert (v1.version, v2.version) == (1, 1)
        rule = db.query(m.Rule).filter(m.Rule.key == "queue").one()
        rule.threshold = 6
        db.flush()
        cfg3, v3 = current_config(db, site)
        db.commit()
    assert v3.version == 2 and cfg3.version == 2
    stored: dict[str, Any] = v3.config
    assert stored["cameras"][0]["source"] == "***"  # stream credentials are not kept in history
    assert next(r for r in cfg3.rules if r.id == "queue").threshold == 6
