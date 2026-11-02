"""Audit log writes (the full audit trail is CLD-16; this records what CLD-01..05 already change)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from vision_cloud import models as m


def record(
    db: Session,
    *,
    org_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None = None,
    user_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        m.AuditLog(
            organisation_id=org_id,
            user_id=user_id,
            device_id=device_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details or {},
            ip=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    )
