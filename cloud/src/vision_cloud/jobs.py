"""Background jobs (CLD-17).

The API and other jobs only *enqueue* named jobs with a JSON payload ("event.created",
"event.media_ready", later "alert.escalate", ...). `vision_cloud.worker` holds the handlers and runs
them in `vision-cloud worker` processes.

- `RqQueue`      Redis + RQ (BSD-2). Used whenever `VISION_CLOUD_REDIS_URL` is set. Payloads are
                 JSON (never pickle). A failing job is retried `job_max_retries` times with the
                 configured intervals, then kept in RQ's failed-job registry (the dead-letter list)
                 with its traceback for `job_dead_letter_ttl_days`.
- `LoggingQueue` no Redis configured: logs that the job would run (local development, tests).
- `InMemoryQueue` collects jobs in a list (tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol

import structlog

if TYPE_CHECKING:
    from rq import Queue

    from vision_cloud.settings import CloudSettings

log = structlog.get_logger(__name__)

QUEUE_NAME = "vision"
RUN_JOB = "vision_cloud.worker.run_job"


class JobQueue(Protocol):
    def enqueue(self, job: str, payload: dict[str, Any]) -> None: ...

    def enqueue_in(
        self, delay_s: float, job: str, payload: dict[str, Any], *, job_id: str | None = None
    ) -> None: ...


class LoggingQueue:
    """Default without Redis: records that a job would run. Never raises."""

    def enqueue(self, job: str, payload: dict[str, Any]) -> None:
        log.info("job.enqueued", job=job, **payload)

    def enqueue_in(
        self, delay_s: float, job: str, payload: dict[str, Any], *, job_id: str | None = None
    ) -> None:
        log.info("job.scheduled", job=job, delay_s=delay_s, **payload)


@dataclass
class InMemoryQueue:
    """Collects jobs in a list (tests). Delayed jobs go to `delayed` with their delay."""

    jobs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    delayed: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)

    def enqueue(self, job: str, payload: dict[str, Any]) -> None:
        self.jobs.append((job, dict(payload)))

    def enqueue_in(
        self, delay_s: float, job: str, payload: dict[str, Any], *, job_id: str | None = None
    ) -> None:
        self.delayed.append((delay_s, job, dict(payload)))


class RqQueue:
    def __init__(
        self,
        redis_url: str,
        *,
        max_retries: int = 3,
        retry_intervals_s: list[int] | None = None,
        dead_letter_ttl_s: int = 30 * 24 * 3600,
        job_timeout_s: int = 120,
    ) -> None:
        from redis import Redis
        from rq import Queue
        from rq.serializers import JSONSerializer

        self.redis = Redis.from_url(redis_url)
        self.queue: Queue = Queue(QUEUE_NAME, connection=self.redis, serializer=JSONSerializer)
        self.max_retries = max_retries
        self.retry_intervals_s = (
            retry_intervals_s if retry_intervals_s is not None else [10, 60, 300]
        )
        self.dead_letter_ttl_s = dead_letter_ttl_s
        self.job_timeout_s = job_timeout_s

    def _options(self, job: str, job_id: str | None) -> dict[str, Any]:
        from rq import Retry

        opts: dict[str, Any] = {
            "description": job,
            "failure_ttl": self.dead_letter_ttl_s,
            "job_timeout": self.job_timeout_s,
            "result_ttl": 3600,
        }
        if self.max_retries > 0:
            opts["retry"] = Retry(max=self.max_retries, interval=self.retry_intervals_s)
        if job_id:
            opts["job_id"] = job_id
        return opts

    def enqueue(self, job: str, payload: dict[str, Any]) -> None:
        self.queue.enqueue(RUN_JOB, job, dict(payload), **self._options(job, None))

    def enqueue_in(
        self, delay_s: float, job: str, payload: dict[str, Any], *, job_id: str | None = None
    ) -> None:
        self.queue.enqueue_in(
            timedelta(seconds=delay_s), RUN_JOB, job, dict(payload), **self._options(job, job_id)
        )


def queue_from_settings(settings: CloudSettings) -> JobQueue:
    if not settings.redis_url:
        return LoggingQueue()
    return RqQueue(
        settings.redis_url,
        max_retries=settings.job_max_retries,
        retry_intervals_s=settings.job_retry_intervals_s,
        dead_letter_ttl_s=int(settings.job_dead_letter_ttl_days * 24 * 3600),
        job_timeout_s=settings.job_timeout_s,
    )
