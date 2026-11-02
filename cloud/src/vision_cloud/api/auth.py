"""Authentication and organisation membership endpoints (CLD-02, CLD-03)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from vision_cloud.api.deps import (
    DbDep,
    Principal,
    PrincipalDep,
    StateDep,
    audit,
    membership_sites,
    require_platform_admin,
)
from vision_cloud.db import system_session, tenant_session
from vision_cloud.errors import AppError, forbidden, not_found
from vision_cloud.models import Membership, Organisation, Role, User
from vision_cloud.schemas import (
    AcceptInvitation,
    InvitationCreate,
    InvitationCreated,
    LoginRequest,
    LogoutRequest,
    MemberOut,
    MeResponse,
    OrganisationCreate,
    OrganisationCreated,
    OrganisationOut,
    OrganisationSummary,
    RefreshRequest,
    TokenResponse,
)
from vision_cloud.services import accounts

router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, state: StateDep) -> TokenResponse:
    """Email + password sign-in. Returns a short-lived access token and a refresh token."""
    return accounts.login(
        state.sessions, state.settings, body.email, body.password, body.organisation_id
    )


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, state: StateDep) -> TokenResponse:
    """Rotate the refresh token; optionally switch the active organisation."""
    return accounts.refresh(
        state.sessions, state.settings, body.refresh_token, body.organisation_id
    )


@router.post("/auth/logout", status_code=204)
def logout(body: LogoutRequest, state: StateDep) -> Response:
    accounts.logout(state.sessions, body.refresh_token)
    return Response(status_code=204)


@router.post("/auth/accept-invitation", response_model=TokenResponse)
def accept_invitation(body: AcceptInvitation, state: StateDep) -> TokenResponse:
    """Accept an invitation: creates the account (or adds the organisation to an existing
    account, whose password must then be given) and signs in."""
    return accounts.accept_invitation(
        state.sessions, state.settings, body.token, body.password, body.full_name
    )


@router.get("/auth/me", response_model=MeResponse)
def me(principal: PrincipalDep, state: StateDep) -> MeResponse:
    with system_session(state.sessions) as db:  # the user's memberships span organisations
        rows = db.execute(
            select(Organisation.id, Organisation.name, Membership.role)
            .join(Membership, Membership.organisation_id == Organisation.id)
            .where(Membership.user_id == principal.user_id)
            .order_by(Organisation.name)
        ).all()
        user = db.scalar(select(User).where(User.id == principal.user_id))
    return MeResponse(
        user_id=principal.user_id,
        email=principal.email,
        full_name=user.full_name if user else "",
        is_platform_admin=principal.is_platform_admin,
        organisation_id=principal.organisation_id,
        role=principal.role,
        site_ids=sorted(principal.site_ids) if principal.site_ids is not None else None,
        organisations=[OrganisationSummary(id=r[0], name=r[1], role=Role(r[2])) for r in rows],
    )


# --------------------------------------------------------------------------- organisation


@router.get("/organisation", response_model=OrganisationOut, tags=["organisation"])
def current_organisation(principal: PrincipalDep, db: DbDep) -> Organisation:
    org = db.scalar(select(Organisation).where(Organisation.id == principal.organisation_id))
    if org is None:
        raise not_found("organisation")
    return org


@router.get("/members", response_model=list[MemberOut], tags=["organisation"])
def list_members(principal: PrincipalDep, db: DbDep) -> list[MemberOut]:
    principal.require(Role.MANAGER)
    memberships = db.scalars(
        select(Membership).where(Membership.organisation_id == principal.organisation_id)
    ).all()
    out = []
    for m in memberships:
        sites = membership_sites(m)
        out.append(
            MemberOut(
                user_id=m.user_id,
                email=m.user.email,
                full_name=m.user.full_name,
                role=Role(m.role),
                site_ids=sorted(sites) if sites is not None else None,
            )
        )
    return out


def _check_can_invite(principal: Principal, role: Role) -> None:
    principal.require(Role.MANAGER)
    if role in (Role.OWNER, Role.MANAGER) and principal.role is not Role.OWNER:
        raise forbidden("only an owner can invite owners and managers")


@router.post(
    "/invitations", response_model=InvitationCreated, status_code=201, tags=["organisation"]
)
def invite(
    body: InvitationCreate, principal: PrincipalDep, db: DbDep, state: StateDep, request: Request
) -> InvitationCreated:
    """Invite a person by email. The one-time token is returned to the inviter (email delivery
    of the link is a follow-up)."""
    _check_can_invite(principal, body.role)
    if body.role in (Role.SITE_MANAGER, Role.VIEWER) and not body.site_ids:
        raise AppError(422, "site managers and viewers need at least one site in site_ids")
    created = accounts.create_invitation(
        db,
        state.settings,
        organisation_id=principal.organisation_id,
        email=body.email,
        role=body.role,
        site_ids=body.site_ids,
        invited_by=principal.user_id,
    )
    audit(
        db,
        request,
        organisation_id=principal.organisation_id,
        user_id=principal.user_id,
        action="invitation.created",
        entity_type="invitation",
        entity_id=created.id,
        details={"email": body.email, "role": body.role.value},
    )
    db.commit()
    return created


# --------------------------------------------------------------------------- Code-Ox admin


@router.post(
    "/admin/organisations",
    response_model=OrganisationCreated,
    status_code=201,
    tags=["admin"],
)
def create_organisation(
    body: OrganisationCreate,
    admin: Annotated[Principal, Depends(require_platform_admin)],
    state: StateDep,
    request: Request,
) -> OrganisationCreated:
    """Code-Ox admin: create a customer organisation and an invitation for its first owner."""
    with system_session(state.sessions) as sdb:
        org = Organisation(
            name=body.name, plan=body.plan, language=body.language, timezone=body.timezone
        )
        sdb.add(org)
        sdb.commit()
    with tenant_session(state.sessions, org.id) as db:
        inv = accounts.create_invitation(
            db,
            state.settings,
            organisation_id=org.id,
            email=body.owner_email,
            role=Role.OWNER,
            site_ids=[],
            invited_by=admin.user_id,
        )
        audit(
            db,
            request,
            organisation_id=org.id,
            user_id=admin.user_id,
            action="organisation.created",
            entity_type="organisation",
            entity_id=org.id,
        )
        db.commit()
    return OrganisationCreated(
        organisation=OrganisationOut.model_validate(org), owner_invitation=inv
    )
