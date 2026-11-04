"""Management API for the dashboard: sites, cameras (with zones and lines), rules and devices
(CLD-07 minimal, CLD-04 enrolment tokens).

Every query filters on the caller's organisation explicitly *and* through the tenant session;
site managers and viewers additionally only see their sites. Anything not visible is a 404, never
a 403, so ids of other tenants cannot be probed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from vision_cloud.api.deps import AppState, DbDep, Principal, PrincipalDep, StateDep, audit
from vision_cloud.db import new_id, utcnow
from vision_cloud.errors import AppError, not_found
from vision_cloud.models import Camera, Device, DeviceStatus, LineRow, Role, RuleRow, Site, Zone
from vision_cloud.schemas import (
    CameraCreate,
    CameraOut,
    CameraUpdate,
    DeviceCreate,
    DeviceCreated,
    DeviceOut,
    RuleIn,
    RuleOut,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)
from vision_cloud.security import FieldCipher, new_token, token_hash
from vision_cloud.services.config import (
    build_site_config,
    lines_of,
    redact_url,
    rule_of,
    zones_of,
)
from vision_shared.schemas import CameraConfig, Line, Rule, SiteConfig
from vision_shared.schemas import Zone as ZoneSpec

router = APIRouter(prefix="/api/v1")


# --------------------------------------------------------------------------- lookups


def get_site(db: Session, principal: Principal, site_id: str) -> Site:
    site = db.scalar(
        select(Site).where(
            Site.id == site_id,
            Site.organisation_id == principal.organisation_id,
            principal.site_filter(Site.id),
        )
    )
    if site is None:
        raise not_found("site")
    return site


def get_camera(db: Session, principal: Principal, camera_id: str) -> Camera:
    cam = db.scalar(
        select(Camera).where(
            Camera.id == camera_id,
            Camera.organisation_id == principal.organisation_id,
            principal.site_filter(Camera.site_id),
        )
    )
    if cam is None:
        raise not_found("camera")
    return cam


def get_rule(db: Session, principal: Principal, rule_id: str) -> RuleRow:
    row = db.scalar(
        select(RuleRow).where(
            RuleRow.id == rule_id,
            RuleRow.organisation_id == principal.organisation_id,
            principal.site_filter(RuleRow.site_id),
        )
    )
    if row is None:
        raise not_found("rule")
    return row


def _audit(
    db: Session,
    request: Request,
    principal: Principal,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, object] | None = None,
) -> None:
    audit(
        db,
        request,
        organisation_id=principal.organisation_id,
        user_id=principal.user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=dict(details or {}),
    )


# --------------------------------------------------------------------------- sites


# GET /sites (with camera counts and alerts today) lives in api/dashboard.py.


@router.post("/sites", response_model=SiteOut, status_code=201, tags=["sites"])
def create_site(body: SiteCreate, principal: PrincipalDep, db: DbDep, request: Request) -> Site:
    principal.require(Role.MANAGER)
    site = Site(organisation_id=principal.organisation_id, **body.model_dump())
    db.add(site)
    db.flush()
    _audit(db, request, principal, "site.created", "site", site.id, {"name": site.name})
    db.commit()
    return site


@router.get("/sites/{site_id}", response_model=SiteOut, tags=["sites"])
def read_site(site_id: str, principal: PrincipalDep, db: DbDep) -> Site:
    return get_site(db, principal, site_id)


@router.patch("/sites/{site_id}", response_model=SiteOut, tags=["sites"])
def update_site(
    site_id: str, body: SiteUpdate, principal: PrincipalDep, db: DbDep, request: Request
) -> Site:
    principal.require(Role.MANAGER)
    site = get_site(db, principal, site_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None:
            raise AppError(422, f"{key} cannot be null")
        setattr(site, key, value)
    _audit(db, request, principal, "site.updated", "site", site.id, {"fields": sorted(changes)})
    db.commit()
    return site


@router.get("/sites/{site_id}/config", response_model=SiteConfig, tags=["sites"])
def preview_site_config(
    site_id: str, principal: PrincipalDep, db: DbDep, state: StateDep
) -> SiteConfig:
    """The configuration the site's edge boxes receive, with stream credentials redacted."""
    principal.require(Role.SITE_MANAGER)
    site = get_site(db, principal, site_id)
    return build_site_config(db, site, state.cipher, redact=True)


