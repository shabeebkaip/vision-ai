"""Device API used by edge boxes (CLD-04, CLD-05). Authenticated with the device token from
enrolment (`Authorization: Bearer cxd_...`), except the enrolment call itself."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import select

from vision_cloud.api.deps import DeviceDbDep, DeviceDep, StateDep, audit
from vision_cloud.db import system_session, utcnow
from vision_cloud.errors import AppError
from vision_cloud.models import Camera, Device, DeviceStatus, ModelRelease, Site
from vision_cloud.security import new_token, token_hash
from vision_cloud.services import ingest
from vision_cloud.services.config import current_config
from vision_shared.api import (
    AggregateBatch,
    AggregateBatchResult,
    EnrolmentRequest,
    EnrolmentResponse,
    EventBatch,
    EventBatchResult,
    EventIngestResult,
    EventMediaState,
    FinaliseRequest,
    Heartbeat,
    HeartbeatResponse,
    IngestStatus,
    ModelReleaseInfo,
    UploadRequest,
    UploadResponse,
)
from vision_shared.schemas import Event, SiteConfig

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/device/v1", tags=["device"])


@router.post("/enrol", response_model=EnrolmentResponse)
def enrol(body: EnrolmentRequest, state: StateDep, request: Request) -> EnrolmentResponse:
    """Exchange the one-time enrolment token for the device's long-lived token."""
    with system_session(state.sessions) as db:  # organisation unknown until the token matches
        device = db.scalar(
            select(Device).where(Device.enrolment_token_hash == token_hash(body.enrolment_token))
        )
        now = utcnow()
        if (
            device is None
            or device.status != DeviceStatus.PENDING.value
            or device.enrolment_expires_at is None
            or device.enrolment_expires_at <= now
        ):
            raise AppError(401, "enrolment token is invalid, used or expired", code="invalid_token")
        credential = new_token("cxd_")
        device.credential_hash = token_hash(credential)
        device.enrolment_token_hash = None
        device.enrolment_expires_at = None
        device.status = DeviceStatus.ACTIVE.value
        device.enrolled_at = now
        if body.hardware_tier:
            device.hardware_tier = body.hardware_tier
        device.software_version = body.software_version
        audit(
            db,
            request,
            organisation_id=device.organisation_id,
            device_id=device.id,
            action="device.enrolled",
            entity_type="device",
            entity_id=device.id,
            details={"hostname": body.hostname},
        )
        db.commit()
        log.info("device.enrolled", device_id=device.id, site_id=device.site_id)
        return EnrolmentResponse(
            device_id=device.id,
            organisation_id=device.organisation_id,
            site_id=device.site_id,
            device_token=credential,
        )


def _site(db: DeviceDbDep, site_id: str) -> Site:
    site = db.scalar(select(Site).where(Site.id == site_id))
    if site is None:
        raise AppError(404, "site not found")
    return site


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    body: Heartbeat, device: DeviceDep, db: DeviceDbDep, state: StateDep
) -> HeartbeatResponse:
    row = db.scalar(select(Device).where(Device.id == device.device_id))
    if row is None:
        raise AppError(404, "device not found")
    now = utcnow()
    row.last_heartbeat_at = now
    row.last_heartbeat = body.model_dump(mode="json")
    row.software_version = body.software_version or row.software_version
    row.model_version = body.model_version or row.model_version
    if body.config_version is not None:
        row.applied_config_version = body.config_version
    if body.cameras:
        cams = {
            c.id: c
            for c in db.scalars(
                select(Camera).where(
                    Camera.site_id == device.site_id,
                    Camera.id.in_([h.camera_id for h in body.cameras]),
                )
            ).all()
        }
        for health in body.cameras:
            cam = cams.get(health.camera_id)
            if cam is not None and cam.status != health.status.value:
                cam.status = health.status.value
                cam.status_at = now
    config, etag = current_config(db, _site(db, device.site_id), state.cipher)
    release = _current_release(db, device.hardware_tier)
    db.commit()
    return HeartbeatResponse(
        server_time=now,
        config_version=config.version,
        config_etag=etag,
        model_version=release.version if release else None,
    )


