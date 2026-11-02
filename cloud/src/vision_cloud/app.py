"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from vision_cloud import __version__
from vision_cloud.api import admin, auth, device, ingest, orgs
from vision_cloud.db import check_role_is_not_privileged, make_engine, make_sessionmaker
from vision_cloud.errors import install_error_handlers
from vision_cloud.logs import configure_logging
from vision_cloud.mailer import Mailer, make_mailer
from vision_cloud.ratelimit import RateLimiter, make_limiter
from vision_cloud.settings import CloudSettings, get_settings
from vision_cloud.storage import ObjectStore, make_store

log = structlog.get_logger(__name__)


def create_app(
    settings: CloudSettings | None = None,
    *,
    store: ObjectStore | None = None,
    mailer: Mailer | None = None,
    limiter: RateLimiter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(json=settings.log_json)
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        check_role_is_not_privileged(
            engine, strict=settings.environment in {"staging", "production"}
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="Code-Ox Vision API",
        version=__version__,
        lifespan=lifespan,
        description="Dashboard API (`/api/v1`) and edge device API (`/device/v1`).",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.store = store or make_store(settings)
    app.state.mailer = mailer or make_mailer(settings)
    app.state.limiter = limiter or make_limiter(settings.redis_url)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type", "If-None-Match", "X-Request-ID"],
            expose_headers=["ETag", "X-Request-ID", "Retry-After"],
        )

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        rid = rid[:64]
        request.state.request_id = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    install_error_handlers(app)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    for module in (auth, orgs, admin, device, ingest):
        app.include_router(module.router)
    return app