# --------------------------------------------------------------------------- cameras


def camera_out(cam: Camera, cipher: FieldCipher) -> CameraOut:
    return CameraOut(
        id=cam.id,
        site_id=cam.site_id,
        name=cam.name,
        source_redacted=redact_url(cipher.decrypt(cam.stream_url_encrypted)),
        fps=cam.fps,
        width=cam.width,
        height=cam.height,
        status=cam.status,
        status_at=cam.status_at,
        enabled=cam.enabled,
        zones=zones_of(cam),
        lines=lines_of(cam),
    )


def _check_geometry(zones: list[ZoneSpec], lines: list[Line]) -> None:
    try:
        CameraConfig(id="check", source="check", zones=zones, lines=lines)
    except ValueError as exc:
        raise AppError(422, "zone and line ids must be unique per camera") from exc


def _sync_zones(cam: Camera, zones: list[ZoneSpec]) -> None:
    by_key = {z.key: z for z in cam.zones}
    wanted = {z.id for z in zones}
    for key, row in list(by_key.items()):
        if key not in wanted:
            cam.zones.remove(row)
    for spec in zones:
        polygon = [[x, y] for x, y in spec.polygon]
        if spec.id in by_key:
            by_key[spec.id].name = spec.name
            by_key[spec.id].polygon = polygon
        else:
            cam.zones.append(
                Zone(
                    organisation_id=cam.organisation_id,
                    key=spec.id,
                    name=spec.name,
                    polygon=polygon,
                )
            )


def _sync_lines(cam: Camera, lines: list[Line]) -> None:
    by_key = {ln.key: ln for ln in cam.lines}
    wanted = {ln.id for ln in lines}
    for key, row in list(by_key.items()):
        if key not in wanted:
            cam.lines.remove(row)
    for spec in lines:
        start, end = list(spec.start), list(spec.end)
        if spec.id in by_key:
            row = by_key[spec.id]
            row.name, row.start, row.end = spec.name, start, end
        else:
            cam.lines.append(
                LineRow(
                    organisation_id=cam.organisation_id,
                    key=spec.id,
                    name=spec.name,
                    start=start,
                    end=end,
                )
            )


@router.get("/cameras", response_model=list[CameraOut], tags=["cameras"])
def list_cameras(
    principal: PrincipalDep,
    db: DbDep,
    state: StateDep,
    site_id: Annotated[str | None, Query()] = None,
) -> list[CameraOut]:
    stmt = select(Camera).where(
        Camera.organisation_id == principal.organisation_id, principal.site_filter(Camera.site_id)
    )
    if site_id:
        stmt = stmt.where(Camera.site_id == site_id)
    cams = db.scalars(stmt.order_by(Camera.site_id, Camera.name, Camera.id)).all()
    return [camera_out(c, state.cipher) for c in cams]


@router.post(
    "/sites/{site_id}/cameras", response_model=CameraOut, status_code=201, tags=["cameras"]
)
def create_camera(
    site_id: str,
    body: CameraCreate,
    principal: PrincipalDep,
    db: DbDep,
    state: StateDep,
    request: Request,
) -> CameraOut:
    principal.require(Role.SITE_MANAGER)
    site = get_site(db, principal, site_id)
    _check_geometry(body.zones, body.lines)
    cam = Camera(
        organisation_id=principal.organisation_id,
        site_id=site.id,
        name=body.name,
        stream_url_encrypted=state.cipher.encrypt(body.source),
        fps=body.fps,
        enabled=body.enabled,
    )
    db.add(cam)
    _sync_zones(cam, body.zones)
    _sync_lines(cam, body.lines)
    db.flush()
    _audit(db, request, principal, "camera.created", "camera", cam.id, {"site_id": site.id})
    db.commit()
    return camera_out(cam, state.cipher)


