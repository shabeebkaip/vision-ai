"""Building the shared `SiteConfig` a device runs, and versioning it (CLD-04).

The config is assembled from the site's cameras, zones, lines and rules and validated by the
shared schema, so the cloud can never hand an edge box a config the edge would reject. Its ETag is
the SHA-256 of the canonical JSON (without the version number); a new `config_versions` row with
the next version number is written whenever the ETag changes.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vision_cloud.errors import AppError
from vision_cloud.models import Camera, ConfigVersion, RuleRow, Site
from vision_cloud.security import FieldCipher
from vision_shared.schemas import CameraConfig, Line, Rule, SiteConfig, Zone


def redact_url(url: str) -> str:
    """Drop user:password from a stream URL (for API responses and stored config history)."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment))


def zones_of(camera: Camera) -> list[Zone]:
    return [
        Zone(id=z.key, name=z.name, polygon=[(float(p[0]), float(p[1])) for p in z.polygon])
        for z in camera.zones
    ]


def lines_of(camera: Camera) -> list[Line]:
    return [
        Line(
            id=ln.key,
            name=ln.name,
            start=(float(ln.start[0]), float(ln.start[1])),
            end=(float(ln.end[0]), float(ln.end[1])),
        )
        for ln in camera.lines
    ]


def rule_of(row: RuleRow) -> Rule:
    return Rule.model_validate({**row.definition, "id": row.id, "camera_id": row.camera_id})


def build_site_config(
    db: Session, site: Site, cipher: FieldCipher, version: int = 1, redact: bool = False
) -> SiteConfig:
    """`redact=True` removes stream credentials (for the stored history)."""
    cameras = db.scalars(
        select(Camera)
        .where(Camera.site_id == site.id, Camera.organisation_id == site.organisation_id)
        .order_by(Camera.created_at, Camera.id)
    ).all()
    rules = db.scalars(
        select(RuleRow)
        .where(RuleRow.site_id == site.id, RuleRow.organisation_id == site.organisation_id)
        .order_by(RuleRow.created_at, RuleRow.id)
    ).all()
    try:
        return SiteConfig(
            id=site.id,
            name=site.name,
            timezone=site.timezone,
            version=version,
            events_only=site.events_only,
            cameras=[
                CameraConfig(
                    id=c.id,
                    name=c.name,
                    source=_source(cipher, c, redact),
                    fps=c.fps,
                    zones=zones_of(c),
                    lines=lines_of(c),
                    enabled=c.enabled,
                )
                for c in cameras
            ],
            rules=[rule_of(r) for r in rules],
        )
    except ValidationError as exc:
        raise AppError(
            422,
            "the site configuration would be invalid",
            code="invalid_site_config",
            details=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        ) from exc


def _source(cipher: FieldCipher, camera: Camera, redact: bool) -> str:
    url = cipher.decrypt(camera.stream_url_encrypted)
    return redact_url(url) if redact else url


def config_etag(config: SiteConfig) -> str:
    canonical = config.model_dump_json(exclude={"version"})
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_config(db: Session, site: Site, cipher: FieldCipher) -> tuple[SiteConfig, str]:
    """The config devices should run now, with its version and ETag; publishes a new version when
    anything changed since the last one."""
    config = build_site_config(db, site, cipher)
    etag = config_etag(config)
    for _attempt in range(3):
        latest = db.scalar(
            select(ConfigVersion)
            .where(ConfigVersion.site_id == site.id)
            .order_by(ConfigVersion.version.desc())
            .limit(1)
        )
        if latest is not None and latest.etag == etag:
            return config.model_copy(update={"version": latest.version}), etag
        version = (latest.version if latest else 0) + 1
        history = build_site_config(db, site, cipher, version, redact=True)
        try:
            with db.begin_nested():
                db.add(
                    ConfigVersion(
                        organisation_id=site.organisation_id,
                        site_id=site.id,
                        version=version,
                        etag=etag,
                        config=history.model_dump(mode="json"),
                    )
                )
        except IntegrityError:
            continue  # another request published the same version first; re-read
        return config.model_copy(update={"version": version}), etag
    raise AppError(409, "config is changing too fast; retry", code="conflict")