@router.get(
    "/config",
    response_model=SiteConfig,
    responses={304: {"description": "unchanged since the ETag in If-None-Match"}},
)
def get_config(
    device: DeviceDep,
    db: DeviceDbDep,
    state: StateDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """The shared `SiteConfig` for this device's site, with a strong ETag."""
    config, etag = current_config(db, _site(db, device.site_id), state.cipher)
    db.commit()
    quoted = f'"{etag}"'
    headers = {"ETag": quoted, "Cache-Control": "no-store", "X-Config-Version": str(config.version)}
    if if_none_match and quoted in {t.strip() for t in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)
    return Response(
        content=config.model_dump_json(), media_type="application/json", headers=headers
    )


def _current_release(db: DeviceDbDep, tier: str) -> ModelRelease | None:
    return db.scalar(
        select(ModelRelease)
        .where(ModelRelease.hardware_tier == tier, ModelRelease.is_current.is_(True))
        .order_by(ModelRelease.created_at.desc())
        .limit(1)
    )


@router.get(
    "/model-release",
    response_model=ModelReleaseInfo,
    responses={204: {"description": "no model release published for this hardware tier"}},
)
def model_release(device: DeviceDep, db: DeviceDbDep, state: StateDep) -> Response:
    release = _current_release(db, device.hardware_tier)
    if release is None:
        return Response(status_code=204)
    signed = state.storage.presign_get(release.storage_key, state.settings.upload_url_ttl_s)
    info = ModelReleaseInfo(
        version=release.version,
        hardware_tier=release.hardware_tier,
        sha256=release.sha256,
        download_url=signed.url,
        expires_at=signed.expires_at,
    )
    return Response(content=info.model_dump_json(), media_type="application/json")


@router.post("/logs", status_code=202)
async def upload_logs(request: Request, device: DeviceDep, state: StateDep) -> dict[str, int]:
    """Stub: accepts a log bundle and discards it (storage of logs is a follow-up)."""
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > state.settings.max_log_upload_bytes:
            raise AppError(413, "log upload too large")
    log.info("device.logs_received", device_id=device.device_id, bytes=size)
    return {"received_bytes": size}


# --------------------------------------------------------------------------- events


@router.post(
    "/events",
    response_model=EventIngestResult,
    responses={201: {"model": EventIngestResult, "description": "created"}},
)
def post_event(
    event: Event, device: DeviceDep, db: DeviceDbDep, state: StateDep, response: Response
) -> EventIngestResult:
    """Idempotent create keyed by `Event.id`: 201 when created, 200 when already known (or
    updated to "cleared")."""
    result = ingest.ingest_event(db, device, event, state.queue)
    if result.status is IngestStatus.REJECTED:
        db.rollback()
        code = 409 if result.error in ingest.CONFLICT_ERRORS else 422
        raise AppError(code, result.error or "event rejected", code="event_rejected")
    db.commit()
    response.status_code = 201 if result.status is IngestStatus.CREATED else 200
    return result


@router.post("/events/batch", response_model=EventBatchResult)
def post_events(
    body: EventBatch, device: DeviceDep, db: DeviceDbDep, state: StateDep
) -> EventBatchResult:
    """Up to `VISION_CLOUD_MAX_EVENTS_PER_BATCH` events (outbox replay). Per-item results;
    one bad event does not reject the batch."""
    if len(body.events) > state.settings.max_events_per_batch:
        raise AppError(413, f"at most {state.settings.max_events_per_batch} events per batch")
    results = ingest.ingest_events(db, device, body.events, state.queue)
    db.commit()
    return EventBatchResult(results=results)


@router.post("/events/{event_id}/uploads", response_model=UploadResponse)
def request_uploads(
    event_id: str, body: UploadRequest, device: DeviceDep, db: DeviceDbDep, state: StateDep
) -> UploadResponse:
    """Pre-signed PUT URLs for the event's snapshot and/or clip."""
    targets = ingest.upload_targets(db, state.storage, state.settings, device, event_id, body.kinds)
    return UploadResponse(event_id=event_id, uploads=targets)


@router.post("/events/{event_id}/finalise", response_model=EventMediaState)
def finalise(
    event_id: str, body: FinaliseRequest, device: DeviceDep, db: DeviceDbDep, state: StateDep
) -> EventMediaState:
    """Confirm uploads: the cloud checks the objects exist and records their keys."""
    result = ingest.finalise_media(
        db, state.storage, state.settings, device, event_id, body, state.queue
    )
    db.commit()
    return result


@router.post("/aggregates", response_model=AggregateBatchResult)
def post_aggregates(
    body: AggregateBatch, device: DeviceDep, db: DeviceDbDep, state: StateDep
) -> AggregateBatchResult:
    """Per-minute counts; re-sending a minute overwrites it (idempotent)."""
    if len(body.rows) > state.settings.max_aggregates_per_batch:
        raise AppError(413, f"at most {state.settings.max_aggregates_per_batch} rows per batch")
    accepted = ingest.ingest_aggregates(db, device, body.rows)
    db.commit()
    return AggregateBatchResult(accepted=accepted)
