"""Background job hook (CLD-17 basics).

The API only *enqueues*: "event.created" and "event.media_ready" jobs for the alert dispatcher
(CLD-08). The Redis-backed queue, worker, retries and dead-letter handling are CLD-17 proper; they
will implement this same `JobQueue` protocol so callers do not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


class JobQueue(Protocol):
    def enqueue(self, job: str, payload: dict[str, Any]) -> None: ...


class LoggingQueue:
    """Default until CLD-17: records that a job would run. Never raises."""

    def enqueue(self, job: str, payload: dict[str, Any]) -> None:
        log.info("job.enqueued", job=job, **payload)


@dataclass
class InMemoryQueue:
    """Collects jobs in a list (tests)."""

    jobs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def enqueue(self, job: str, payload: dict[str, Any]) -> None:
        self.jobs.append((job, dict(payload)))
