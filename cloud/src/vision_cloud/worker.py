"""Job handlers and the worker process (CLD-17).

    vision-cloud worker            # run jobs (and delayed jobs) until stopped
    vision-cloud jobs failed       # the dead-letter list: failed jobs with their errors
    vision-cloud jobs retry --all  # put dead-lettered jobs back on the queue

A handler is a function `(ctx, payload) -> None` registered under a job name with `@handler`.
RQ calls `run_job(name, payload)`, which looks the handler up and runs it with a `WorkerContext`
(settings, database sessions, storage, queue) built once per worker process. Unknown job names
and exceptions fail the job, so RQ retries it and, after the last retry, moves it to the
dead-letter list.

Handlers must be idempotent: a job can run more than once (retries, a worker killed mid-job).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import sessionmaker

from vision_cloud.db import TenantSession, make_engine, make_session_factory
from vision_cloud.jobs import QUEUE_NAME, JobQueue, RqQueue, queue_from_settings
from vision_cloud.security import FieldCipher
from vision_cloud.settings import CloudSettings
from vision_cloud.storage import ObjectStorage, storage_from_settings

log = structlog.get_logger(__name__)


@dataclass
class WorkerContext:
    settings: CloudSettings
    sessions: sessionmaker[TenantSession]
    """Open with `tenant_session(ctx.sessions, payload['organisation_id'])` so row-level
    security keeps a job inside its own tenant."""
    storage: ObjectStorage
    queue: JobQueue
    cipher: FieldCipher


Handler = Callable[[WorkerContext, dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}


def handler(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn

    return register


_context: WorkerContext | None = None


def build_context(settings: CloudSettings | None = None) -> WorkerContext:
    settings = settings or CloudSettings()
    engine = make_engine(settings.database_url, echo=settings.database_echo)
    return WorkerContext(
        settings=settings,
        sessions=make_session_factory(engine),
        storage=storage_from_settings(settings),
        queue=queue_from_settings(settings),
        cipher=FieldCipher(settings.field_encryption_key.get_secret_value()),
    )


def set_context(ctx: WorkerContext | None) -> None:
    """Tests and `vision-cloud worker` set the context; otherwise it is built from the env."""
    global _context
    _context = ctx


def context() -> WorkerContext:
    global _context
    if _context is None:
        _context = build_context()
    return _context


def run_job(name: str, payload: dict[str, Any]) -> None:
    """Entry point RQ calls for every job."""
    _load_handlers()
    fn = HANDLERS.get(name)
    if fn is None:
        raise LookupError(f"no handler for job {name!r}")
    structlog.contextvars.bind_contextvars(job=name, **_ids(payload))
    try:
        fn(context(), payload)
        log.info("job.done")
    finally:
        structlog.contextvars.clear_contextvars()


def _ids(payload: dict[str, Any]) -> dict[str, Any]:
    keys = ("organisation_id", "site_id", "event_id", "notification_id")
    return {k: payload[k] for k in keys if k in payload}


def _load_handlers() -> None:
    """Import the modules that register handlers (kept lazy to avoid import cycles)."""
    from vision_cloud.services import dispatch  # noqa: F401


# --------------------------------------------------------------------------- worker process


def run_worker(settings: CloudSettings, *, burst: bool = False) -> bool:
    from rq import Worker

    queue = queue_from_settings(settings)
    if not isinstance(queue, RqQueue):
        raise SystemExit("the worker needs VISION_CLOUD_REDIS_URL")
    _load_handlers()
    set_context(build_context(settings))
    worker = Worker([queue.queue], connection=queue.redis, serializer=queue.queue.serializer)
    log.info("worker.start", queue=QUEUE_NAME, handlers=sorted(HANDLERS), burst=burst)
    return bool(worker.work(burst=burst, with_scheduler=True))


# --------------------------------------------------------------------------- dead letter


@dataclass(frozen=True)
class FailedJob:
    id: str
    name: str
    payload: dict[str, Any]
    error: str
    failed_at: datetime | None
    attempts: int


def failed_jobs(queue: RqQueue) -> list[FailedJob]:
    from rq.job import Job
    from rq.registry import FailedJobRegistry

    registry = FailedJobRegistry(queue=queue.queue)
    jobs = []
    for job_id in registry.get_job_ids():
        job = Job.fetch(job_id, connection=queue.redis, serializer=queue.queue.serializer)
        name, payload = (job.args[0], job.args[1]) if len(job.args) >= 2 else ("?", {})
        result = job.latest_result()
        error = (result.exc_string if result and result.exc_string else "") or ""
        ended = job.ended_at.replace(tzinfo=timezone.utc) if job.ended_at else None
        retries = queue.max_retries - (job.retries_left or 0)
        jobs.append(FailedJob(job_id, str(name), dict(payload), error.strip(), ended, retries + 1))
    return jobs


def retry_failed(queue: RqQueue, job_ids: list[str] | None = None) -> int:
    """Put dead-lettered jobs back on the queue. Each runs once more; if it fails again it
    returns to the dead-letter list (its automatic retries were already used)."""
    from rq.exceptions import InvalidJobOperation, NoSuchJobError
    from rq.registry import FailedJobRegistry

    registry = FailedJobRegistry(queue=queue.queue)
    ids = job_ids if job_ids is not None else registry.get_job_ids()
    done = 0
    for job_id in ids:
        try:
            registry.requeue(job_id)
        except (NoSuchJobError, InvalidJobOperation):
            log.warning("jobs.not_in_dead_letter", job_id=job_id)
            continue
        done += 1
    return done
