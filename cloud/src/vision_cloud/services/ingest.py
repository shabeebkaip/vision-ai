"""Event, media and aggregate ingest from edge boxes (CLD-05).

Idempotency: the edge-generated `Event.id` is the primary key. Re-sending an event that is already
stored changes nothing ("unchanged"), except the one forward transition the edge outbox produces:
the same event re-sent in state "cleared" updates `state`, `cleared_at`, `value`, `message` and
`attributes` ("updated"). An event never goes back from cleared to triggered.

Snapshot and clip keys are owned by the cloud: the edge's local paths in `snapshot_key`/`clip_key`
are ignored and the keys are set by the finalise call after the uploads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vision_cloud.api.deps import DevicePrincipal
from vision_cloud.db import new_id, utcnow
from vision_cloud.errors import AppError, not_found
from vision_cloud.jobs import JobQueue
from vision_cloud.models import AggregateMinute, Camera, EventRow, Site
from vision_cloud.settings import CloudSettings
from vision_cloud.storage import MEDIA_FILES, ObjectStorage, event_media_key
from vision_shared.api import (
    AggregateRow,
    EventIngestResult,
    EventMediaState,
    FinaliseRequest,
    IngestStatus,
    MediaKind,
    UploadTarget,
)
from vision_shared.schemas import Event, EventState

MAX_EVENT_ID = 64
ID_CONFLICT = "event id conflict"
ID_REUSED = "event id already used for another camera"
CONFLICT_ERRORS = frozenset({ID_CONFLICT, ID_REUSED})


def _rejected(event_id: str, error: str) -> EventIngestResult:
    return EventIngestResult(event_id=event_id, status=IngestStatus.REJECTED, error=error)


def ingest_events(
    db: Session, device: DevicePrincipal, events: list[Event], queue: JobQueue
) -> list[EventIngestResult]:
    """Store a batch of events; one result per event, in order. The caller commits.

    Cameras and already-stored events are fetched with one query each, new rows are flushed
    together; only when that flush hits a conflict (an id used by another organisation, or a
    concurrent insert) are the new rows retried one by one to find the culprit."""
    camera_ids = {e.camera_id for e in events}
    known_cameras = set(
        db.scalars(
            select(Camera.id).where(Camera.id.in_(camera_ids), Camera.site_id == device.site_id)
        ).all()
    )
    ids = [e.id for e in events if len(e.id) <= MAX_EVENT_ID]
    rows: dict[str, EventRow] = {
        r.id: r for r in db.scalars(select(EventRow).where(EventRow.id.in_(ids))).all()
    }
    results: list[EventIngestResult] = []
    new_rows: list[EventRow] = []
    jobs: list[tuple[str, str]] = []
    for event in events:
        if len(event.id) > MAX_EVENT_ID:
            results.append(
                _rejected(event.id[:MAX_EVENT_ID], f"event id longer than {MAX_EVENT_ID}")
            )
        elif event.site_id != device.site_id:
            results.append(_rejected(event.id, "event site_id is not this device's site"))
        elif event.camera_id not in known_cameras:
            results.append(_rejected(event.id, f"unknown camera {event.camera_id}"))
        elif event.id in rows:
            results.append(_apply_existing(rows[event.id], event, device, jobs))
        else:
            row = _new_row(device, event)
            rows[event.id] = row
            new_rows.append(row)
            jobs.append(("event.created", event.id))
            results.append(EventIngestResult(event_id=event.id, status=IngestStatus.CREATED))
    if new_rows and not _insert_all(db, new_rows):
        conflicted = {r.id for r in new_rows if not _insert_all(db, [r])}
        results = [
            _rejected(r.event_id, ID_CONFLICT)
            if r.event_id in conflicted and r.status is not IngestStatus.REJECTED
            else r
            for r in results
        ]
        jobs = [j for j in jobs if j[1] not in conflicted]
    for job, event_id in jobs:
        queue.enqueue(job, _job(device, event_id))
    return results


def ingest_event(
    db: Session, device: DevicePrincipal, event: Event, queue: JobQueue
) -> EventIngestResult:
    return ingest_events(db, device, [event], queue)[0]


def _insert_all(db: Session, rows: list[EventRow]) -> bool:
    try:
        with db.begin_nested():
            db.add_all(rows)
    except IntegrityError:
        for row in rows:
            if row in db:
                db.expunge(row)
        return False
    return True


def _apply_existing(
    existing: EventRow, event: Event, device: DevicePrincipal, jobs: list[tuple[str, str]]
) -> EventIngestResult:
    if existing.site_id != device.site_id or existing.camera_id != event.camera_id:
        return _rejected(event.id, ID_REUSED)
    if event.state is EventState.CLEARED and existing.state == EventState.TRIGGERED.value:
        existing.state = EventState.CLEARED.value
        existing.cleared_at = event.cleared_at
        existing.value = event.value
        existing.message = event.message
        existing.attributes = dict(event.attributes)
        jobs.append(("event.cleared", event.id))
        return EventIngestResult(event_id=event.id, status=IngestStatus.UPDATED)
    return EventIngestResult(event_id=event.id, status=IngestStatus.UNCHANGED)


def _new_row(device: DevicePrincipal, event: Event) -> EventRow:
    return EventRow(
        id=event.id,
        organisation_id=device.organisation_id,
        site_id=event.site_id,
        camera_id=event.camera_id,
        device_id=device.device_id,
        rule_id=event.rule_id,
        rule_type=event.rule_type.value,
        severity=event.severity.value,
        state=event.state.value,
        schema_version=event.schema_version,
        condition_started_at=event.condition_started_at,
        triggered_at=event.triggered_at,
        cleared_at=event.cleared_at,
        value=event.value,
        message=event.message,
        attributes=dict(event.attributes),
        needs_verification=event.needs_verification,
        edge_created_at=event.created_at,
        received_at=utcnow(),
    )


def _job(device: DevicePrincipal, event_id: str) -> dict[str, Any]:
    return {
        "organisation_id": device.organisation_id,
        "site_id": device.site_id,
        "event_id": event_id,
    }


def _device_event(db: Session, device: DevicePrincipal, event_id: str) -> EventRow:
    row = db.scalar(
        select(EventRow).where(EventRow.id == event_id, EventRow.site_id == device.site_id)
    )
    if row is None:
        raise not_found("event")
    return row


def _media_key(row: EventRow, kind: MediaKind) -> str:
    return event_media_key(
        row.organisation_id, row.site_id, row.camera_id, row.triggered_at, row.id, kind.value
    )


def upload_targets(
    db: Session,
    storage: ObjectStorage,
    settings: CloudSettings,
    device: DevicePrincipal,
    event_id: str,
    kinds: list[MediaKind],
) -> list[UploadTarget]:
    row = _device_event(db, device, event_id)
    site = db.scalar(select(Site).where(Site.id == row.site_id))
    if site is not None and site.events_only:
        raise AppError(409, "this site is events-only: snapshots and clips are not accepted")
    targets = []
    for kind in dict.fromkeys(kinds):  # de-duplicate, keep order
        key = _media_key(row, kind)
        signed = storage.presign_put(key, MEDIA_FILES[kind.value][1], settings.upload_url_ttl_s)
        targets.append(
            UploadTarget(
                kind=kind,
                key=key,
                url=signed.url,
                method=signed.method,
                headers=signed.headers,
                expires_at=signed.expires_at,
            )
        )
    return targets


def finalise_media(
    db: Session,
    storage: ObjectStorage,
    settings: CloudSettings,
    device: DevicePrincipal,
    event_id: str,
    req: FinaliseRequest,
    queue: JobQueue,
) -> EventMediaState:
    row = _device_event(db, device, event_id)
    limits = {
        MediaKind.SNAPSHOT: settings.max_snapshot_bytes,
        MediaKind.CLIP: settings.max_clip_bytes,
    }
    wanted = [
        k for k, flag in ((MediaKind.SNAPSHOT, req.snapshot), (MediaKind.CLIP, req.clip)) if flag
    ]
    for kind in wanted:
        key = _media_key(row, kind)
        size = storage.size(key)
        if size is None:
            raise AppError(409, f"{kind.value} has not been uploaded", code="media_missing")
        if size > limits[kind]:
            storage.delete(key)
            raise AppError(413, f"{kind.value} is larger than {limits[kind]} bytes")
        if kind is MediaKind.SNAPSHOT:
            row.snapshot_key = key
        else:
            row.clip_key = key
    if wanted:
        queue.enqueue("event.media_ready", _job(device, event_id))
    return EventMediaState(event_id=row.id, snapshot_key=row.snapshot_key, clip_key=row.clip_key)


def ingest_aggregates(db: Session, device: DevicePrincipal, rows: list[AggregateRow]) -> int:
    camera_ids = {r.camera_id for r in rows}
    known = set(
        db.scalars(
            select(Camera.id).where(Camera.id.in_(camera_ids), Camera.site_id == device.site_id)
        ).all()
    )
    unknown = sorted(camera_ids - known)
    if unknown:
        raise AppError(422, f"unknown camera(s) for this site: {', '.join(unknown[:5])}")
    # Last value wins for the same (camera, minute, metric, target) inside one batch.
    dedup: dict[tuple[str, datetime, str, str], AggregateRow] = {}
    for r in rows:
        dedup[(r.camera_id, r.minute, r.metric.value, r.target)] = r
    values = [
        {
            "id": new_id(),
            "organisation_id": device.organisation_id,
            "site_id": device.site_id,
            "camera_id": r.camera_id,
            "minute": r.minute,
            "metric": r.metric.value,
            "target": r.target,
            "value": r.value,
        }
        for r in dedup.values()
    ]
    dialect = db.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    stmt = insert(AggregateMinute)
    stmt = stmt.on_conflict_do_update(
        index_elements=["camera_id", "minute", "metric", "target"],
        set_={"value": stmt.excluded.value},
    )
    for start in range(0, len(values), 1000):
        db.execute(stmt, values[start : start + 1000])
    return len(values)
