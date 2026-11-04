"""Shared helpers for the alerting tests (CLD-08, CLD-10): post events, add recipients, run the
queued jobs the way the worker would, and read the delivery log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select

from vision_cloud.db import system_session
from vision_cloud.jobs import InMemoryQueue
from vision_cloud.models import Alert, Notification
from vision_cloud.services import channels
from vision_cloud.worker import HANDLERS, WorkerContext

from .conftest import World, auth, make_event

# T0 is 2026-11-01 09:00 UTC = 12:00 in Riyadh.


def sent_messages() -> list[tuple[str, str, Any]]:
    return channels._dry_run.sent  # type: ignore[attr-defined]


def run_jobs(ctx: WorkerContext, queue: InMemoryQueue) -> None:
    """Run queued jobs like the worker would, including jobs queued by jobs."""
    while queue.jobs:
        name, payload = queue.jobs.pop(0)
        HANDLERS[name](ctx, payload)


def recipient(world: World, **kw: Any) -> dict[str, Any]:
    body = {"name": "Manager", "channel": "whatsapp", "address": "+966501234567", **kw}
    r = world.client.post("/api/v1/recipients", json=body, headers=auth(world.a.owner_token))
    assert r.status_code == 201, r.text
    return dict(r.json())


def post_events(world: World, times: list[datetime], **kw: Any) -> list[str]:
    a = world.a
    ids = []
    camera = kw.pop("camera", a.camera_ids[0])
    rule_id = kw.pop("rule_id", a.rule_id)
    for at in times:
        ev = make_event(a.site_ids[0], camera, rule_id, at=at, **kw)
        r = world.client.post("/device/v1/events", json=ev, headers=auth(a.device_token))
        assert r.status_code == 201, r.text
        ids.append(ev["id"])
    return ids


def log_rows(app: FastAPI) -> list[Notification]:
    with system_session(app.state.vision.sessions) as db:
        return list(db.scalars(select(Notification).order_by(Notification.created_at)).all())


def alerts(app: FastAPI, org: str) -> list[Alert]:
    with system_session(app.state.vision.sessions) as db:
        return list(
            db.scalars(
                select(Alert).where(Alert.organisation_id == org).order_by(Alert.opened_at)
            ).all()
        )
