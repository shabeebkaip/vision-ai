"""ASGI entry point: `uvicorn vision_cloud.main:app`."""

from __future__ import annotations

from vision_cloud.app import create_app

app = create_app()
