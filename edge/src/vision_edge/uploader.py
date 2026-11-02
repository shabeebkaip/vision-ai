"""Ships the outbox to the cloud (EDG-12).

`Uploader.drain()` sends everything it can and returns; `Uploader.run_forever()` repeats it with
backoff; `UploaderThread` runs that next to the pipeline inside `vision-edge run`.

Per drain:
1. events, oldest first, in batches to `POST /device/v1/events/batch`. Per-item results: created,
   updated or unchanged = delivered; rejected = parked as failed (logged, never retried) so one bad
   event cannot block the queue.
2. media for delivered events, oldest first: `POST /events/{id}/uploads` for a pre-signed URL,
   `PUT` the file there, `POST /events/{id}/finalise`.

Network errors, 5xx and 429 stop the drain; the caller backs off (1 s doubling to 5 min) and tries
again, so after an outage everything is delivered once, in order. 401 means the device token was
revoked or is wrong: logged loudly, retried at the maximum backoff.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import structlog

from vision_edge.outbox import Op, OpKind, OpStatus, Outbox
from vision_shared.api import (
    EventBatch,
    EventBatchResult,
    FinaliseRequest,
    IngestStatus,
    MediaKind,
    UploadRequest,
    UploadResponse,
)

log = structlog.get_logger(__name__)

MAX_MEDIA_ATTEMPTS = 20


class RetryLater(Exception):
    """The cloud is unreachable or overloaded: stop this drain and back off."""


class Unauthorised(RetryLater):
    pass


@dataclass
class DrainResult:
    events_sent: int = 0
    events_failed: int = 0
    media_sent: int = 0
    media_dropped: int = 0


class CloudClient:
    """Thin client for the device API. `http` may be any `httpx.Client` (tests pass a mock or a
    FastAPI TestClient); pre-signed uploads go through `uploads`, which never sends the token."""

    def __init__(
        self,
        base_url: str,
        device_token: str,
        *,
        http: httpx.Client | None = None,
        uploads: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {device_token}"}
        self._http = http or httpx.Client(timeout=timeout_s)
        self._uploads = uploads or self._http

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code == 401:
            raise Unauthorised("device token rejected (401): re-enrol the box")
        if r.status_code == 429 or r.status_code >= 500:
            raise RetryLater(f"cloud answered {r.status_code}")
        return r

    def _post(self, path: str, body: str) -> httpx.Response:
        try:
            r = self._http.post(
                f"{self._base}/device/v1{path}",
                content=body,
                headers={**self._headers, "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise RetryLater(f"{type(exc).__name__}: {exc}") from exc
        return self._check(r)

    def send_events(self, ops: list[Op]) -> EventBatchResult:
        batch = EventBatch(events=[op.event() for op in ops])
        r = self._post("/events/batch", batch.model_dump_json())
        r.raise_for_status()
        return EventBatchResult.model_validate_json(r.content)

    def upload_targets(self, event_id: str, kind: MediaKind) -> httpx.Response:
        return self._post(
            f"/events/{event_id}/uploads", UploadRequest(kinds=[kind]).model_dump_json()
        )

    def put(self, url: str, headers: dict[str, str], data: bytes) -> httpx.Response:
        try:
            r = self._uploads.put(url, content=data, headers=headers)
        except httpx.HTTPError as exc:
            raise RetryLater(f"upload {type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise RetryLater(f"storage answered {r.status_code}")
        return r

    def finalise(self, event_id: str, kind: MediaKind) -> httpx.Response:
        body = FinaliseRequest(
            snapshot=kind is MediaKind.SNAPSHOT, clip=kind is MediaKind.CLIP
        ).model_dump_json()
        return self._post(f"/events/{event_id}/finalise", body)


class Uploader:
    def __init__(self, outbox: Outbox, client: CloudClient, *, batch_size: int = 100) -> None:
        self.outbox = outbox
        self.client = client
        self.batch_size = batch_size

    # ------------------------------------------------------------------ one pass
    def drain(self) -> DrainResult:
        """Send everything currently sendable. Raises RetryLater when the cloud is unreachable."""
        result = DrainResult()
        while True:
            ops = self.outbox.pending_events(self.batch_size)
            if not ops:
                break
            self._send_events(ops, result)
        for orphan in self.outbox.orphan_media():
            self.outbox.mark([orphan.seq], OpStatus.DROPPED, "event refused by the cloud")
            result.media_dropped += 1
        after = 0
        while (media := self.outbox.next_media(after)) is not None:
            self._send_media(media, result)
            after = media.seq
        self.outbox.purge()
        return result

    def _send_events(self, ops: list[Op], result: DrainResult) -> None:
        try:
            outcome = self.client.send_events(ops)
        except RetryLater as exc:
            self.outbox.record_attempt([o.seq for o in ops], str(exc))
            raise
        except httpx.HTTPStatusError as exc:
            # The whole batch was refused (e.g. 413/422). Fall back to one at a time so a single
            # malformed event is isolated instead of blocking everything behind it.
            if len(ops) > 1:
                for op in ops:
                    self._send_events([op], result)
                return
            self.outbox.mark([ops[0].seq], OpStatus.FAILED, f"HTTP {exc.response.status_code}")
            log.error("uploader.event_refused", event_id=ops[0].event_id, error=str(exc))
            result.events_failed += 1
            return
        by_id = {r.event_id: r for r in outcome.results}
        done: list[int] = []
        failed = 0
        for op in ops:
            r = by_id.get(op.event_id)
            if r is None:  # not in the answer: try again next drain
                continue
            if r.status is IngestStatus.REJECTED:
                self.outbox.mark([op.seq], OpStatus.FAILED, r.error)
                log.error("uploader.event_refused", event_id=op.event_id, error=r.error)
                failed += 1
            else:
                done.append(op.seq)
        self.outbox.mark(done, OpStatus.DONE)
        result.events_sent += len(done)
        result.events_failed += failed
        if len(done) + failed < len(ops):
            raise RetryLater("cloud answered for only part of the batch")

    def _drop(self, op: Op, reason: str, result: DrainResult) -> None:
        self.outbox.mark([op.seq], OpStatus.DROPPED, reason)
        result.media_dropped += 1
        log.warning(
            "uploader.media_dropped", event_id=op.event_id, kind=op.kind.value, reason=reason
        )

    def _send_media(self, op: Op, result: DrainResult) -> None:
        kind = MediaKind.SNAPSHOT if op.kind is OpKind.SNAPSHOT else MediaKind.CLIP
        path = self.outbox.media_path(op)
        if not path.is_file():
            self._drop(op, "file missing", result)
            return
        if op.attempts >= MAX_MEDIA_ATTEMPTS:
            self._drop(op, f"gave up after {op.attempts} attempts", result)
            return
        try:
            r = self.client.upload_targets(op.event_id, kind)
            if r.status_code in (404, 409):  # event unknown, or site is events-only
                self._drop(op, f"uploads refused ({r.status_code}): {r.text[:200]}", result)
                return
            r.raise_for_status()
            target = UploadResponse.model_validate_json(r.content).uploads[0]
            put = self.client.put(target.url, target.headers, path.read_bytes())
            put.raise_for_status()
            fin = self.client.finalise(op.event_id, kind)
            if fin.status_code == 413:
                self._drop(op, "larger than the cloud accepts", result)
                return
            fin.raise_for_status()
        except RetryLater as exc:
            self.outbox.record_attempt([op.seq], str(exc))
            raise
        except httpx.HTTPStatusError as exc:
            # Unexpected 4xx: count it and move on; the op is retried in the next drain.
            self.outbox.record_attempt([op.seq], f"HTTP {exc.response.status_code}")
            log.warning("uploader.media_error", event_id=op.event_id, error=str(exc))
            return
        self.outbox.mark([op.seq], OpStatus.DONE)
        result.media_sent += 1

    # ------------------------------------------------------------------ loop
    def run_forever(
        self,
        stop: threading.Event,
        *,
        idle_s: float = 2.0,
        min_backoff_s: float = 1.0,
        max_backoff_s: float = 300.0,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        wait = sleep or stop.wait
        backoff = min_backoff_s
        while not stop.is_set():
            try:
                res = self.drain()
            except Unauthorised as exc:
                log.error("uploader.unauthorised", error=str(exc))
                backoff = max_backoff_s
                wait(backoff)
                continue
            except RetryLater as exc:
                s = self.outbox.stats()
                log.warning(
                    "uploader.offline",
                    error=str(exc),
                    retry_in_s=round(backoff, 1),
                    pending_events=s.pending_events,
                    pending_media=s.pending_media,
                )
                wait(backoff * random.uniform(0.8, 1.2))
                backoff = min(backoff * 2, max_backoff_s)
                continue
            if res.events_sent or res.media_sent:
                log.info("uploader.sent", events=res.events_sent, media=res.media_sent)
            backoff = min_backoff_s
            wait(idle_s)


class UploaderThread:
    """Runs `Uploader.run_forever` in a daemon thread next to the pipeline."""

    def __init__(self, uploader: Uploader) -> None:
        self.uploader = uploader
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="uploader", daemon=True)

    def _run(self) -> None:
        self.uploader.run_forever(self._stop)

    def start(self) -> None:
        self._thread.start()

    def stop(self, flush_timeout_s: float = 10.0) -> None:
        """Stop the loop, then try one last drain so a clean shutdown leaves little behind."""
        self._stop.set()
        self._thread.join(timeout=flush_timeout_s)
        try:
            self.uploader.drain()
        except RetryLater as exc:
            log.warning("uploader.left_pending", error=str(exc))
