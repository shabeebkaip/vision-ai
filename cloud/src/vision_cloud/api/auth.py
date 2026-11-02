"""Sign-in, refresh, invitations, password reset and authenticator-app 2FA (CLD-03).

Library choice: see docs/adr/0001-cloud-authentication.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vision_cloud import crypto
from vision_cloud import models as m
from vision_cloud.api.deps import (
    DB,
    CurrentUser,
    Limiter,
    MailerDep,
    Sessions,
    Settings,
    rate_limit,
)
from vision_cloud.api.schemas import (
    AcceptInvitationIn,
    InvitationPreview,
    LoginIn,
    MembershipOut,
    MeOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RefreshIn,
    TokenPair,
    TotpCodeIn,
    TotpDisableIn,
    TotpSetupOut,
)
from vision_cloud.db import system_session
from vision_cloud.errors import APIError, unauthorised
from vision_cloud.i18n import t
from vision_cloud.mailer import Mail
from vision_cloud.security import (
    hash_password,
    new_totp_secret,
    password_needs_rehash,
    password_problem,
    totp_uri,
    verify_password,
    verify_totp,
)
from vision_cloud.services import audit
from vision_cloud.services.auth import issue_tokens, revoke_all, revoke_family, rotate_refresh

router = APIRouter(prefix="/api/v1", tags=["auth"])

LOGIN_PER_MIN = 10
RESET_PER_HOUR = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _check_password(password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise APIError(422, "weak_password", problem)


def _user_by_email(db: Session, email: str) -> m.User | None:
    return db.scalars(select(m.User).where(func.lower(m.User.email) == email.lower())).first()


# --------------------------------------------------------------------------- sign-in


@router.post("/auth/login", response_model=TokenPair)
def login(body: LoginIn, sessions: Sessions, settings: Settings, limiter: Limiter) -> TokenPair:
    rate_limit(limiter, f"login:{body.email}", LOGIN_PER_MIN, LOGIN_PER_MIN)
    with system_session(sessions) as db:
        user = _user_by_email(db, body.email)
        ok = verify_password(user.password_hash if user else None, body.password)
        if user is None or not ok or not user.is_active:
            raise unauthorised("invalid_credentials", "email or password is wrong")
        if user.totp_enabled:
            if not body.otp:
                raise unauthorised("otp_required", "enter the code from your authenticator app")
            if not user.totp_secret or not verify_totp(user.totp_secret, body.otp):
                raise unauthorised("otp_invalid", "authenticator code is wrong")
        if user.password_hash and password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(body.password)
        user.last_login_at = _now()
        tokens = issue_tokens(db, settings, user)
        db.commit()
        return tokens


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, sessions: Sessions, settings: Settings) -> TokenPair:
    with system_session(sessions) as db:
        tokens = rotate_refresh(db, settings, body.refresh_token)
        db.commit()
        return tokens


@router.post("/auth/logout", status_code=204)
def logout(body: RefreshIn, sessions: Sessions) -> Response:
    with system_session(sessions) as db:
        row = db.scalars(
            select(m.RefreshToken).where(
                m.RefreshToken.token_hash == crypto.hash_token(body.refresh_token)
            )
        ).first()
        if row is not None:
            revoke_family(db, row.family_id)
            db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=MeOut, tags=["people"])
def me(db: DB, user: CurrentUser) -> MeOut:
    rows = db.execute(
        select(m.Membership, m.Organisation.name)
        .join(m.Organisation, m.Organisation.id == m.Membership.organisation_id)
        .where(m.Membership.user_id == user.id)
        .order_by(m.Organisation.name)
    ).all()
    memberships = [
        MembershipOut(
            organisation_id=ms.organisation_id,
            organisation_name=name,
            role=ms.role,
            all_sites=ms.all_sites,
        )
        for ms, name in rows
    ]
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        language=user.language,
        is_platform_admin=user.is_platform_admin,
        totp_enabled=user.totp_enabled,
        memberships=memberships,
    )


# --------------------------------------------------------------------------- invitations


def _open_invitation(db: Session, token: str) -> m.Invitation:
    inv = db.scalars(
        select(m.Invitation)
        .where(m.Invitation.token_hash == crypto.hash_token(token))
        .with_for_update()
    ).first()
    if inv is None or inv.accepted_at is not None or inv.expires_at <= _now():
        raise APIError(400, "invalid_invitation", "invitation is invalid, used or expired")
    return inv


@router.get("/auth/invitations/{token}", response_model=InvitationPreview)
def preview_invitation(token: str, sessions: Sessions) -> InvitationPreview:
    with system_session(sessions) as db:
        inv = _open_invitation(db, token)
        org = db.get(m.Organisation, inv.organisation_id)
        assert org is not None
        return InvitationPreview(
            organisation_name=org.name,
            email=inv.email,
            role=inv.role,
            existing_account=_user_by_email(db, inv.email) is not None,
            expires_at=inv.expires_at,
        )


@router.post("/auth/invitations/accept", response_model=TokenPair)
def accept_invitation(
    body: AcceptInvitationIn, request: Request, sessions: Sessions, settings: Settings
) -> TokenPair:
    with system_session(sessions) as db:
        inv = _open_invitation(db, body.token)
        org = db.get(m.Organisation, inv.organisation_id)
        assert org is not None
        user = _user_by_email(db, inv.email)
        if user is not None and user.password_hash:
            # Existing account: prove it is theirs with their current password.
            if not verify_password(user.password_hash, body.password):
                raise unauthorised("invalid_credentials", "password is wrong for this account")
        else:
            _check_password(body.password)
            if user is None:
                user = m.User(email=inv.email, name=body.name, language=org.language)
                db.add(user)
            user.password_hash = hash_password(body.password)
            if body.name:
                user.name = body.name
            db.flush()
        if not user.is_active:
            raise unauthorised("account_disabled", "this account is disabled")

        existing = db.scalars(
            select(m.Membership).where(
                m.Membership.organisation_id == org.id, m.Membership.user_id == user.id
            )
        ).first()
        if existing is None:
            membership = m.Membership(
                organisation_id=org.id,
                user_id=user.id,
                role=inv.role,
                all_sites=not inv.site_ids,
            )
            db.add(membership)
            db.flush()
            for sid in inv.site_ids:
                db.add(
                    m.MembershipSite(
                        membership_id=membership.id, site_id=sid, organisation_id=org.id
                    )
                )
        inv.accepted_at = _now()
        audit.record(
            db,
            org_id=org.id,
            action="invitation.accepted",
            entity_type="membership",
            entity_id=user.id,
            user_id=user.id,
            details={"role": inv.role.value},
            request=request,
        )
        tokens = issue_tokens(db, settings, user)
        db.commit()
        return tokens


# --------------------------------------------------------------------------- password reset


@router.post("/auth/password-reset/request", status_code=202)
def request_password_reset(
    body: PasswordResetRequestIn,
    sessions: Sessions,
    settings: Settings,
    limiter: Limiter,
    mailer: MailerDep,
) -> Response:
    """Always answers 202, whether or not the address has an account."""
    rate_limit(limiter, f"reset:{body.email}", RESET_PER_HOUR / 60, RESET_PER_HOUR)
    with system_session(sessions) as db:
        user = _user_by_email(db, body.email)
        if user is not None and user.is_active:
            token = crypto.new_token()
            db.add(
                m.PasswordReset(
                    user_id=user.id,
                    token_hash=crypto.hash_token(token),
                    expires_at=_now() + timedelta(seconds=settings.password_reset_ttl_s),
                )
            )
            db.commit()
            lang = user.language.value
            link = f"{settings.public_web_url}/reset-password#token={token}"
            mailer.send(
                Mail(
                    to=user.email,
                    subject=t(lang, "email.reset.subject"),
                    body=t(lang, "email.reset.body", link=link),
                )
            )
    return Response(status_code=202)


@router.post("/auth/password-reset/confirm", status_code=204)
def confirm_password_reset(body: PasswordResetConfirmIn, sessions: Sessions) -> Response:
    _check_password(body.password)
    with system_session(sessions) as db:
        row = db.scalars(
            select(m.PasswordReset)
            .where(m.PasswordReset.token_hash == crypto.hash_token(body.token))
            .with_for_update()
        ).first()
        if row is None or row.used_at is not None or row.expires_at <= _now():
            raise APIError(400, "invalid_reset_token", "reset link is invalid, used or expired")
        user = db.get(m.User, row.user_id)
        if user is None or not user.is_active:
            raise APIError(400, "invalid_reset_token", "reset link is invalid, used or expired")
        user.password_hash = hash_password(body.password)
        user.token_version += 1  # signs out every open session
        row.used_at = _now()
        revoke_all(db, user.id)
        db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- 2FA (TOTP)


@router.post("/auth/2fa/setup", response_model=TotpSetupOut)
def totp_setup(db: DB, user: CurrentUser) -> TotpSetupOut:
    if user.totp_enabled:
        raise APIError(409, "totp_already_enabled", "two-factor sign-in is already on")
    secret = new_totp_secret()
    user.totp_secret = secret
    db.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/auth/2fa/enable", status_code=204)
def totp_enable(body: TotpCodeIn, db: DB, user: CurrentUser) -> Response:
    if user.totp_enabled:
        raise APIError(409, "totp_already_enabled", "two-factor sign-in is already on")
    if not user.totp_secret:
        raise APIError(409, "totp_not_set_up", "call /auth/2fa/setup first")
    if not verify_totp(user.totp_secret, body.code):
        raise APIError(400, "otp_invalid", "authenticator code is wrong")
    user.totp_enabled = True
    db.commit()
    return Response(status_code=204)


@router.post("/auth/2fa/disable", status_code=204)
def totp_disable(body: TotpDisableIn, db: DB, user: CurrentUser) -> Response:
    if not user.totp_enabled or not user.totp_secret:
        raise APIError(409, "totp_not_enabled", "two-factor sign-in is off")
    if not verify_password(user.password_hash, body.password):
        raise unauthorised("invalid_credentials", "password is wrong")
    if not verify_totp(user.totp_secret, body.code):
        raise APIError(400, "otp_invalid", "authenticator code is wrong")
    user.totp_enabled = False
    user.totp_secret = None
    db.commit()
    return Response(status_code=204)
