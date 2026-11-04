"""CLD-17: Redis job queue, worker, retries, delayed jobs and the dead-letter list.

Needs a throwaway Redis: VISION_CLOUD_TEST_REDIS_URL=redis://localhost:6379/15 (the tests flush
that database). `.github/workflows/cloud.yml` sets VISION_CLOUD_REQUIRE_REDIS=1 so a missing
server fails instead of skipping.

Done-when from the plan: "A failing job retries 3 times then lands in dead-letter with its error".
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vision_cloud.app import create_app
from vision_cloud.jobs import RqQueue, queue_from_settings
from vision_cloud.settings import CloudSettings
from vision_cloud.worker import (
    WorkerContext,
    build_context,
    failed_jobs,
    handler,
    retry_failed,
    set_context,
)

from .conftest import _bootstrap_admin_org, auth, build_tenant, create_admin, make_event

REDIS_URL = os.environ.get("VISION_CLOUD_TEST_REDIS_URL", "")
if not REDIS_URL and os.environ.get("VISION_CLOUD_REQUIRE_REDIS") == "1":
    pytest.fail("VISION_CLOUD_TEST_REDIS_URL is required", pytrace=False)
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="needs VISION_CLOUD_TEST_REDIS_URL")

RAN: list[tuple[str, dict[str, Any]]] = []
ATTEMPTS: dict[str, int] = {}


@handler("test.record")
def _record(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    RAN.append(("test.record", payload))


@handler("test.boom")
def _boom(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    ATTEMPTS[payload["key"]] = ATTEMPTS.get(payload["key"], 0) + 1
    raise ValueError(f"boom {payload['key']}")


@handler("test.flaky")
def _flaky(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    ATTEMPTS[payload["key"]] = ATTEMPTS.get(payload["key"], 0) + 1
    if ATTEMPTS[payload["key"]] < 3:
        raise ConnectionError("provider timeout")
    RAN.append(("test.flaky", payload))


@pytest.fixture
def queue() -> Iterator[RqQueue]:
    q = RqQueue(REDIS_URL, max_retries=3, retry_intervals_s=[0])
    q.redis.flushdb()
    RAN.clear()
    ATTEMPTS.clear()
    set_context(None)
    yield q
    q.redis.flushdb()
    set_context(None)


def work(q: RqQueue) -> None:
    """Run everything queued in this process (SimpleWorker: no fork), including due delayed jobs."""
    from rq import SimpleWorker

    SimpleWorker([q.queue], connection=q.redis, serializer=q.queue.serializer).work(
        burst=True, with_scheduler=True
    )


def test_job_runs_once(queue: RqQueue) -> None:
    queue.enqueue("test.record", {"event_id": "e1"})
    work(queue)
    assert RAN == [("test.record", {"event_id": "e1"})]
    assert failed_jobs(queue) == []


def test_failing_job_retries_three_times_then_dead_letters_with_its_error(queue: RqQueue) -> None:
    queue.enqueue("test.boom", {"key": "42", "event_id": "e9"})
    work(queue)
    assert ATTEMPTS["42"] == 4  # the first run and 3 retries
    [dead] = failed_jobs(queue)
    assert dead.name == "test.boom" and dead.payload == {"key": "42", "event_id": "e9"}
    assert "ValueError: boom 42" in dead.error
    assert dead.attempts == 4
    assert dead.failed_at is not None


def test_transient_failure_succeeds_on_retry(queue: RqQueue) -> None:
    queue.enqueue("test.flaky", {"key": "t"})
    work(queue)
    assert ATTEMPTS["t"] == 3 and RAN == [("test.flaky", {"key": "t"})]
    assert failed_jobs(queue) == []


def test_unknown_job_goes_to_dead_letter(queue: RqQueue) -> None:
    queue.enqueue("no.such.job", {"x": 1})
    work(queue)
    [dead] = failed_jobs(queue)
    assert "no handler for job 'no.such.job'" in dead.error


def test_dead_letter_retry(queue: RqQueue) -> None:
    queue.enqueue("test.boom", {"key": "r"})
    work(queue)
    [dead] = failed_jobs(queue)
    assert retry_failed(queue, [dead.id]) == 1
    assert failed_jobs(queue) == []
    work(queue)
    assert ATTEMPTS["r"] == 5  # a manual retry runs once more (no new retry budget)
    assert len(failed_jobs(queue)) == 1


def test_delayed_job_waits_until_due(queue: RqQueue) -> None:
    queue.enqueue_in(1.0, "test.record", {"event_id": "later"}, job_id="escalate-later")
    work(queue)
    assert RAN == []
    time.sleep(1.3)
    work(queue)
    assert RAN == [("test.record", {"event_id": "later"})]


def test_delayed_job_with_the_same_id_is_scheduled_once(queue: RqQueue) -> None:
    queue.enqueue_in(0.5, "test.record", {"n": 1}, job_id="escalate-e1")
    queue.enqueue_in(0.5, "test.record", {"n": 2}, job_id="escalate-e1")  # replaces, not adds
    time.sleep(0.8)
    work(queue)
    assert RAN == [("test.record", {"n": 2})]


def test_api_enqueues_into_redis_and_worker_has_a_context(
    settings: CloudSettings, tmp_path: Any
) -> None:
    redis_settings = settings.model_copy(update={"redis_url": REDIS_URL})
    q = queue_from_settings(redis_settings)
    assert isinstance(q, RqQueue)
    q.redis.flushdb()
    app = create_app(redis_settings)
    with TestClient(app) as client:
        create_admin(app)
        _bootstrap_admin_org(app)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "ops@codeox.test", "password": "correct-horse-battery-staple"},
        )
        tenant = build_tenant(client, r.json()["access_token"], "Gamma")
        event = make_event(tenant.site_ids[0], tenant.camera_ids[0], tenant.rule_id)
        r = client.post("/device/v1/events", json=event, headers=auth(tenant.device_token))
        assert r.status_code == 201
    names = [job.args[0] for job in q.queue.get_jobs()]
    assert names.count("event.created") == 2  # build_tenant's event and ours
    set_context(build_context(redis_settings))
    work(q)  # the placeholder dispatch handlers acknowledge them
    assert q.queue.count == 0 and failed_jobs(q) == []
    app.state.vision.engine.dispose()
    q.redis.flushdb()
