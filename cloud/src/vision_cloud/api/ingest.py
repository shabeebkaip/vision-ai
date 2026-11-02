"""Event ingest API (CLD-05): idempotent create, batch, media finalise, per-minute aggregates."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Response

from vision_cloud import models as m
from vision_cloud.api.deps import DB, CurrentDevice, Settings, Store
from vision_cloud.contract import (
    AggregateBatch,
    AggregateReceipt,
    EventBatch,
    EventBatchReceipt,
    EventReceipt,
    IngestStatus,
    MediaFinalised,
    MediaKind,
    RejectedItem,
)
from vision_cloud.errors import APIError, not_found
from vision_cloud.services.ingest import (
    EventIngestor,
    IngestResult,
    finalise_media,
    ingest_aggregates,
    parse_events,
)

router = APIRouter(prefix="/device/v1", tags=["device"])


def _raise_single(rejected: list[RejectedItem]) -> None:
    item = rejected[0]
    status = 409 if item.code == "id_conflict" else 422
    raise APIError(status, item.code, item.message)


@router.post(
    "/events",
    response_model=EventReceipt,
    responses={201: {"description": "created"}, 200: {"description": "updated or duplicate"}},
)
def submit_event(
    ctx: CurrentDevice,
    db: DB,
    store: Store,
    settings: Settings,
    response: Response,
    event: Annotated[dict[str, Any], Body(description="a vision_shared.schemas.Event")],
) -> EventReceipt:
    """Submit one event (or a later version of it). Safe to retry: the event id is the key."""
    result = IngestResult()
    parsed = parse_events([event], result)
    if parsed:
        EventIngestor(db, ctx.device, ctx.site, store, settings).ingest(parsed, result)
    if result.rejected:
        db.rollback()
        _raise_single(result.rejected)
    db.commit()
    receipt = result.receipts[0]
    response.status_code = 201 if receipt.status is IngestStatus.CREATED else 200
    return receipt


@router.post("/events/batch", response_model=EventBatchReceipt)
def submit_events(
    body: EventBatch, ctx: CurrentDevice, db: DB, store: Store, settings: Settings
) -> EventBatchReceipt:
    """Submit up to `VISION_MAX_BATCH_EVENTS` events. Bad items are rejected one by one; the rest
    are stored. Retrying the whole batch is safe."""
    if len(body.events) > settings.max_batch_events:
        raise APIError(413, "batch_too_large", f"at most {settings.max_batch_events} events")
    result = IngestResult()
    parsed = parse_events(body.events, result)
    if parsed:
        EventIngestor(db, ctx.device, ctx.site, store, settings).ingest(parsed, result)
    db.commit()
    result.rejected.sort(key=lambda r: r.index)
    return EventBatchReceipt(receipts=result.receipts, rejected=result.rejected)


@router.post("/events/{event_id}/media/{kind}/finalise", response_model=MediaFinalised)
def finalise(
    event_id: uuid.UUID,
    kind: MediaKind,
    ctx: CurrentDevice,
    db: DB,
    store: Store,
    settings: Settings,
) -> MediaFinalised:
    row = db.get(m.EventRow, event_id, with_for_update=True)
    if row is None or row.site_id != ctx.site.id:
        raise not_found("event")
    size = finalise_media(db, store, settings, row, kind)
    db.commit()
    key = row.snapshot_key if kind is MediaKind.SNAPSHOT else row.clip_key
    assert key is not None
    return MediaFinalised(event_id=str(row.id), kind=kind, key=key, size_bytes=size)


@router.post("/aggregates", response_model=AggregateReceipt)
def submit_aggregates(
    body: AggregateBatch, ctx: CurrentDevice, db: DB, settings: Settings
) -> AggregateReceipt:
    """Per-minute counts. Re-sending a minute replaces it (idempotent)."""
    if len(body.items) > settings.max_batch_aggregates:
        raise APIError(413, "batch_too_large", f"at most {settings.max_batch_aggregates} items")
    if body.site_id != ctx.site.key:
        raise APIError(422, "site_mismatch", "aggregates are for another site")
    rejected = ingest_aggregates(db, ctx.site, body.items)
    db.commit()
    return AggregateReceipt(accepted=len(body.items) - len(rejected), rejected=rejected)