@router.get("/cameras/{camera_id}", response_model=CameraOut, tags=["cameras"])
def read_camera(camera_id: str, principal: PrincipalDep, db: DbDep, state: StateDep) -> CameraOut:
    return camera_out(get_camera(db, principal, camera_id), state.cipher)


@router.patch("/cameras/{camera_id}", response_model=CameraOut, tags=["cameras"])
def update_camera(
    camera_id: str,
    body: CameraUpdate,
    principal: PrincipalDep,
    db: DbDep,
    state: StateDep,
    request: Request,
) -> CameraOut:
    """Partial update; `zones` / `lines`, when given, replace the camera's whole set (matched by
    id, so rules keep pointing at zones that still exist)."""
    principal.require(Role.SITE_MANAGER)
    cam = get_camera(db, principal, camera_id)
    changes = body.model_dump(exclude_unset=True)
    _check_geometry(
        body.zones if body.zones is not None else zones_of(cam),
        body.lines if body.lines is not None else lines_of(cam),
    )
    if body.name is not None:
        cam.name = body.name
    if body.source is not None:
        cam.stream_url_encrypted = state.cipher.encrypt(body.source)
    if body.fps is not None:
        cam.fps = body.fps
    if body.enabled is not None:
        cam.enabled = body.enabled
    if body.zones is not None:
        _sync_zones(cam, body.zones)
    if body.lines is not None:
        _sync_lines(cam, body.lines)
    db.flush()
    _validate_site(db, state, cam.site_id, principal)
    _audit(db, request, principal, "camera.updated", "camera", cam.id, {"fields": sorted(changes)})
    db.commit()
    return camera_out(cam, state.cipher)


def _validate_site(db: Session, state: AppState, site_id: str, principal: Principal) -> None:
    """Refuse a change that would make the site's SiteConfig invalid (e.g. a rule pointing at a
    removed zone). Raises 422; the session is then rolled back."""
    site = db.scalar(
        select(Site).where(Site.id == site_id, Site.organisation_id == principal.organisation_id)
    )
    if site is not None:
        build_site_config(db, site, state.cipher, redact=True)


# --------------------------------------------------------------------------- rules


