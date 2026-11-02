"""Durable outbox on the edge box (EDG-12): every event version and media file to send to the cloud.

One SQLite file per outbox directory (`outbox.db`, WAL mode) holds an ordered queue of operations:

- `event`    one version of an event (triggered, then possibly cleared), as the shared `Event` JSON
- `snapshot` / `clip`  a media file in `media/` to upload for an event that is already delivered

Delivery rules (enforced by `vision_edge.uploader`):

- events go out strictly in the order they were queued (`seq`); media never delays an event
- media for an event goes out after that event is delivered, in queue order
- nothing is lost while offline: undelivered events are never deleted. Clips are the only thing
  that can be dropped, oldest first, when they exceed the disk quota; the event is still sent
- delivered rows are purged after the retention period (7 days by default)

The cloud de-duplicates by `Event.id`, so re-sending after a lost response is harmless.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import structlog

from vision_shared.schemas import Event

log = structlog.get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,              -- event | snapshot | clip
    event_id    TEXT NOT NULL,
    payload     TEXT,                       -- event JSON for kind=event
    path        TEXT,                       -- media file, relative to the outbox directory
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  REAL NOT NULL,
    done_at     REAL
);
CREATE INDEX IF NOT EXISTS ops_pending ON ops (status, kind, seq);
CREATE INDEX IF NOT EXISTS ops_event ON ops (event_id, kind);
"""


class OpKind(str, Enum):
    EVENT = "event"
    SNAPSHOT = "snapshot"
    CLIP = "clip"


class OpStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"  # accepted by the cloud
    FAILED = "failed"  # the cloud refused it for good (kept for inspection, never retried)
    DROPPED = "dropped"  # media given up: quota, file missing, event refused, site events-only


@dataclass(frozen=True)
class Op:
    seq: int
    kind: OpKind
    event_id: str
    payload: str | None
    path: str | None
    attempts: int

    def event(self) -> Event:
        assert self.payload is not None
        return Event.model_validate_json(self.payload)


@dataclass(frozen=True)
class OutboxStats:
    pending_events: int
    pending_media: int
    failed: int
    dropped: int
    clip_bytes: int


