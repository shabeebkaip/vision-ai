"""Sign-in, refresh-token rotation and invitations (CLD-03).

Refresh tokens rotate on every use. Presenting a refresh token that was already rotated or revoked
is treated as theft: every refresh token of that user is revoked (they must sign in again).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from vision_cloud.db import TenantSession, system_session, utcnow
from vision_cloud.errors import AppError
from vision_cloud.models import (
    Invitation,
    Membership,
    MembershipSite,
    Organisation,
    RefreshToken,
    Role,
    Site,
    User,
)
from vision_cloud.schemas import InvitationCreated, TokenResponse
from vision_cloud.security import (
    check_password_strength,
    hash_password,
    issue_access_token,
    new_token,
    token_hash,
    verify_password,
)
from vision_cloud.settings import CloudSettings

_BAD_LOGIN = "wrong email or password"


def _pick_organisation(db: Session, user: User, requested: str | None) -> tuple[str, Role]:
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    ).all()
    if requested:
        for m in memberships:
            if m.organisation_id == requested:
                return m.organisation_id, Role(m.role)
        if user.is_platform_admin and db.get(Organisation, requested) is not None:
            return requested, Role.OWNER
        raise AppError(403, "no access to this organisation")
    if memberships:
        return memberships[0].organisation_id, Role(memberships[0].role)
    raise AppError(403, "this account has no organisation; pass organisation_id")


def _issue(
    db: Session, settings: CloudSettings, user: User, organisation_id: str, role: Role
) -> tuple[TokenResponse, RefreshToken]:
    access, expires_at = issue_access_token(
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        user_id=user.id,
        organisation_id=organisation_id,
        ttl_s=settings.access_token_ttl_s,
    )
    refresh = new_token("cxr_")
    row = RefreshToken(
        user_id=user.id,
        organisation_id=organisation_id,
        token_hash=token_hash(refresh),
        expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_s),
    )
    db.add(row)
    db.flush()
    return (
        TokenResponse(
            access_token=access,
            expires_at=expires_at,
            refresh_token=refresh,
            organisation_id=organisation_id,
            role=role,
        ),
        row,
    )


def login(
    sessions: sessionmaker[TenantSession],
    settings: CloudSettings,
    email: str,
    password: str,
    organisation_id: str | None,
) -> TokenResponse:
    with system_session(sessions) as db:
        user = db.scalar(select(User).where(User.email == email))
        ok = verify_password(user.password_hash if user else None, password)
        if user is None or not ok or not user.is_active:
            raise AppError(401, _BAD_LOGIN, code="invalid_credentials")
        org_id, role = _pick_organisation(db, user, organisation_id)
        user.last_login_at = utcnow()
        tokens, _ = _issue(db, settings, user, org_id, role)
        db.commit()
        return tokens


def refresh(
    sessions: sessionmaker[TenantSession],
    settings: CloudSettings,
    refresh_token: str,
    organisation_id: str | None,
) -> TokenResponse:
    with system_session(sessions) as db:
        row = db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash(refresh_token))
        )
        now = utcnow()
        if row is None:
            raise AppError(401, "invalid refresh token", code="invalid_token")
        if row.revoked_at is not None:
            _revoke_all(db, row.user_id)
            db.commit()
            raise AppError(401, "refresh token reused; signed out everywhere", code="token_reused")
        if row.expires_at <= now:
            raise AppError(401, "refresh token expired", code="invalid_token")
        user = db.scalar(select(User).where(User.id == row.user_id))
        if user is None or not user.is_active:
            raise AppError(401, "user disabled", code="invalid_token")
        org_id, role = _pick_organisation(db, user, organisation_id or row.organisation_id)
        tokens, new_row = _issue(db, settings, user, org_id, role)
        row.revoked_at = now
        row.replaced_by = new_row.id
        db.commit()
        return tokens


def logout(sessions: sessionmaker[TenantSession], refresh_token: str) -> None:
    with system_session(sessions) as db:
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash(refresh_token),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )
        db.commit()


def _revoke_all(db: Session, user_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


# --------------------------------------------------------------------------- invitations


def create_invitation(
    db: Session,
    settings: CloudSettings,
    *,
    organisation_id: str,
    email: str,
    role: Role,
    site_ids: list[str],
    invited_by: str | None,
) -> InvitationCreated:
    """`db` must be a tenant session of `organisation_id` (site ids are checked through it)."""
    site_ids = sorted(set(site_ids))
    if site_ids:
        found = set(
            db.scalars(
                select(Site.id).where(
                    Site.id.in_(site_ids), Site.organisation_id == organisation_id
                )
            ).all()
        )
        if found != set(site_ids):
            raise AppError(422, "unknown site id in site_ids")
    token = new_token("cxi_")
    inv = Invitation(
        organisation_id=organisation_id,
        email=email,
        role=role.value,
        site_ids=site_ids,
        token_hash=token_hash(token),
        invited_by=invited_by,
        expires_at=utcnow() + timedelta(seconds=settings.invitation_ttl_s),
    )
    db.add(inv)
    db.flush()
    return InvitationCreated(
        id=inv.id,
        email=email,
        role=role,
        site_ids=site_ids,
        expires_at=inv.expires_at,
        token=token,
    )


def accept_invitation(
    sessions: sessionmaker[TenantSession],
    settings: CloudSettings,
    token: str,
    password: str,
    full_name: str,
) -> TokenResponse:
    with system_session(sessions) as db:
        inv = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
        now = utcnow()
        if inv is None or inv.accepted_at is not None or inv.expires_at <= now:
            raise AppError(400, "invitation is invalid, used or expired", code="invalid_invitation")
        user = db.scalar(select(User).where(User.email == inv.email))
        if user is None:
            try:
                check_password_strength(password)
            except ValueError as exc:
                raise AppError(422, str(exc), code="weak_password") from exc
            user = User(email=inv.email, password_hash=hash_password(password), full_name=full_name)
            db.add(user)
            db.flush()
        elif not verify_password(user.password_hash, password):
            # Existing account: joining another organisation needs that account's password.
            raise AppError(401, _BAD_LOGIN, code="invalid_credentials")
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id, Membership.organisation_id == inv.organisation_id
            )
        )
        if membership is None:
            membership = Membership(
                organisation_id=inv.organisation_id, user_id=user.id, role=inv.role
            )
            db.add(membership)
            db.flush()
        else:
            membership.role = inv.role
            for access in list(membership.site_access):
                db.delete(access)
            db.flush()
        for site_id in inv.site_ids:
            db.add(
                MembershipSite(
                    organisation_id=inv.organisation_id,
                    membership_id=membership.id,
                    site_id=site_id,
                )
            )
        inv.accepted_at = now
        tokens, _ = _issue(db, settings, user, inv.organisation_id, Role(inv.role))
        db.commit()
        return tokens
