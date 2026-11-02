"""Translate between database rows and `vision_shared.schemas.SiteConfig` (the edge contract).

`build_site_config` is what the device config endpoint serves; `import_site_config` loads a site
YAML (used by the seed and, later, by the dashboard's import). Both validate through the shared
pydantic models, so the cloud can never hand an edge box a config the edge would reject.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vision_cloud import models as m
from vision_shared import schemas as s

REDACTED = "***"


def build_site_config(db: Session, site: m.Site, version: int = 1) -> s.SiteConfig:
    cameras = db.scalars(
        select(m.Camera).where(m.Camera.site_id == site.id).order_by(m.Camera.key)
    ).all()
    cam_ids = [c.id for c in cameras]
    zones = db.scalars(
        select(m.Zone).where(m.Zone.camera_id.in_(cam_ids)).order_by(m.Zone.key)
    ).all()
    lines = db.scalars(
        select(m.Line).where(m.Line.camera_id.in_(cam_ids)).order_by(m.Line.key)
    ).all()
    rules = db.scalars(select(m.Rule).where(m.Rule.site_id == site.id).order_by(m.Rule.key)).all()

    cam_key = {c.id: c.key for c in cameras}
    zone_key = {z.id: z.key for z in zones}
    line_key = {ln.id: ln.key for ln in lines}

    camera_configs = [
        s.CameraConfig(
            id=c.key,
            name=c.name,
            source=c.stream_url,
            fps=c.fps,
            enabled=c.enabled,
            zones=[
                s.Zone(id=z.key, name=z.name, polygon=[(p[0], p[1]) for p in z.polygon])
                for z in zones
                if z.camera_id == c.id
            ],
            lines=[
                s.Line(
                    id=ln.key,
                    name=ln.name,
                    start=(ln.start_point[0], ln.start_point[1]),
                    end=(ln.end_point[0], ln.end_point[1]),
                )
                for ln in lines
                if ln.camera_id == c.id
            ],
        )
        for c in cameras
    ]
    rule_configs = [
        s.Rule(
            id=r.key,
            name=r.name,
            type=r.type,
            camera_id=cam_key[r.camera_id],
            zone_id=zone_key[r.zone_id] if r.zone_id else None,
            line_id=line_key[r.line_id] if r.line_id else None,
            classes=list(r.classes),
            threshold=r.threshold,
            min_duration_s=r.min_duration_s,
            window_s=r.window_s,
            direction=r.direction,
            clear_after_s=r.clear_after_s,
            cooldown_s=r.cooldown_s,
            min_confidence=r.min_confidence,
            schedule=s.Schedule.model_validate(r.schedule) if r.schedule else None,
            severity=r.severity,
            verify=r.verify,
            enabled=r.enabled,
        )
        for r in rules
    ]
    return s.SiteConfig(
        id=site.key,
        name=site.name,
        timezone=site.timezone,
        version=version,
        events_only=site.events_only,
        cameras=camera_configs,
        rules=rule_configs,
    )


def content_hash(config: s.SiteConfig) -> str:
    """Hash of everything the edge cares about except the version number itself."""
    data = config.model_dump(mode="json", exclude={"version"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def redacted(config: s.SiteConfig) -> dict[str, Any]:
    data = config.model_dump(mode="json")
    for cam in data["cameras"]:
        cam["source"] = REDACTED
    return data


def current_config(db: Session, site: m.Site) -> tuple[s.SiteConfig, m.ConfigVersion]:
    """The site's config with its version number; records a new version when the content changed."""
    for _ in range(3):
        config = build_site_config(db, site)
        digest = content_hash(config)
        latest = db.scalars(
            select(m.ConfigVersion)
            .where(m.ConfigVersion.site_id == site.id)
            .order_by(m.ConfigVersion.version.desc())
            .limit(1)
        ).first()
        if latest is not None and latest.content_hash == digest:
            return config.model_copy(update={"version": latest.version}), latest
        version = (latest.version + 1) if latest else 1
        config = config.model_copy(update={"version": version})
        row = m.ConfigVersion(
            organisation_id=site.organisation_id,
            site_id=site.id,
            version=version,
            content_hash=digest,
            config=redacted(config),
        )
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:
            continue  # another request recorded this version first; read it again
        return config, row
    raise RuntimeError("could not record a config version")


def import_site_config(
    db: Session, org_id: uuid.UUID, config: s.SiteConfig, address: str = ""
) -> m.Site:
    """Create a site with its cameras, zones, lines and rules from a SiteConfig."""
    site = m.Site(
        organisation_id=org_id,
        key=config.id,
        name=config.name,
        timezone=config.timezone,
        events_only=config.events_only,
        address=address,
    )
    db.add(site)
    db.flush()
    cam_ids: dict[str, uuid.UUID] = {}
    zone_ids: dict[tuple[str, str], uuid.UUID] = {}
    line_ids: dict[tuple[str, str], uuid.UUID] = {}
    for cam in config.cameras:
        row = m.Camera(
            organisation_id=org_id,
            site_id=site.id,
            key=cam.id,
            name=cam.name,
            stream_url=cam.source,
            fps=cam.fps,
            enabled=cam.enabled,
        )
        db.add(row)
        db.flush()
        cam_ids[cam.id] = row.id
        for z in cam.zones:
            zr = m.Zone(
                organisation_id=org_id,
                camera_id=row.id,
                key=z.id,
                name=z.name,
                polygon=[list(p) for p in z.polygon],
            )
            db.add(zr)
            db.flush()
            zone_ids[(cam.id, z.id)] = zr.id
        for ln in cam.lines:
            lr = m.Line(
                organisation_id=org_id,
                camera_id=row.id,
                key=ln.id,
                name=ln.name,
                start_point=list(ln.start),
                end_point=list(ln.end),
            )
            db.add(lr)
            db.flush()
            line_ids[(cam.id, ln.id)] = lr.id
    for r in config.rules:
        db.add(
            m.Rule(
                organisation_id=org_id,
                site_id=site.id,
                camera_id=cam_ids[r.camera_id],
                key=r.id,
                name=r.name,
                type=r.type,
                zone_id=zone_ids[(r.camera_id, r.zone_id)] if r.zone_id else None,
                line_id=line_ids[(r.camera_id, r.line_id)] if r.line_id else None,
                classes=list(r.classes),
                threshold=r.threshold,
                min_duration_s=r.min_duration_s,
                window_s=r.window_s,
                direction=r.direction,
                clear_after_s=r.clear_after_s,
                cooldown_s=r.cooldown_s,
                min_confidence=r.min_confidence,
                schedule=r.schedule.model_dump(mode="json") if r.schedule else None,
                severity=r.severity,
                verify=r.verify,
                enabled=r.enabled,
            )
        )
    db.flush()
    return site