def rule_out(row: RuleRow) -> RuleOut:
    return RuleOut.model_validate(
        {
            **rule_of(row).model_dump(),
            "site_id": row.site_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


def _apply_rule(row: RuleRow, rule: Rule) -> None:
    row.camera_id = rule.camera_id
    row.name = rule.name
    row.type = rule.type.value
    row.severity = rule.severity.value
    row.enabled = rule.enabled
    row.definition = rule.model_dump(mode="json", exclude={"id", "camera_id"})


@router.get("/rules", response_model=list[RuleOut], tags=["rules"])
def list_rules(
    principal: PrincipalDep,
    db: DbDep,
    site_id: Annotated[str | None, Query()] = None,
    camera_id: Annotated[str | None, Query()] = None,
) -> list[RuleOut]:
    stmt = select(RuleRow).where(
        RuleRow.organisation_id == principal.organisation_id,
        principal.site_filter(RuleRow.site_id),
    )
    if site_id:
        stmt = stmt.where(RuleRow.site_id == site_id)
    if camera_id:
        stmt = stmt.where(RuleRow.camera_id == camera_id)
    return [rule_out(r) for r in db.scalars(stmt.order_by(RuleRow.created_at, RuleRow.id)).all()]


@router.post("/rules", response_model=RuleOut, status_code=201, tags=["rules"])
def create_rule(
    body: RuleIn, principal: PrincipalDep, db: DbDep, state: StateDep, request: Request
) -> RuleOut:
    principal.require(Role.SITE_MANAGER)
    cam = get_camera(db, principal, body.camera_id)
    rule_id = new_id()
    rule = Rule.model_validate({**body.model_dump(exclude={"id"}), "id": rule_id})
    row = RuleRow(id=rule_id, organisation_id=principal.organisation_id, site_id=cam.site_id)
    _apply_rule(row, rule)
    db.add(row)
    db.flush()
    _validate_site(db, state, cam.site_id, principal)
    _audit(db, request, principal, "rule.created", "rule", row.id, {"type": row.type})
    db.commit()
    return rule_out(row)


@router.get("/rules/{rule_id}", response_model=RuleOut, tags=["rules"])
def read_rule(rule_id: str, principal: PrincipalDep, db: DbDep) -> RuleOut:
    return rule_out(get_rule(db, principal, rule_id))


@router.put("/rules/{rule_id}", response_model=RuleOut, tags=["rules"])
def replace_rule(
    rule_id: str,
    body: RuleIn,
    principal: PrincipalDep,
    db: DbDep,
    state: StateDep,
    request: Request,
) -> RuleOut:
    principal.require(Role.SITE_MANAGER)
    row = get_rule(db, principal, rule_id)
    cam = get_camera(db, principal, body.camera_id)
    if cam.site_id != row.site_id:
        raise AppError(422, "a rule cannot move to a camera of another site")
    rule = Rule.model_validate({**body.model_dump(exclude={"id"}), "id": row.id})
    _apply_rule(row, rule)
    db.flush()
    _validate_site(db, state, row.site_id, principal)
    _audit(db, request, principal, "rule.updated", "rule", row.id, {"type": row.type})
    db.commit()
    return rule_out(row)


@router.delete("/rules/{rule_id}", status_code=204, tags=["rules"])
def delete_rule(rule_id: str, principal: PrincipalDep, db: DbDep, request: Request) -> None:
    principal.require(Role.SITE_MANAGER)
    row = get_rule(db, principal, rule_id)
    db.delete(row)
    _audit(db, request, principal, "rule.deleted", "rule", rule_id)
    db.commit()


# --------------------------------------------------------------------------- devices


@router.get("/devices", response_model=list[DeviceOut], tags=["devices"])
def list_devices(
    principal: PrincipalDep, db: DbDep, site_id: Annotated[str | None, Query()] = None
) -> list[Device]:
    stmt = select(Device).where(
        Device.organisation_id == principal.organisation_id, principal.site_filter(Device.site_id)
    )
    if site_id:
        stmt = stmt.where(Device.site_id == site_id)
    return list(db.scalars(stmt.order_by(Device.created_at, Device.id)).all())


@router.post(
    "/sites/{site_id}/devices", response_model=DeviceCreated, status_code=201, tags=["devices"]
)
def create_device(
    site_id: str,
    body: DeviceCreate,
    principal: PrincipalDep,
    db: DbDep,
    state: StateDep,
    request: Request,
) -> DeviceCreated:
    """Register an edge box and get its one-time enrolment token."""
    principal.require(Role.MANAGER)
    site = get_site(db, principal, site_id)
    token = new_token("cxe_")
    expires = utcnow() + timedelta(seconds=state.settings.enrolment_token_ttl_s)
    device = Device(
        organisation_id=principal.organisation_id,
        site_id=site.id,
        name=body.name,
        hardware_tier=body.hardware_tier,
        status=DeviceStatus.PENDING.value,
        enrolment_token_hash=token_hash(token),
        enrolment_expires_at=expires,
    )
    db.add(device)
    db.flush()
    _audit(db, request, principal, "device.created", "device", device.id, {"site_id": site.id})
    db.commit()
    return DeviceCreated(
        device=DeviceOut.model_validate(device),
        enrolment_token=token,
        enrolment_expires_at=expires,
    )


@router.post("/devices/{device_id}/revoke", response_model=DeviceOut, tags=["devices"])
def revoke_device(device_id: str, principal: PrincipalDep, db: DbDep, request: Request) -> Device:
    principal.require(Role.MANAGER)
    device = db.scalar(
        select(Device).where(
            Device.id == device_id,
            Device.organisation_id == principal.organisation_id,
            principal.site_filter(Device.site_id),
        )
    )
    if device is None:
        raise not_found("device")
    device.status = DeviceStatus.REVOKED.value
    device.credential_hash = None
    device.enrolment_token_hash = None
    _audit(db, request, principal, "device.revoked", "device", device.id)
    db.commit()
    return device
