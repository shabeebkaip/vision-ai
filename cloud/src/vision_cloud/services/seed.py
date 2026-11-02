"""Importing a shared `SiteConfig` (e.g. an `examples/*/site.yaml`) into an organisation, and the
demo-organisation seed (CLD-01)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from vision_cloud.db import new_id, utcnow
from vision_cloud.models import (
    Camera,
    Device,
    DeviceStatus,
    LineRow,
    Membership,
    Organisation,
    Role,
    RuleRow,
    Site,
    User,
    Zone,
)
from vision_cloud.security import FieldCipher, hash_password, new_token, token_hash
from vision_shared.schemas import SiteConfig


def import_site_config(
    db: Session, organisation_id: str, config: SiteConfig, cipher: FieldCipher
) -> Site:
    """Create a site with its cameras, zones, lines and rules. New cloud ids are assigned to the
    site, cameras and rules (the YAML ids are mapped); zone and line ids are kept."""
    site = Site(
        id=new_id(),
        organisation_id=organisation_id,
        name=config.name or config.id,
        timezone=config.timezone,
        events_only=config.events_only,
    )
    db.add(site)
    db.flush()  # no ORM relationship between sites and cameras: insert the site first
    camera_ids: dict[str, str] = {}
    for cam in config.cameras:
        row = Camera(
            id=new_id(),
            organisation_id=organisation_id,
            site_id=site.id,
            name=cam.name or cam.id,
            stream_url_encrypted=cipher.encrypt(cam.source),
            fps=cam.fps,
            enabled=cam.enabled,
        )
        row.zones = [
            Zone(
                organisation_id=organisation_id,
                key=z.id,
                name=z.name,
                polygon=[list(p) for p in z.polygon],
            )
            for z in cam.zones
        ]
        row.lines = [
            LineRow(
                organisation_id=organisation_id,
                key=ln.id,
                name=ln.name,
                start=list(ln.start),
                end=list(ln.end),
            )
            for ln in cam.lines
        ]
        db.add(row)
        camera_ids[cam.id] = row.id
    db.flush()
    for rule in config.rules:
        db.add(
            RuleRow(
                organisation_id=organisation_id,
                site_id=site.id,
                camera_id=camera_ids[rule.camera_id],
                name=rule.name,
                type=rule.type.value,
                severity=rule.severity.value,
                enabled=rule.enabled,
                definition=rule.model_dump(mode="json", exclude={"id", "camera_id"}),
            )
        )
    db.flush()
    return site


@dataclass
class DemoSeed:
    organisation_id: str
    site_id: str
    owner_email: str
    device_id: str
    enrolment_token: str


def seed_demo(
    db: Session,
    cipher: FieldCipher,
    *,
    owner_email: str,
    owner_password: str,
    config: SiteConfig,
    organisation_name: str = "Demo organisation",
) -> DemoSeed:
    """One demo organisation: an owner, one site imported from `config`, one pending device.
    `db` must be a system session (it creates an organisation)."""
    org = Organisation(id=new_id(), name=organisation_name, plan="standard")
    db.add(org)
    db.flush()
    user = User(
        email=owner_email.lower(),
        password_hash=hash_password(owner_password),
        full_name="Demo owner",
    )
    db.add(user)
    db.flush()
    db.add(Membership(organisation_id=org.id, user_id=user.id, role=Role.OWNER.value))
    site = import_site_config(db, org.id, config, cipher)
    token = new_token("cxe_")
    device = Device(
        organisation_id=org.id,
        site_id=site.id,
        name="Demo edge box",
        status=DeviceStatus.PENDING.value,
        enrolment_token_hash=token_hash(token),
        enrolment_expires_at=utcnow() + timedelta(days=1),
    )
    db.add(device)
    db.flush()
    return DemoSeed(
        organisation_id=org.id,
        site_id=site.id,
        owner_email=user.email,
        device_id=device.id,
        enrolment_token=token,
    )
