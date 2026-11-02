"""Organisation-scoped read endpoints and user invitations (CLD-02).

Every route lives under `/api/v1/orgs/{org_id}` and depends on `org_access`, which sets the tenant
context for row-level security and checks membership. Queries still filter on `organisation_id`
and on the member's sites: RLS is the second lock, not the only one. The full CRUD for sites,
cameras, zones, rules and recipients is CLD-07.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from vision_cloud import crypto
from vision_cloud import models as m
from vision_cloud.api.deps import DB, Access, MailerDep, OrgAccess, Settings, requires
from vision_cloud.api.schemas import (
    CameraOut,
    DeviceOut,
    EventOut,
    EventPage,
    InvitationIn,
    InvitationOut,
    MemberOut,
    OrganisationOut,
    SiteOut,
)
from vision_cloud.errors import APIError, forbidden, not_found
from vision_cloud.i18n import t
from vision_cloud.mailer import Mail
from vision_cloud.permissions import INVITABLE_ROLES, Permission
from vision_cloud.services import audit

router = APIRouter(prefix="/api/v1/orgs/{org_id}", tags=["organisation"])

Inviter = Annotated[OrgAccess, Depends(requires(Permission.INVITE_USERS))]
MemberAdmin = Annotated[OrgAccess, Depends(requires(Permission.MANAGE_MEMBERS))]


@router.get("", response_model=OrganisationOut)
def get_organisation(access: Access) -> m.Organisation:
    return access.org


# --------------------------------------------------------------------------- sites and cameras


@router.get("/sites", response_model=list[SiteOut])
def list_sites(db: DB, access: Access) -> list[m.Site]:
    return list(
        db.scalars(
            select(m.Site)
            .where(m.Site.organisation_id == access.org.id, access.site_clause(m.Site.id))
            .order_by(m.Site.name)
        ).all()
    )


def _site(db: DB, access: OrgAccess, site_id: uuid.UUID) -> m.Site:
    site = db.get(m.Site, site_id)
    if site is None or site.organisation_id != access.org.id or not access.can_see_site(site.id):
        raise not_found("site")
    return site


@router.get("/sites/{site_id}", response_model=SiteOut)
def get_site(site_id: uuid.UUID, db: DB, access: Access) -> m.Site:
    return _site(db, access, site_id)


@router.get("/cameras", response_model=list[CameraOut])
def list_cameras(
    db: DB, access: Access, site_id: Annotated[uuid.UUID | None, Query()] = None
) -> list[m.Camera]:
    q = select(m.Camera).where(
        m.Camera.organisation_id == access.org.id, access.site_clause(m.Camera.site_id)
    )
    if site_id is not None:
        q = q.where(m.Camera.site_id == site_id)
    return list(db.scalars(q.order_by(m.Camera.name)).all())


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: uuid.UUID, db: DB, access: Access) -> m.Camera:
    cam = db.get(m.Camera, camera_id)
    if cam is None or cam.organisation_id != access.org.id or not access.can_see_site(cam.site_id):
        raise not_found("camera")
    return cam


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(db: DB, access: Access) -> list[m.Device]:
    return list(
        db.scalars(
            select(m.Device)
            .where(m.Device.organisation_id == access.org.id, access.site_clause(m.Device.site_id))
            .order_by(m.Device.enrolled_at)
        ).all()
    )


# --------------------------------------------------------------------------- events


@router.get("/events", response_model=EventPage)
def list_events(
    db: DB,
    access: Access,
    site_id: Annotated[uuid.UUID | None, Query()] = None,
    camera_id: Annotated[uuid.UUID | None, Query()] = None,
    before: Annotated[datetime | None, Query(description="triggered strictly before")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EventPage:
    q = select(m.EventRow).where(
        m.EventRow.organisation_id == access.org.id, access.site_clause(m.EventRow.site_id)
    )
    if site_id is not None:
        q = q.where(m.EventRow.site_id == site_id)
    if camera_id is not None:
        q = q.where(m.EventRow.camera_id == camera_id)
    if before is not None:
        q = q.where(m.EventRow.triggered_at < before)
    rows = list(db.scalars(q.order_by(m.EventRow.triggered_at.desc()).limit(limit)).all())
    next_before = rows[-1].triggered_at if len(rows) == limit else None
    return EventPage(items=[EventOut.model_validate(r) for r in rows], next_before=next_before)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: uuid.UUID, db: DB, access: Access) -> m.EventRow:
    ev = db.get(m.EventRow, event_id)
    if ev is None or ev.organisation_id != access.org.id or not access.can_see_site(ev.site_id):
        raise not_found("event")
    return ev


# --------------------------------------------------------------------------- people


@router.get("/members", response_model=list[MemberOut])
def list_members(db: DB, access: Access) -> list[MemberOut]:
    rows = db.execute(
        select(m.Membership, m.User)
        .join(m.User, m.User.id == m.Membership.user_id)
        .where(m.Membership.organisation_id == access.org.id)
        .order_by(m.User.email)
    ).all()
    sites: dict[uuid.UUID, list[uuid.UUID]] = {}
    for ms_id, site_id in db.execute(
        select(m.MembershipSite.membership_id, m.MembershipSite.site_id).where(
            m.MembershipSite.organisation_id == access.org.id
        )
    ).all():
        sites.setdefault(ms_id, []).append(site_id)
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            name=u.name,
            role=ms.role,
            all_sites=ms.all_sites,
            site_ids=sites.get(ms.id, []),
        )
        for ms, u in rows
    ]


@router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(db: DB, access: Inviter) -> list[m.Invitation]:
    return list(
        db.scalars(
            select(m.Invitation)
            .where(m.Invitation.organisation_id == access.org.id)
            .order_by(m.Invitation.created_at.desc())
        ).all()
    )


@router.post("/invitations", response_model=InvitationOut, status_code=201)
def create_invitation(
    body: InvitationIn,
    request: Request,
    db: DB,
    access: Inviter,
    settings: Settings,
    mailer: MailerDep,
) -> m.Invitation:
    if access.role is not None and body.role not in INVITABLE_ROLES[access.role]:
        raise forbidden(f"you cannot invite a {body.role.value}")
    if body.role is m.Role.SITE_MANAGER and not body.site_ids:
        raise APIError(422, "sites_required", "a site manager needs at least one site")
    if body.site_ids:
        found = set(
            db.scalars(
                select(m.Site.id).where(
                    m.Site.organisation_id == access.org.id, m.Site.id.in_(body.site_ids)
                )
            ).all()
        )
        if found != set(body.site_ids):
            raise not_found("site")
        # A site-limited inviter can only grant sites they can see themselves.
        if access.site_ids is not None and not found <= access.site_ids:
            raise forbidden("you can only invite to your own sites")
    elif access.site_ids is not None:
        raise forbidden("you can only invite to your own sites")

    already = db.scalar(
        select(func.count())
        .select_from(m.Membership)
        .join(m.User, m.User.id == m.Membership.user_id)
        .where(
            m.Membership.organisation_id == access.org.id,
            func.lower(m.User.email) == body.email,
        )
    )
    if already:
        raise APIError(409, "already_member", "this person is already a member")

    token = crypto.new_token()
    inv = m.Invitation(
        id=uuid.uuid4(),
        organisation_id=access.org.id,
        email=body.email,
        role=body.role,
        site_ids=[str(s) for s in body.site_ids],
        token_hash=crypto.hash_token(token),
        invited_by=access.user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.invitation_ttl_s),
    )
    db.add(inv)
    audit.record(
        db,
        org_id=access.org.id,
        action="invitation.created",
        entity_type="invitation",
        entity_id=inv.id,
        user_id=access.user.id,
        details={"email": body.email, "role": body.role.value},
        request=request,
    )
    db.commit()

    lang = access.org.language.value
    link = f"{settings.public_web_url}/accept-invite#token={token}"
    mailer.send(
        Mail(
            to=body.email,
            subject=t(lang, "email.invitation.subject", org=access.org.name),
            body=t(
                lang,
                "email.invitation.body",
                org=access.org.name,
                inviter=access.user.name or access.user.email,
                role=t(lang, f"role.{body.role.value}"),
                link=link,
            ),
        )
    )
    return inv


@router.delete("/members/{user_id}", status_code=204)
def remove_member(user_id: uuid.UUID, request: Request, db: DB, access: MemberAdmin) -> None:
    ms = db.scalars(
        select(m.Membership).where(
            m.Membership.organisation_id == access.org.id, m.Membership.user_id == user_id
        )
    ).first()
    if ms is None:
        raise not_found("member")
    if ms.role is m.Role.OWNER:
        owners = db.scalar(
            select(func.count())
            .select_from(m.Membership)
            .where(m.Membership.organisation_id == access.org.id, m.Membership.role == m.Role.OWNER)
        )
        if (owners or 0) <= 1:
            raise APIError(409, "last_owner", "an organisation needs at least one owner")
    db.delete(ms)
    audit.record(
        db,
        org_id=access.org.id,
        action="member.removed",
        entity_type="membership",
        entity_id=user_id,
        user_id=access.user.id,
        request=request,
    )
    db.commit()
