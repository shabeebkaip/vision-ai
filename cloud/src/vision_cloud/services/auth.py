"""Token issuing and refresh rotation (CLD-03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from vision_cloud import crypto
from vision_cloud import models as m
from vision_cloud.api.schemas import TokenPair
from vision_cloud.errors import unauthorised
from vision_cloud.security import create_access_token
from vision_cloud.settings import CloudSettings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue_tokens(
    db: Session, settings: CloudSettings, user: m.User, family_id: uuid.UUID | None = None
) -> TokenPair:
    refresh = crypto.new_token()
    db.add(
        m.RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=crypto.hash_token(refresh),
            expires_at=_now() + timedelta(seconds=settings.refresh_token_ttl_s),
        )
    )
    return TokenPair(
        access_token=create_access_token(settings, user.id, user.token_version),
        refresh_token=refresh,
        expires_in=settings.access_token_ttl_s,
    )


def revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(m.RefreshToken)
        .where(m.RefreshToken.family_id == family_id, m.RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def revoke_all(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(m.RefreshToken)
        .where(m.RefreshToken.user_id == user_id, m.RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def rotate_refresh(db: Session, settings: CloudSettings, token: str) -> TokenPair:
    """Swap a refresh token for a new pair. Presenting an already-rotated token means it was
    stolen or replayed: the whole family is revoked and the user must sign in again."""
    row = db.scalars(
        select(m.RefreshToken)
        .where(m.RefreshToken.token_hash == crypto.hash_token(token))
        .with_for_update()
    ).first()
    invalid = unauthorised("invalid_refresh_token", "refresh token is invalid or expired")
    if row is None or row.revoked_at is not None or row.expires_at <= _now():
        raise invalid
    if row.rotated_at is not None:
        revoke_family(db, row.family_id)
        db.commit()
        raise unauthorised("refresh_token_reused", "refresh token was already used; sign in again")
    user = db.get(m.User, row.user_id)
    if user is None or not user.is_active:
        raise invalid
    row.rotated_at = _now()
    return issue_tokens(db, settings, user, family_id=row.family_id)
