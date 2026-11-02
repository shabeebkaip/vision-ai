"""Signed upload/download endpoints for `LocalStorage` (development and tests only; production uses
S3-compatible storage and these routes are not mounted)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from vision_cloud.api.deps import StateDep
from vision_cloud.errors import AppError
from vision_cloud.storage import LocalStorage

router = APIRouter(prefix="/storage/local", tags=["storage (dev)"], include_in_schema=False)


def _local(state: StateDep) -> LocalStorage:
    if not isinstance(state.storage, LocalStorage):
        raise AppError(404, "not found")
    return state.storage


@router.put("/{key:path}", status_code=204)
async def put_object(
    key: str,
    request: Request,
    state: StateDep,
    expires: Annotated[str, Query()],
    signature: Annotated[str, Query()],
) -> Response:
    storage = _local(state)
    if not storage.verify("PUT", key, expires, signature):
        raise AppError(403, "invalid or expired signature")
    limit = state.settings.max_clip_bytes
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise AppError(413, "object too large")
    storage.put_bytes(key, bytes(data), request.headers.get("content-type", ""))
    return Response(status_code=204)


@router.get("/{key:path}")
def get_object(
    key: str,
    state: StateDep,
    expires: Annotated[str, Query()],
    signature: Annotated[str, Query()],
) -> Response:
    storage = _local(state)
    if not storage.verify("GET", key, expires, signature):
        raise AppError(403, "invalid or expired signature")
    if not storage.exists(key):
        raise AppError(404, "not found")
    media = "video/mp4" if key.endswith(".mp4") else "image/jpeg"
    return Response(content=storage.read_bytes(key), media_type=media)
