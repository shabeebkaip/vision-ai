"""Seed data: one demo organisation (CLD-01).

Creates the "Code-Ox Demo" organisation, an owner account, and a site imported from a SiteConfig
YAML (default: the built-in demo restaurant, the same layout as examples/synthetic-restaurant).
Running it twice changes nothing.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from vision_cloud import models as m
from vision_cloud.db import system_session
from vision_cloud.security import hash_password
from vision_cloud.siteconfig import import_site_config
from vision_shared.io import load_site
from vision_shared.schemas import SiteConfig

DEMO_ORG_SLUG = "codeox-demo"

DEMO_SITE = {
    "id": "demo-restaurant",
    "name": "Demo restaurant",
    "timezone": "Asia/Riyadh",
    "cameras": [
        {
            "id": "counter",
            "name": "Counter camera",
            "source": "rtsp://mediamtx:8554/counter",
            "fps": 5,
            "zones": [
                {
                    "id": "counter_queue",
                    "name": "Counter queue",
                    "polygon": [[0.30, 0.55], [0.70, 0.55], [0.70, 0.95], [0.30, 0.95]],
                }
            ],
            "lines": [
                {"id": "door", "name": "Front door", "start": [0.05, 0.40], "end": [0.05, 0.90]}
            ],
        }
    ],
    "rules": [
        {
            "id": "queue",
            "name": "Queue too long",
            "type": "queue_length_over",
            "camera_id": "counter",
            "zone_id": "counter_queue",
            "threshold": 4,
            "min_duration_s": 20,
            "cooldown_s": 600,
            "severity": "warning",
        },
        {
            "id": "counter_unattended",
            "name": "Counter unattended",
            "type": "zone_empty",
            "camera_id": "counter",
            "zone_id": "counter_queue",
            "min_duration_s": 600,
            "schedule": {"days": [1, 2, 3, 4, 5, 6, 7], "start": "08:00", "end": "23:30"},
        },
    ],
}


@dataclass
class SeedResult:
    created: bool
    organisation_id: str
    site_id: str
    owner_email: str
    owner_password: str | None  # only when generated now


def seed_demo(
    sessions: sessionmaker[Session],
    owner_email: str = "demo-owner@code-ox.com",
    owner_password: str | None = None,
    site_yaml: Path | None = None,
) -> SeedResult:
    config = load_site(site_yaml) if site_yaml else SiteConfig.model_validate(DEMO_SITE)
    with system_session(sessions) as db:
        org = db.scalars(select(m.Organisation).where(m.Organisation.slug == DEMO_ORG_SLUG)).first()
        if org is not None:
            site = db.scalars(select(m.Site).where(m.Site.organisation_id == org.id)).first()
            return SeedResult(False, str(org.id), str(site.id) if site else "", owner_email, None)

        org = m.Organisation(
            name="Code-Ox Demo",
            slug=DEMO_ORG_SLUG,
            plan=m.Plan.BUSINESS,
            language=m.Language.EN,
            timezone=config.timezone,
        )
        db.add(org)
        db.flush()

        generated = owner_password is None
        password = owner_password or secrets.token_urlsafe(12)
        user = db.scalars(
            select(m.User).where(func.lower(m.User.email) == owner_email.lower())
        ).first()
        if user is None:
            user = m.User(
                email=owner_email.lower(),
                name="Demo owner",
                password_hash=hash_password(password),
                language=m.Language.EN,
            )
            db.add(user)
            db.flush()
        else:
            generated = False
        db.add(m.Membership(organisation_id=org.id, user_id=user.id, role=m.Role.OWNER))
        site = import_site_config(db, org.id, config, address="Riyadh (demo)")
        db.add(
            m.Recipient(
                organisation_id=org.id,
                site_id=site.id,
                user_id=user.id,
                name="Demo owner",
                language=m.Language.EN,
                email=user.email,
            )
        )
        db.commit()
        return SeedResult(
            True, str(org.id), str(site.id), user.email, password if generated else None
        )
