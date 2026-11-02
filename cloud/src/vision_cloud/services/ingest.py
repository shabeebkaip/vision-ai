"""Event and aggregate ingest (CLD-05).

Idempotency: the edge-generated event UUID is the key. The first submission inserts the event;
later submissions of the same id either move it forward (triggered -> cleared, clip ready) or are
reported as duplicates. Batches are inserted with one `INSERT ... ON CONFLICT DO NOTHING`, so a
10,000-event burst costs a handful of statements per batch rather than one round trip per event.

Media: the edge's `snapshot_key` / `clip_key` are local outbox paths; they only tell us media exists.
The cloud assigns its own storage key and returns a pre-signed upload form; the edge uploads and
then calls finalise. Sites flagged `events_only` never get upload forms.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from vision_cloud import models as m
from vision_cloud.contract import (
    AggregateMinute,
    EventReceipt,
    IngestStatus,
    MediaKind,
    RejectedItem,
    UploadTarget,
)
from vision_cloud.errors import APIError
from vision_cloud.settings import CloudSettings
from vision_cloud.storage import CLIP_TYPE, SNAPSHOT_TYPE, ObjectStore, event_media_key
from vision_shared.schemas import Event, EventState


@dataclass
class IngestResult:
    receipts: list[EventReceipt] = field(default_factory=list)
    rejected: list[RejectedItem] = field(default_factory=list)


def _reject(index: int, ev_id: str | None, code: str, message: str) -> RejectedItem:
    return RejectedItem(index=index, id=ev_id, code=code, message=message)


def parse_events(items: list[dict[str, Any]], result: IngestResult) -> list[tuple[int, Event]]:
    parsed: list[tuple[int, Event]] = []
    for i, raw in enumerate(items):
        try:
            parsed.append((i, Event.model_validate(raw)))
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            ev_id = raw.get("id") if isinstance(raw, dict) else None
            result.rejected.append(
                _reject(i, str(ev_id) if ev_id else None, "invalid_event", f"{loc}: {first['msg']}")
            )
    return parsed


class EventIngestor:
    def __init__(
        self,
        db: Session,
        device: m.Device,
        site: m.Site,
        store: ObjectStore,
        settings: CloudSettings,
    ) -> None:
        self.db = db
        self.device = device
        self.site = site
        self.store = store
        self.settings = settings
        self.cameras = {
            c.key: c for c in db.scalars(select(m.Camera).where(m.Camera.site_id == site.id))
        }
        self.rules = {r.key: r for r in db.scalars(select(m.Rule).where(m.Rule.site_id == site.id))}

    # ------------------------------------------------------------------ helpers

    def _media_wanted(self, edge_key: str | None) -> bool:
        return bool(edge_key) and not self.site.events_only

    def _upload(self, row: m.EventRow, kind: MediaKind) -> UploadTarget:
        key = row.snapshot_key if kind is MediaKind.SNAPSHOT else row.clip_key
        assert key is not None
        if kind is MediaKind.SNAPSHOT:
            post = self.store.presign_post(
                key, SNAPSHOT_TYPE, self.settings.max_snapshot_bytes, self.settings.upload_url_ttl_s
            )
        else:
            post = self.store.presign_post(
                key, CLIP_TYPE, self.settings.max_clip_bytes, self.settings.upload_url_ttl_s
            )
        return UploadTarget(
            url=post.url,
            fields=post.fields,
            key=post.key,
            expires_at=post.expires_at,
            max_bytes=post.max_bytes,
        )

    def _receipt(self, row: m.EventRow, status: IngestStatus) -> EventReceipt:
        return EventReceipt(
            event_id=str(row.id),
            status=status,
            snapshot_upload=(
                self._upload(row, MediaKind.SNAPSHOT)
                if row.snapshot_state is m.MediaState.PENDING
                else None
            ),
            clip_upload=(
                self._upload(row, MediaKind.CLIP)
                if row.clip_state is m.MediaState.PENDING
                else None
            ),
        )

    def _values(self, ev: Event, event_id: uuid.UUID, camera: m.Camera) -> dict[str, Any]:
        rule = self.rules.get(ev.rule_id)
        snap = self._media_wanted(ev.snapshot_key)
        clip = self._media_wanted(ev.clip_key)
        org = self.site.organisation_id

        def key(kind: str) -> str:
            return event_media_key(org, self.site.id, camera.id, ev.triggered_at, event_id, kind)

        return {
            "id": event_id,
            "organisation_id": org,
            "site_id": self.site.id,
            "camera_id": camera.id,
            "rule_id": rule.id if rule else None,
            "device_id": self.device.id,
            "rule_key": ev.rule_id,
            "rule_type": ev.rule_type,
            "severity": ev.severity,
            "state": ev.state,
            "status": m.EventStatus.NEW,
            "condition_started_at": ev.condition_started_at,
            "triggered_at": ev.triggered_at,
            "cleared_at": ev.cleared_at,
            "value": ev.value,
            "message": ev.message,
            "attributes": ev.attributes,
            "needs_verification": ev.needs_verification,
            "schema_version": ev.schema_version,
            "snapshot_key": key("snapshot") if snap else None,
            "snapshot_state": m.MediaState.PENDING if snap else m.MediaState.NONE,
            "clip_key": key("clip") if clip else None,
            "clip_state": m.MediaState.PENDING if clip else m.MediaState.NONE,
            "edge_created_at": ev.created_at,
        }

    def _merge(self, row: m.EventRow, ev: Event, camera: m.Camera) -> bool:
        """Apply a later version of an event. Returns True if anything changed."""
        changed = False
        # An older version arriving late must not undo the cleared state.
        stale = row.state is EventState.CLEARED and ev.state is EventState.TRIGGERED
        if not stale:
            if ev.state is EventState.CLEARED and row.state is EventState.TRIGGERED:
                row.state = EventState.CLEARED
                row.cleared_at = ev.cleared_at
                changed = True
            for attr in ("value", "message", "attributes"):
                new = getattr(ev, attr)
                if getattr(row, attr) != new:
                    setattr(row, attr, new)
                    changed = True
        if self._media_wanted(ev.snapshot_key) and row.snapshot_state is m.MediaState.NONE:
            row.snapshot_key = event_media_key(
                row.organisation_id, row.site_id, camera.id, row.triggered_at, row.id, "snapshot"
            )
            row.snapshot_state = m.MediaState.PENDING
            changed = True
        if self._media_wanted(ev.clip_key) and row.clip_state is m.MediaState.NONE:
            row.clip_key = event_media_key(
                row.organisation_id, row.site_id, camera.id, row.triggered_at, row.id, "clip"
            )
            row.clip_state = m.MediaState.PENDING
            changed = True
        return changed

    # ------------------------------------------------------------------ entry point

    def ingest(self, events: list[tuple[int, Event]], result: IngestResult) -> None:
        accepted: list[tuple[int, Event, uuid.UUID, m.Camera]] = []
        for index, ev in events:
            if ev.site_id != self.site.key:
                result.rejected.append(
                    _reject(index, ev.id, "site_mismatch", "event is for another site")
                )
                continue
            camera = self.cameras.get(ev.camera_id)
            if camera is None:
                result.rejected.append(
                    _reject(index, ev.id, "unknown_camera", f"no camera {ev.camera_id!r}")
                )
                continue
            try:
                event_id = uuid.UUID(ev.id)
            except ValueError:
                result.rejected.append(_reject(index, ev.id, "invalid_id", "id must be a UUID"))
                continue
            accepted.append((index, ev, event_id, camera))
        if not accepted:
            return

        # 1. Insert the first version of every id in one statement; existing ids are skipped.
        first: dict[uuid.UUID, dict[str, Any]] = {}
        for _, ev, event_id, camera in accepted:
            first.setdefault(event_id, self._values(ev, event_id, camera))
        created = set(
            self.db.scalars(
                pg_insert(m.EventRow)
                .values(list(first.values()))
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(m.EventRow.id)
            ).all()
        )

        # 2. Load every touched row (RLS hides rows of other organisations).
        rows = {
            r.id: r
            for r in self.db.scalars(
                select(m.EventRow).where(m.EventRow.id.in_(list(first))).with_for_update()
            )
        }

        # 3. Apply later versions in submission order and build one receipt per submitted item.
        seen: set[uuid.UUID] = set()
        statuses: dict[int, IngestStatus] = {}
        for index, ev, event_id, camera in accepted:
            row = rows.get(event_id)
            if row is None or row.site_id != self.site.id or row.camera_id != camera.id:
                result.rejected.append(
                    _reject(index, ev.id, "id_conflict", "event id already used elsewhere")
                )
                continue
            if event_id in created and event_id not in seen:
                statuses[index] = IngestStatus.CREATED
            else:
                statuses[index] = (
                    IngestStatus.UPDATED if self._merge(row, ev, camera) else IngestStatus.DUPLICATE
                )
            seen.add(event_id)
        self.db.flush()
        for index, _ev, event_id, _ in accepted:
            if index in statuses:
                result.receipts.append(self._receipt(rows[event_id], statuses[index]))


def finalise_media(
    db: Session, store: ObjectStore, settings: CloudSettings, row: m.EventRow, kind: MediaKind
) -> int:
    """Mark an uploaded snapshot or clip as stored after checking the object exists."""
    state = row.snapshot_state if kind is MediaKind.SNAPSHOT else row.clip_state
    key = row.snapshot_key if kind is MediaKind.SNAPSHOT else row.clip_key
    if state is m.MediaState.NONE or key is None:
        raise APIError(409, "media_not_expected", f"no {kind.value} expected for this event")
    obj = store.head(key)
    if obj is None:
        raise APIError(409, "media_not_uploaded", f"{kind.value} has not been uploaded")
    if kind is MediaKind.SNAPSHOT:
        row.snapshot_state = m.MediaState.STORED
    else:
        row.clip_state = m.MediaState.STORED
    return obj.size


def ingest_aggregates(
    db: Session, site: m.Site, items: list[AggregateMinute]
) -> list[RejectedItem]:
    cameras = {c.key: c.id for c in db.scalars(select(m.Camera).where(m.Camera.site_id == site.id))}
    rejected: list[RejectedItem] = []
    rows: dict[tuple[uuid.UUID, Any], dict[str, Any]] = {}
    for i, item in enumerate(items):
        cam_id = cameras.get(item.camera_id)
        if cam_id is None:
            rejected.append(_reject(i, item.camera_id, "unknown_camera", "no such camera"))
            continue
        rows[(cam_id, item.minute)] = {
            "organisation_id": site.organisation_id,
            "site_id": site.id,
            "camera_id": cam_id,
            **item.model_dump(exclude={"camera_id"}),
        }
    if rows:
        stmt = pg_insert(m.AggregateMinute).values(list(rows.values()))
        update_cols = [
            "occupancy_avg",
            "occupancy_max",
            "entries",
            "exits",
            "queue_length_max",
            "dwell_avg_s",
            "dwell_max_s",
            "attributes",
        ]
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=["camera_id", "minute"],
                set_={c: stmt.excluded[c] for c in update_cols},
            )
        )
    return rejected