class Outbox:
    """Thread-safe: the pipeline queues from its thread, the uploader drains from another."""

    def __init__(
        self,
        directory: str | Path,
        *,
        clip_quota_bytes: int = 2 * 1024**3,
        retention_s: float = 7 * 24 * 3600,
        clock: object = time.time,
    ) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clip_quota_bytes = clip_quota_bytes
        self.retention_s = retention_s
        self._clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(
            self.dir / "outbox.db", check_same_thread=False, isolation_level=None, timeout=30
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")  # durable across process crashes
        self._db.executescript(SCHEMA)

    def _now(self) -> float:
        return float(self._clock())  # type: ignore[operator]

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ queueing (pipeline side)
    def add_event(self, event: Event) -> None:
        """Queue this version of the event unless the same state is already queued."""
        with self._lock:
            last = self._db.execute(
                "SELECT payload FROM ops WHERE event_id = ? AND kind = 'event' "
                "ORDER BY seq DESC LIMIT 1",
                (event.id,),
            ).fetchone()
            if last is not None and Event.model_validate_json(last[0]).state is event.state:
                return
            self._db.execute(
                "INSERT INTO ops (kind, event_id, payload, created_at) VALUES ('event', ?, ?, ?)",
                (event.id, event.model_dump_json(), self._now()),
            )

    def add_media(self, event_id: str, kind: OpKind, path: str | Path) -> None:
        """Queue a media file (relative to the outbox directory, or absolute inside it)."""
        if kind is OpKind.EVENT:
            raise ValueError("use add_event for events")
        p = Path(path)
        rel = p.relative_to(self.dir) if p.is_absolute() else p
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM ops WHERE event_id = ? AND kind = ?", (event_id, kind.value)
            ).fetchone()
            if exists:
                return
            self._db.execute(
                "INSERT INTO ops (kind, event_id, path, created_at) VALUES (?, ?, ?, ?)",
                (kind.value, event_id, str(rel), self._now()),
            )
        if kind is OpKind.CLIP:
            self.enforce_clip_quota()

    # ------------------------------------------------------------------ draining (uploader side)
    def _rows(self, sql: str, args: tuple[object, ...]) -> list[Op]:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [Op(r[0], OpKind(r[1]), r[2], r[3], r[4], r[5]) for r in rows]

    def pending_events(self, limit: int) -> list[Op]:
        return self._rows(
            "SELECT seq, kind, event_id, payload, path, attempts FROM ops "
            "WHERE status = 'pending' AND kind = 'event' ORDER BY seq LIMIT ?",
            (limit,),
        )

    def next_media(self, after_seq: int = 0) -> Op | None:
        """Oldest pending media after `after_seq` whose event has been delivered (and has no
        earlier event version still pending)."""
        rows = self._rows(
            "SELECT m.seq, m.kind, m.event_id, m.payload, m.path, m.attempts FROM ops m "
            "WHERE m.status = 'pending' AND m.kind != 'event' AND m.seq > ? "
            "AND EXISTS (SELECT 1 FROM ops e WHERE e.event_id = m.event_id AND e.kind = 'event' "
            "            AND e.status = 'done') "
            "AND NOT EXISTS (SELECT 1 FROM ops e WHERE e.event_id = m.event_id "
            "                AND e.kind = 'event' AND e.status = 'pending' AND e.seq < m.seq) "
            "ORDER BY m.seq LIMIT 1",
            (after_seq,),
        )
        return rows[0] if rows else None

    def orphan_media(self) -> list[Op]:
        """Pending media whose event the cloud refused: they can never be uploaded."""
        return self._rows(
            "SELECT m.seq, m.kind, m.event_id, m.payload, m.path, m.attempts FROM ops m "
            "WHERE m.status = 'pending' AND m.kind != 'event' "
            "AND EXISTS (SELECT 1 FROM ops e WHERE e.event_id = m.event_id AND e.kind = 'event' "
            "            AND e.status = 'failed') "
            "AND NOT EXISTS (SELECT 1 FROM ops e WHERE e.event_id = m.event_id "
            "                AND e.kind = 'event' AND e.status IN ('done', 'pending'))",
            (),
        )

    def mark(self, seqs: list[int], status: OpStatus, error: str | None = None) -> None:
        if not seqs:
            return
        marks = ",".join("?" * len(seqs))
        with self._lock:
            self._db.execute(
                f"UPDATE ops SET status = ?, last_error = ?, done_at = ? WHERE seq IN ({marks})",
                (status.value, error, self._now(), *seqs),
            )

    def record_attempt(self, seqs: list[int], error: str) -> None:
        if not seqs:
            return
        marks = ",".join("?" * len(seqs))
        with self._lock:
            self._db.execute(
                f"UPDATE ops SET attempts = attempts + 1, last_error = ? WHERE seq IN ({marks})",
                (error[:500], *seqs),
            )

    def media_path(self, op: Op) -> Path:
        assert op.path is not None
        return self.dir / op.path

    # ------------------------------------------------------------------ housekeeping
    def enforce_clip_quota(self) -> int:
        """Delete the oldest clip files until clips fit the quota. Returns bytes freed."""
        with self._lock:
            rows = self._db.execute(
                "SELECT seq, path, status FROM ops WHERE kind = 'clip' "
                "AND status IN ('pending', 'done') ORDER BY seq"
            ).fetchall()
        sizes = []
        for seq, rel, status in rows:
            f = self.dir / rel
            sizes.append((seq, f, status, f.stat().st_size if f.is_file() else 0))
        total = sum(s[3] for s in sizes)
        freed = 0
        for seq, f, status, size in sizes:
            if total <= self.clip_quota_bytes:
                break
            f.unlink(missing_ok=True)
            total -= size
            freed += size
            if status == OpStatus.PENDING.value:
                self.mark([seq], OpStatus.DROPPED, "clip quota exceeded")
            log.warning("outbox.clip_dropped", seq=seq, bytes=size, delivered=status == "done")
        return freed

    def purge(self) -> int:
        """Forget delivered, failed and dropped rows older than the retention period."""
        cutoff = self._now() - self.retention_s
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM ops WHERE status != 'pending' AND done_at IS NOT NULL AND done_at < ?",
                (cutoff,),
            )
        return int(cur.rowcount or 0)

    def stats(self) -> OutboxStats:
        with self._lock:
            row = self._db.execute(
                "SELECT "
                "SUM(status = 'pending' AND kind = 'event'), "
                "SUM(status = 'pending' AND kind != 'event'), "
                "SUM(status = 'failed'), SUM(status = 'dropped') FROM ops"
            ).fetchone()
            clips = self._db.execute(
                "SELECT path FROM ops WHERE kind = 'clip' AND status IN ('pending', 'done')"
            ).fetchall()
        clip_bytes = sum(
            (self.dir / p).stat().st_size for (p,) in clips if (self.dir / p).is_file()
        )
        return OutboxStats(
            pending_events=int(row[0] or 0),
            pending_media=int(row[1] or 0),
            failed=int(row[2] or 0),
            dropped=int(row[3] or 0),
            clip_bytes=clip_bytes,
        )
