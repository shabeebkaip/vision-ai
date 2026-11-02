"""`vision-cloud` command: serve, migrate, seed, create-admin, enrolment-token, gen-key."""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path

from sqlalchemy import func, select


def _alembic_config(url: str | None = None) -> object:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(files("vision_cloud").joinpath("migrations")))
    cfg.attributes["configure_logger"] = False
    if url:
        cfg.attributes["url"] = url
    return cfg


def migrate(revision: str = "head", url: str | None = None) -> None:
    from alembic import command

    command.upgrade(_alembic_config(url), revision)  # type: ignore[arg-type]


def _sessions() -> object:
    from vision_cloud.db import make_engine, make_sessionmaker
    from vision_cloud.settings import get_settings

    return make_sessionmaker(make_engine(get_settings().database_url))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vision-cloud", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="run the API with uvicorn")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--workers", type=int, default=1)
    serve.add_argument("--reload", action="store_true")

    mig = sub.add_parser("migrate", help="alembic upgrade (default: head)")
    mig.add_argument("revision", nargs="?", default="head")

    seed = sub.add_parser("seed", help="load the demo organisation")
    seed.add_argument("--owner-email", default="demo-owner@code-ox.com")
    seed.add_argument("--site-yaml", type=Path, default=None)

    admin = sub.add_parser("create-admin", help="create or promote a Code-Ox admin user")
    admin.add_argument("email")

    tok = sub.add_parser("enrolment-token", help="one-time token to enrol an edge box")
    tok.add_argument("site_id", type=uuid.UUID)
    tok.add_argument("--name", default="")
    tok.add_argument("--hours", type=float, default=24)

    sub.add_parser("gen-key", help="print a new VISION_ENCRYPTION_KEY")

    args = p.parse_args(argv)

    if args.cmd == "gen-key":
        from vision_cloud.crypto import generate_key

        print(generate_key())
        return 0

    if args.cmd == "serve":
        import uvicorn

        from vision_cloud.settings import get_settings

        get_settings()  # fail fast with a readable message
        uvicorn.run(
            "vision_cloud.main:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            reload=args.reload,
            proxy_headers=True,
        )
        return 0

    if args.cmd == "migrate":
        migrate(args.revision)
        print(f"database at {args.revision}")
        return 0

    from vision_cloud import crypto
    from vision_cloud import models as m
    from vision_cloud.db import system_session
    from vision_cloud.security import hash_password, password_problem

    sessions = _sessions()

    if args.cmd == "seed":
        import os

        from vision_cloud.seed import seed_demo

        result = seed_demo(
            sessions,  # type: ignore[arg-type]
            owner_email=args.owner_email,
            owner_password=os.environ.get("VISION_SEED_OWNER_PASSWORD"),
            site_yaml=args.site_yaml,
        )
        state = "created" if result.created else "already present"
        print(f"demo organisation {state}: {result.organisation_id}")
        print(f"site: {result.site_id}")
        print(f"owner: {result.owner_email}")
        if result.owner_password:
            print(f"owner password (shown once): {result.owner_password}")
        return 0

    if args.cmd == "create-admin":
        with system_session(sessions) as db:  # type: ignore[arg-type]
            user = db.scalars(
                select(m.User).where(func.lower(m.User.email) == args.email.lower())
            ).first()
            if user is None:
                password = getpass.getpass("password for the new admin: ")
                problem = password_problem(password)
                if problem:
                    print(problem, file=sys.stderr)
                    return 2
                user = m.User(
                    email=args.email.lower(), name="", password_hash=hash_password(password)
                )
                db.add(user)
            user.is_platform_admin = True
            db.commit()
        print(f"{args.email} is a Code-Ox admin")
        return 0

    if args.cmd == "enrolment-token":
        token = "enr_" + crypto.new_token()
        with system_session(sessions) as db:  # type: ignore[arg-type]
            site = db.get(m.Site, args.site_id)
            if site is None:
                print("no such site", file=sys.stderr)
                return 2
            db.add(
                m.EnrolmentToken(
                    organisation_id=site.organisation_id,
                    site_id=site.id,
                    device_name=args.name,
                    token_hash=crypto.hash_token(token),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=args.hours),
                )
            )
            db.commit()
        print(token)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
