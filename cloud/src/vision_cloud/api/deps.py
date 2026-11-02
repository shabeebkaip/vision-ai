"""Request dependencies: database session, signed-in user, organisation access, device identity."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
import structlog
from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import ColumnElement, select, true
from sqlalchemy.orm import Session, sessionmaker

from vision_cloud import crypto
from vision_cloud import models as m
from vision_cloud.db import set_context, system_session
from vision_cloud.errors import APIError, forbidden, not_found, unauthorised
from vision_cloud.mailer import Mailer
from vision_cloud.permissions import Permission, role_allows
from vision_cloud.ratelimit import RateLimiter
from vision_cloud.security import decode_access_token
from vision_cloud.settings import CloudSettings
from vision_cloud.storage import ObjectStore

_bearer = HTTPBearer(auto_error=False)


def settings_dep(request: Request) -> CloudSettings:
    s: CloudSettings = request.app.state.settings
    return s


def sessions_dep(request: Request) -> sessionmaker[Session]:
    f: sessionmaker[Session] = request.app.state.sessionmaker
    return f


def store_dep(request: Request) -> ObjectStore:
    s: ObjectStore = request.app.state.store
    return s


def mailer_dep(request: Request) -> Mailer:
    mailer: Mailer = request.app.state.mailer
    return mailer


def limiter_dep(request: Request) -> RateLimiter:
    lim: RateLimiter = request.app.state.limiter
    return lim


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as db:
        yield db


Settings = Annotated[CloudSettings, Depends(settings_dep)]
Sessions = Annotated[sessionmaker[Session], Depends(sessions_dep)]
DB = Annotated[Session, Depends(get_db)]
Store = Annotated[ObjectStore, Depends(store_dep)]
MailerDep = Annotated[Mailer, Depends(mailer_dep)]
Limiter = Annotated[RateLimiter, Depends(limiter_dep)]
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def rate_limit(limiter: RateLimiter, key: str, per_min: float, burst: int) -> None:
    decision = limiter.hit(key, per_min, burst)
    if not decision.allowed:
        retry = max(1, int(decision.retry_after_s + 0.999))
        raise APIError(
            429, "rate_limited", "too many requests", headers={"Retry-After": str(retry)}
        )


# --------------------------------------------------------------------------- users


def current_user(db: DB, settings: Settings, creds: Bearer) -> m.User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorised()
    try:
        claims = decode_access_token(settings, creds.credentials)
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise unauthorised("invalid_token", "access token is invalid or expired") from None
    set_context(db, user_id=user_id)
    user = db.get(m.User, user_id)
    if user is None or not user.is_active or user.token_version != claims["ver"]:
        raise unauthorised("invalid_token", "access token is no longer valid")
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


CurrentUser = Annotated[m.User, Depends(current_user)]


def platform_admin(user: CurrentUser) -> m.User:
    if not user.is_platform_admin:
        raise forbidden("Code-Ox admin only")
    return user


PlatformAdmin = Annotated[m.User, Depends(platform_admin)]


@dataclass
class OrgAccess:
    """What the signed-in user may do in one organisation."""

    org: m.Organisation
    user: m.User
    role: m.Role | None  # None: Code-Ox admin acting in the organisation
    site_ids: frozenset[uuid.UUID] | None  # None: every site

    @property
    def is_platform_admin(self) -> bool:
        return self.user.is_platform_admin

    def can(self, permission: Permission) -> bool:
        return self.role is None or role_allows(self.role, permission)

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise forbidden()

    def can_see_site(self, site_id: uuid.UUID) -> bool:
        return self.site_ids is None or site_id in self.site_ids

    def site_clause(self, column: Any) -> ColumnElement[bool]:
        if self.site_ids is None:
            return true()
        clause: ColumnElement[bool] = column.in_(self.site_ids)
        return clause


def org_access(db: DB, user: CurrentUser, org_id: Annotated[uuid.UUID, Path()]) -> OrgAccess:
    set_context(db, org_id=org_id, user_id=user.id)
    membership = db.scalars(
        select(m.Membership).where(
            m.Membership.organisation_id == org_id, m.Membership.user_id == user.id
        )
    ).first()
    if membership is None and not user.is_platform_admin:
        raise not_found("organisation")
    org = db.get(m.Organisation, org_id)
    if org is None:
        raise not_found("organisation")
    structlog.contextvars.bind_contextvars(org_id=str(org_id))
    if membership is None:
        return OrgAccess(org=org, user=user, role=None, site_ids=None)
    site_ids: frozenset[uuid.UUID] | None = None
    if not membership.all_sites:
        site_ids = frozenset(
            db.scalars(
                select(m.MembershipSite.site_id).where(
                    m.MembershipSite.membership_id == membership.id
                )
            ).all()
        )
    return OrgAccess(org=org, user=user, role=membership.role, site_ids=site_ids)


Access = Annotated[OrgAccess, Depends(org_access)]


def requires(permission: Permission) -> Callable[[OrgAccess], OrgAccess]:
    def dep(access: Access) -> OrgAccess:
        access.require(permission)
        return access

    return dep


# --------------------------------------------------------------------------- devices


@dataclass
class DeviceContext:
    device: m.Device
    site: m.Site


def current_device(
    db: DB, sessions: Sessions, settings: Settings, limiter: Limiter, creds: Bearer
) -> DeviceContext:
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorised("not_authenticated", "device credential required")
    digest = crypto.hash_token(creds.credentials)
    # The only cross-tenant step: find which organisation this credential belongs to.
    with system_session(sessions) as sdb:
        found = sdb.execute(
            select(m.Device.id, m.Device.organisation_id, m.Device.status).where(
                m.Device.credential_hash == digest
            )
        ).first()
    if found is None or found.status is not m.DeviceStatus.ACTIVE:
        raise unauthorised("invalid_credential", "device credential is invalid or revoked")
    set_context(db, org_id=found.organisation_id)
    device = db.get(m.Device, found.id)
    site = db.get(m.Site, device.site_id) if device else None
    if device is None or site is None:
        raise unauthorised("invalid_credential", "device credential is invalid or revoked")
    structlog.contextvars.bind_contextvars(
        device_id=str(device.id), site_id=site.key, org_id=str(device.organisation_id)
    )
    rate_limit(
        limiter,
        f"device:{device.id}",
        settings.device_rate_limit_per_min,
        settings.device_rate_limit_burst,
    )
    return DeviceContext(device=device, site=site)


CurrentDevice = Annotated[DeviceContext, Depends(current_device)]
