"""Device API (CLD-04): enrolment, heartbeat, config with ETag, model release, log upload.

Edge boxes authenticate with `Authorization: Bearer <credential>` (the credential from enrolment).
Only its SHA-256 is stored. Each device is rate-limited (token bucket, see `ratelimit.py`).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import func, select

from vision_cloud import crypto
from vision_cloud import models as m
from vision_cloud.api.deps import DB, CurrentDevice, Limiter, Sessions, Settings, Store, rate_limit
from vision_cloud.contract import (
    EnrolmentRequest,
    EnrolmentResponse,
    Heartbeat,
    HeartbeatResponse,
    LogUploadRequest,
    LogUploadResponse,
    ModelReleaseInfo,
    UploadTarget,
)
from vision_cloud.db import system_session
from vision_cloud.errors import APIError, unauthorised
from vision_cloud.services import audit
from vision_cloud.siteconfig import current_config
from vision_cloud.storage import device_log_key

router = APIRouter(prefix="/device/v1", tags=["device"])

ENROL_PER_MIN = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    candidates = {tag.strip().removeprefix("W/") for tag in header.split(",")}
    return etag in candidates or "*" in candidates


@router.post("/enrol", response_model=EnrolmentResponse, status_code=201)
def enrol(
    body: EnrolmentRequest, request: Request, sessions: Sessions, limiter: Limiter
) -> EnrolmentResponse:
    client = request.client.host if request.client else "unknown"
    rate_limit(limiter, f"enrol:{client}", ENROL_PER_MIN, ENROL_PER_MIN)
    with system_session(sessions) as db:
        tok = db.scalars(
            select(m.EnrolmentToken)
            .where(m.EnrolmentToken.token_hash == crypto.hash_token(body.token))
            .with_for_update()
        ).first()
        if tok is None or tok.used_at is not None or tok.expires_at <= _now():
            raise unauthorised("invalid_enrolment_token", "enrolment token is invalid or used")
        site = db.get(m.Site, tok.site_id)
        assert site is not None
        try:
            tier = m.HardwareTier(body.hardware_tier) if body.hardware_tier else None
        except ValueError:
            tier = m.HardwareTier.OTHER
        credential = "dev_" + crypto.new_token()
        device = m.Device(
            organisation_id=tok.organisation_id,
            site_id=tok.site_id,
            name=body.name or tok.device_name,
            hardware_tier=tier,
            credential_hash=crypto.hash_token(credential),
            software_version=body.software_version,
        )
        db.add(device)
        db.flush()
        tok.used_at = _now()
        tok.device_id = device.id
        audit.record(
            db,
            org_id=tok.organisation_id,
            action="device.enrolled",
            entity_type="device",
            entity_id=device.id,
            device_id=device.id,
            request=request,
        )
        db.commit()
        return EnrolmentResponse(device_id=str(device.id), site_id=site.key, credential=credential)


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(body: Heartbeat, ctx: CurrentDevice, db: DB) -> HeartbeatResponse:
    device = ctx.device
    now = _now()
    device.last_heartbeat_at = now
    device.last_heartbeat = body.model_dump(mode="json")
    device.software_version = body.software_version
    device.model_version = body.model_version
    if body.applied_config_version is not None:
        device.applied_config_version = body.applied_config_version

    if body.cameras:
        cameras = {
            c.key: c
            for c in db.scalars(select(m.Camera).where(m.Camera.site_id == ctx.site.id)).all()
        }
        for health in body.cameras:
            cam = cameras.get(health.camera_id)
            if cam is None:
                continue  # camera removed in the cloud; the box will drop it on the next config pull
            cam.status = m.CameraStatus.ONLINE if health.online else m.CameraStatus.OFFLINE
            if health.last_frame_at is not None:
                cam.last_frame_at = health.last_frame_at
            if health.resolution:
                cam.resolution = health.resolution

    latest = db.scalar(
        select(func.max(m.ConfigVersion.version)).where(m.ConfigVersion.site_id == ctx.site.id)
    )
    logs_requested = device.logs_requested_at is not None
    db.commit()
    return HeartbeatResponse(server_time=now, config_version=latest, logs_requested=logs_requested)


@router.get(
    "/config",
    responses={
        200: {"description": "the site's SiteConfig (vision_shared.schemas.SiteConfig)"},
        304: {"description": "unchanged since If-None-Match"},
    },
)
def get_config(
    ctx: CurrentDevice,
    db: DB,
    if_none_match: str | None = Header(default=None),
) -> Response:
    config, version = current_config(db, ctx.site)
    db.commit()
    etag = f'"v{version.version}-{version.content_hash[:16]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=config.model_dump_json(), media_type="application/json", headers=headers
    )


@router.get(
    "/model-release",
    response_model=ModelReleaseInfo,
    responses={204: {"description": "no release for this device's channel"}, 304: {}},
)
def get_model_release(
    ctx: CurrentDevice,
    db: DB,
    store: Store,
    settings: Settings,
    if_none_match: str | None = Header(default=None),
) -> Response:
    device = ctx.device
    release: m.ModelRelease | None = None
    if device.pinned_model_release_id is not None:
        release = db.get(m.ModelRelease, device.pinned_model_release_id)
    if release is None:
        release = db.scalars(
            select(m.ModelRelease)
            .where(m.ModelRelease.channel == device.model_channel)
            .order_by(m.ModelRelease.created_at.desc())
            .limit(1)
        ).first()
    if release is None:
        return Response(status_code=204)
    etag = f'"{release.id}"'
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers={"ETag": etag})
    expires = _now().timestamp() + settings.download_url_ttl_s
    info = ModelReleaseInfo(
        id=str(release.id),
        name=release.name,
        version=release.version,
        channel=release.channel.value,
        sha256=release.sha256,
        size_bytes=release.size_bytes,
        download_url=store.presign_get(release.file_key, settings.download_url_ttl_s),
        expires_at=datetime.fromtimestamp(expires, timezone.utc),
    )
    return Response(
        content=info.model_dump_json(), media_type="application/json", headers={"ETag": etag}
    )


@router.post("/logs", response_model=LogUploadResponse, status_code=201)
def request_log_upload(
    body: LogUploadRequest,
    request: Request,
    ctx: CurrentDevice,
    db: DB,
    store: Store,
    settings: Settings,
) -> LogUploadResponse:
    if body.size_bytes > settings.max_log_bytes:
        raise APIError(413, "too_large", f"log bundle over {settings.max_log_bytes} bytes")
    device = ctx.device
    key = device_log_key(device.organisation_id, device.site_id, device.id, _now())
    post = store.presign_post(
        key, "application/gzip", settings.max_log_bytes, settings.upload_url_ttl_s
    )
    device.logs_requested_at = None
    audit.record(
        db,
        org_id=device.organisation_id,
        action="device.logs_uploaded",
        entity_type="device",
        entity_id=device.id,
        device_id=device.id,
        details={"key": key, "reason": body.reason},
        request=request,
    )
    db.commit()
    return LogUploadResponse(
        upload=UploadTarget(
            url=post.url,
            fields=post.fields,
            key=post.key,
            expires_at=post.expires_at,
            max_bytes=post.max_bytes,
        )
    )
