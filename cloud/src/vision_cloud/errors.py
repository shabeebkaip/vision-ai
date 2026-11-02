"""Consistent error format and request ids (CLD-19 basics).

Every error response has the body
    {"error": {"code": "not_found", "message": "...", "request_id": "...", "details": [...]}}
and every response carries an `X-Request-ID` header (taken from the request when it is a sane
token, otherwise generated). Logs bind the same id.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str | None = None,
        details: list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code or _STATUS_CODES.get(status_code, "error")
        self.details = details or []
        self.headers = headers or {}


def not_found(what: str = "resource") -> AppError:
    return AppError(404, f"{what} not found")


def forbidden(message: str = "not allowed") -> AppError:
    return AppError(403, message)


def request_id_of(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else ""


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = request_id_of(request)
    body = {
        "error": {"code": code, "message": message, "request_id": rid, "details": details or []}
    }
    out_headers = dict(headers or {})
    if rid:
        out_headers[REQUEST_ID_HEADER] = rid
    return JSONResponse(body, status_code=status_code, headers=out_headers)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if _REQUEST_ID_OK.match(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            request, exc.status_code, exc.code, exc.message, exc.details, exc.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 304:
            return Response(status_code=304, headers=dict(exc.headers or {}))
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        return error_response(
            request, exc.status_code, code, message, headers=dict(exc.headers or {})
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return error_response(request, 422, "validation_error", "invalid request", details)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("request.unhandled_error", path=request.url.path)
        return error_response(request, 500, "internal_error", "internal server error")
