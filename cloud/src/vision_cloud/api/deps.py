"""Request dependencies: application state, the authenticated principal (user or device) and the
tenant-scoped database session (CLD-02)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import ColumnElement, Engine, select, true
from sqlalchemy.orm import Session, sessionmaker

from vision_cloud.db import TenantSession, system_session, tenant_session
from vision_cloud.errors import AppError, forbidden, request_id_of
from vision_cloud.jobs import JobQueue
from vision_cloud.models import (
    ROLE_RANK,
    SITE_SCOPED_ROLES,
    AuditLog,
    Device,
    DeviceStatus,
    Membership,
    Role,
    User,
)
from vision_cloud.security import FieldCipher, TokenError, decode_access_token, token_hash
from vision_cloud.settings import CloudSettings
from vision_cloud.storage import ObjectStorage


@dataclass
class AppState:
    settings: CloudSettings
    sessions: sessionmaker[TenantSession]
    storage: ObjectStorage
    queue: JobQueue
    cipher: FieldCipher
    engine: Engine


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.vision
    return state


StateDep = Annotated[AppState, Depends(get_state)]
_bearer = HTTPBearer(auto_error=False)
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def _unauthorized(message: str = "authentication required") -> AppError:
    return AppError(401, message, headers={"WWW-Authenticate": "Bearer"})


# --------------------------------------------------------------------------- users


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    organisation_id: str
    role: Role
    is_platform_admin: bool
    site_ids: frozenset[str] | None  # None = every site of the organisation

    def at_least(self, role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]

    def require(self, role: Role) -> None:
        if not self.at_least(role):
            raise forbidden(f"needs role {role.value} or higher")

    def can_see_site(self, site_id: str) -> bool:
        return self.site_ids is None or site_id in self.site_ids

    def site_filter(self, column: Any) -> ColumnElement[bool]:
        """WHERE clause limiting `column` (a site id column) to the sites this user may see."""
        if self.site_ids is None:
            return true()
        clause: ColumnElement[bool] = column.in_(sorted(self.site_ids))
        return clause


def membership_sites(membership: Membership) -> frozenset[str] | None:
    if Role(membership.role) in SITE_SCOPED_ROLES:
        return frozenset(a.site_id for a in membership.site_access)
    return None


def get_principal(state: StateDep, creds: BearerDep) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        claims = decode_access_token(
            creds.credentials,
            secret=state.settings.jwt_secret.get_secret_value(),
            issuer=state.settings.jwt_issuer,
        )
    except TokenError as exc:
        raise _unauthorized("invalid or expired token") from exc
    with tenant_session(state.sessions, claims.organisation_id) as db:
        user = db.scalar(select(User).where(User.id == claims.user_id))
        if user is None or not user.is_active:
            raise _unauthorized("user disabled")
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organisation_id == claims.organisation_id,
            )
        )
        if membership is not None:
            return Principal(
                user_id=user.id,
                email=user.email,
                organisation_id=claims.organisation_id,
                role=Role(membership.role),
                is_platform_admin=user.is_platform_admin,
                site_ids=membership_sites(membership),
            )
        if user.is_platform_admin:
            return Principal(
                user_id=user.id,
                email=user.email,
                organisation_id=claims.organisation_id,
                role=Role.OWNER,
                is_platform_admin=True,
                site_ids=None,
            )
    raise _unauthorized("no access to this organisation")


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_db(state: StateDep, principal: PrincipalDep) -> Iterator[TenantSession]:
    with tenant_session(state.sessions, principal.organisation_id) as db:
        yield db


DbDep = Annotated[TenantSession, Depends(get_db)]


def require_platform_admin(principal: PrincipalDep) -> Principal:
    if not principal.is_platform_admin:
        raise forbidden("Code-Ox admin only")
    return principal


# --------------------------------------------------------------------------- devices


@dataclass(frozen=True)
class DevicePrincipal:
    device_id: str
    organisation_id: str
    site_id: str
    hardware_tier: str


def get_device(state: StateDep, creds: BearerDep) -> DevicePrincipal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized("device token required")
    # The organisation is unknown until the credential is matched: the only cross-tenant read
    # on the device path, by unique credential hash.
    with system_session(state.sessions) as db:
        device = db.scalar(
            select(Device).where(Device.credential_hash == token_hash(creds.credentials))
        )
        if device is None or device.status != DeviceStatus.ACTIVE.value:
            raise _unauthorized("unknown or revoked device")
        return DevicePrincipal(
            device_id=device.id,
            organisation_id=device.organisation_id,
            site_id=device.site_id,
            hardware_tier=device.hardware_tier,
        )


DeviceDep = Annotated[DevicePrincipal, Depends(get_device)]


def get_device_db(state: StateDep, device: DeviceDep) -> Iterator[TenantSession]:
    with tenant_session(state.sessions, device.organisation_id) as db:
        yield db


DeviceDbDep = Annotated[TenantSession, Depends(get_device_db)]


# --------------------------------------------------------------------------- audit (CLD-16 basics)


def audit(
    db: Session,
    request: Request,
    *,
    organisation_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: str | None = None,
    device_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            organisation_id=organisation_id,
            user_id=user_id,
            device_id=device_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
            ip=request.client.host if request.client else None,
            request_id=request_id_of(request) or None,
        )
    )
