"""`vision-cloud` command line.

vision-cloud migrate                         # alembic upgrade head (VISION_CLOUD_DATABASE_URL)
vision-cloud seed-demo --owner-email a@b.c   # demo organisation from examples/synthetic-restaurant
vision-cloud create-admin --email ops@code-ox.com
vision-cloud serve --port 8000
vision-cloud gen-keys                        # print fresh JWT and field-encryption keys
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from vision_cloud.db import make_engine, make_session_factory, system_session
from vision_cloud.models import User
from vision_cloud.security import (
    FieldCipher,
    check_password_strength,
    generate_field_key,
    hash_password,
)
from vision_cloud.settings import CloudSettings

DEFAULT_DEMO_SITE = Path("examples/synthetic-restaurant/site.yaml")


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "vision_cloud:migrations")
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def _database_url() -> str:
    return (
        os.environ.get("VISION_CLOUD_DATABASE_URL")
        or CloudSettings.model_fields["database_url"].get_default()
    )


def cmd_migrate(args: argparse.Namespace) -> int:
    command.upgrade(alembic_config(_database_url()), args.revision)
    print(f"database at revision {args.revision}")
    return 0


def _password(env_name: str) -> str:
    password = os.environ.get(env_name)
    if not password:
        password = getpass.getpass("Password: ")
    try:
        check_password_strength(password)
    except ValueError as exc:
        sys.exit(str(exc))
    return password


def cmd_create_admin(args: argparse.Namespace) -> int:
    engine = make_engine(_database_url())
    with system_session(make_session_factory(engine)) as db:
        email = args.email.strip().lower()
        if db.scalar(select(User).where(User.email == email)) is not None:
            sys.exit(f"user {email} already exists")
        password = _password("VISION_CLOUD_ADMIN_PASSWORD")
        db.add(User(email=email, password_hash=hash_password(password), is_platform_admin=True))
        db.commit()
    print(f"Code-Ox admin {email} created")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    from vision_cloud.services.seed import seed_demo
    from vision_shared.io import load_site

    settings = CloudSettings()  # values from environment
    config = load_site(args.site)
    engine = make_engine(settings.database_url)
    with system_session(make_session_factory(engine)) as db:
        if db.scalar(select(User).where(User.email == args.owner_email.lower())) is not None:
            sys.exit(f"user {args.owner_email} already exists; the demo seed runs once")
        seeded = seed_demo(
            db,
            FieldCipher(settings.field_encryption_key.get_secret_value()),
            owner_email=args.owner_email,
            owner_password=_password("VISION_CLOUD_SEED_PASSWORD"),
            config=config,
            organisation_name=args.name,
        )
        db.commit()
    print(f"organisation   {seeded.organisation_id}")
    print(f"site           {seeded.site_id}")
    print(f"owner          {seeded.owner_email}")
    print(f"device         {seeded.device_id}")
    print(f"enrolment token (one-time, 24 h): {seeded.enrolment_token}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "vision_cloud.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=True,
    )
    return 0


def cmd_gen_keys(_args: argparse.Namespace) -> int:
    print(f"VISION_CLOUD_JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"VISION_CLOUD_FIELD_ENCRYPTION_KEY={generate_field_key()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vision-cloud", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("migrate", help="apply database migrations")
    p.add_argument("--revision", default="head")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("create-admin", help="create a Code-Ox platform admin user")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("seed-demo", help="seed one demo organisation")
    p.add_argument("--owner-email", required=True)
    p.add_argument("--site", type=Path, default=DEFAULT_DEMO_SITE, help="site YAML to import")
    p.add_argument("--name", default="Demo organisation")
    p.set_defaults(func=cmd_seed_demo)

    p = sub.add_parser("serve", help="run the API with uvicorn")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("gen-keys", help="print fresh secret keys for .env")
    p.set_defaults(func=cmd_gen_keys)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
