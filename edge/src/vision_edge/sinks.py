"""Where events go.

- `ConsoleSink`  : structured log line per event (always on)
- `OutboxSink`   : events as JSONL + snapshot/clip files on disk; the uploader (EDG-12) ships this
                   outbox to the cloud. Until then it is also the local record of what happened.
- `TelegramSink` : development alerts to a Telegram group (bot token and chat id from settings)
- `MemorySink`   : collects events in memory (tests, evaluation harness)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import httpx
import structlog

from vision_shared.schemas import Event, EventState

log = structlog.get_logger(__name__)


class EventSink(Protocol):
    def emit(self, event: Event, snapshot: bytes | None) -> None: ...

    def update(self, event: Event, clip: Path | None = None) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.events: dict[str, Event] = {}
        self.order: list[str] = []
        self.snapshots: dict[str, bytes] = {}
        self.clips: dict[str, Path] = {}

    def emit(self, event: Event, snapshot: bytes | None) -> None:
        self.events[event.id] = event
        self.order.append(event.id)
        if snapshot:
            self.snapshots[event.id] = snapshot

    def update(self, event: Event, clip: Path | None = None) -> None:
        self.events[event.id] = event
        if clip:
            self.clips[event.id] = clip

    @property
    def triggered(self) -> list[Event]:
        return [self.events[i] for i in self.order]


class ConsoleSink:
    def emit(self, event: Event, snapshot: bytes | None) -> None:
        log.info(
            "event.triggered",
            site_id=event.site_id,
            camera_id=event.camera_id,
            rule_id=event.rule_id,
            severity=event.severity.value,
            message=event.message,
            at=event.triggered_at.isoformat(),
        )

    def update(self, event: Event, clip: Path | None = None) -> None:
        if event.state is EventState.CLEARED:
            log.info(
                "event.cleared",
                rule_id=event.rule_id,
                event_id=event.id,
                at=event.cleared_at.isoformat() if event.cleared_at else None,
            )
        if clip:
            log.info("event.clip_ready", event_id=event.id, clip=str(clip))


class OutboxSink:
    """Appends every event version to `events.jsonl` and stores media next to it."""

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        (self.dir / "media").mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "events.jsonl"

    def _append(self, event: Event) -> None:
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")

    def emit(self, event: Event, snapshot: bytes | None) -> None:
        if snapshot:
            key = f"media/{event.id}.jpg"
            (self.dir / key).write_bytes(snapshot)
            event.snapshot_key = key
        self._append(event)

    def update(self, event: Event, clip: Path | None = None) -> None:
        if clip:
            target = self.dir / "media" / clip.name
            if clip.resolve() != target.resolve():
                target.write_bytes(clip.read_bytes())
            event.clip_key = f"media/{clip.name}"
        self._append(event)


class TelegramSink:
    """Sends the snapshot with the alert text; sends the clip when it is ready."""

    def __init__(self, bot_token: str, chat_id: str, timeout_s: float = 10.0) -> None:
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._chat = chat_id
        self._client = httpx.Client(timeout=timeout_s)

    def _caption(self, event: Event) -> str:
        sev = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(event.severity.value, "")
        return f"{sev} {event.message}\nCamera {event.camera_id} · rule {event.rule_id}"

    def emit(self, event: Event, snapshot: bytes | None) -> None:
        try:
            if snapshot:
                self._client.post(
                    f"{self._base}/sendPhoto",
                    data={"chat_id": self._chat, "caption": self._caption(event)},
                    files={"photo": ("snapshot.jpg", snapshot, "image/jpeg")},
                ).raise_for_status()
            else:
                self._client.post(
                    f"{self._base}/sendMessage",
                    data={"chat_id": self._chat, "text": self._caption(event)},
                ).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("telegram.send_failed", error=str(exc), event_id=event.id)

    def update(self, event: Event, clip: Path | None = None) -> None:
        if not clip:
            return
        try:
            with clip.open("rb") as fh:
                self._client.post(
                    f"{self._base}/sendVideo",
                    data={"chat_id": self._chat, "caption": f"Clip: {event.message}"},
                    files={"video": (clip.name, fh, "video/mp4")},
                ).raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            log.warning("telegram.clip_failed", error=str(exc), event_id=event.id)
