"""FastAPI application factory. `uvicorn vision_cloud.app:create_app --factory`."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from vision_cloud import errors
from vision_cloud.api import alerts, auth, device, events, manage, recipients, storage_local
from vision_cloud.api.deps import AppState, StateDep
from vision_cloud.db import make_engine, make_session_factory
from vision_cloud.jobs import JobQueue, queue_from_settings
from vision_cloud.security import FieldCipher
from vision_cloud.settings import CloudSettings
from vision_cloud.storage import LocalStorage, ObjectStorage, storage_from_settings


def configure_logging(json_logs: bool) -> None:
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def create_app(
    settings: CloudSettings | None = None,
    *,
    storage: ObjectStorage | None = None,
    queue: JobQueue | None = None,
) -> FastAPI:
    settings = settings or CloudSettings()  # values from environment
    configure_logging(settings.log_json)
    engine = make_engine(settings.database_url, echo=settings.database_echo)
    state = AppState(
        settings=settings,
        sessions=make_session_factory(engine),
        storage=storage or storage_from_settings(settings),
        queue=queue or queue_from_settings(settings),
        cipher=FieldCipher(settings.field_encryption_key.get_secret_value()),
        engine=engine,
    )
    app = FastAPI(
        title="Code-Ox Vision cloud API",
        version="0.1.0",
        description="Device API for edge boxes and management API for the dashboard.",
    )
    app.state.vision = state
    errors.install(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID", "If-None-Match"],
            expose_headers=["X-Request-ID", "ETag"],
        )
    app.include_router(auth.router)
    app.include_router(manage.router)
    app.include_router(recipients.router)
    app.include_router(alerts.router)
    app.include_router(events.router)
    app.include_router(device.router)
    if isinstance(state.storage, LocalStorage):
        app.include_router(storage_local.router)

    @app.get("/healthz", tags=["health"])
    def healthz(st: StateDep) -> dict[str, str]:
        with st.sessions() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app
