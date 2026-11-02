"""Code-Ox admin endpoints: organisations, enrolment tokens, devices, model releases.

These are deliberately cross-tenant (Code-Ox operations), so they use a system session after
checking `is_platform_admin`. The fleet view (CLD-15) and admin console (WEB-15) build on them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from vision_cloud import crypto
from vision_cloud import models as m
from vision_cloud.api.deps import MailerDep, PlatformAdmin, Sessions, Settings
from vision_cloud.api.schemas import (
    DeviceOut,
    EnrolmentTokenIn,
    EnrolmentTokenOut,
    ModelReleaseIn,
    ModelReleaseOut,
    OrganisationIn,
    OrganisationOut,
)
from vision_cloud.db import system_session
from vision_cloud.errors import APIError, not_found
from vision_cloud.i18n import t
from vision_cloud.mailer import Mail
from vision_cloud.services import audit

router = APIRouter(prefix="/api/v1/admin", tags=["code-ox admin"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/organisations", response_model=OrganisationOut, status_code=201)
def create_organisation(
    body: OrganisationIn,
    request: Request,
    admin: PlatformAdmin,
    sessions: Sessions,
    settings: Settings,
    mailer: MailerDep,
) -> m.Organisation:
    """Create a customer organisation and invite its first owner."""
    token = crypto.new_token()
    with system_session(sessions) as db:
        org = m.Organisation(
            id=uuid.uuid4(),
            name=body.name,
            slug=body.slug,
            plan=body.plan,
            language=body.language,
            timezone=body.timezone,
        )
        db.add(org)
        try:
            db.flush()
        except IntegrityError:
            raise APIError(409, "slug_taken", "an organisation with this slug exists") from None
        db.add(
            m.Invitation(
                organisation_id=org.id,
                email=body.owner_email,
                role=m.Role.OWNER,
                site_ids=[],
                token_hash=crypto.hash_token(token),
                invited_by=admin.id,
                expires_at=_now() + timedelta(seconds=settings.invitation_ttl_s),
            )
        )
        audit.record(
            db,
            org_id=org.id,
            action="organisation.created",
            entity_type="organisation",
            entity_id=org.id,
            user_id=admin.id,
            details={"owner_email": body.owner_email},
            request=request,
        )
        db.commit()
    lang = body.language.value
    mailer.send(
        Mail(
            to=body.owner_email,
            subject=t(lang, "email.invitation.subject", org=body.name),
            body=t(
                lang,
                "email.invitation.body",
                org=body.name,
                inviter="Code-Ox",
                role=t(lang, "role.owner"),
                link=f"{settings.public_web_url}/accept-invite#token={token}",
            ),
        )
    )
    return org


@router.post("/enrolment-tokens", response_model=EnrolmentTokenOut, status_code=201)
def create_enrolment_token(
    body: EnrolmentTokenIn,
    request: Request,
    admin: PlatformAdmin,
    sessions: Sessions,
    settings: Settings,
) -> EnrolmentTokenOut:
    token = "enr_" + crypto.new_token()
    expires = _now() + timedelta(seconds=body.ttl_s or settings.enrolment_token_ttl_s)
    with system_session(sessions) as db:
        site = db.get(m.Site, body.site_id)
        if site is None or site.organisation_id != body.organisation_id:
            raise not_found("site")
        db.add(
            m.EnrolmentToken(
                organisation_id=site.organisation_id,
                site_id=site.id,
                device_name=body.device_name,
                token_hash=crypto.hash_token(token),
                expires_at=expires,
                created_by=admin.id,
            )
        )
        audit.record(
            db,
            org_id=site.organisation_id,
            action="enrolment_token.created",
            entity_type="site",
            entity_id=site.id,
            user_id=admin.id,
            request=request,
        )
        db.commit()
    return EnrolmentTokenOut(token=token, expires_at=expires)


@router.get("/devices", response_model=list[DeviceOut])
def list_all_devices(admin: PlatformAdmin, sessions: Sessions) -> list[m.Device]:
    with system_session(sessions) as db:
        return list(db.scalars(select(m.Device).order_by(m.Device.enrolled_at)).all())


def _device_action(
    sessions: Sessions, admin: m.User, request: Request, device_id: uuid.UUID, action: str
) -> None:
    with system_session(sessions) as db:
        device = db.get(m.Device, device_id)
        if device is None:
            raise not_found("device")
        if action == "device.revoked":
            device.status = m.DeviceStatus.REVOKED
        elif action == "device.logs_requested":
            device.logs_requested_at = _now()
        audit.record(
            db,
            org_id=device.organisation_id,
            action=action,
            entity_type="device",
            entity_id=device.id,
            user_id=admin.id,
            request=request,
        )
        db.commit()


@router.post("/devices/{device_id}/revoke", status_code=204)
def revoke_device(
    device_id: uuid.UUID, request: Request, admin: PlatformAdmin, sessions: Sessions
) -> Response:
    _device_action(sessions, admin, request, device_id, "device.revoked")
    return Response(status_code=204)


@router.post("/devices/{device_id}/request-logs", status_code=204)
def request_device_logs(
    device_id: uuid.UUID, request: Request, admin: PlatformAdmin, sessions: Sessions
) -> Response:
    _device_action(sessions, admin, request, device_id, "device.logs_requested")
    return Response(status_code=204)


@router.post("/model-releases", response_model=ModelReleaseOut, status_code=201)
def create_model_release(
    body: ModelReleaseIn, admin: PlatformAdmin, sessions: Sessions
) -> m.ModelRelease:
    with system_session(sessions) as db:
        release = m.ModelRelease(
            name=body.name,
            version=body.version,
            channel=m.ReleaseChannel(body.channel),
            file_key=body.file_key,
            sha256=body.sha256,
            size_bytes=body.size_bytes,
            notes=body.notes,
        )
        db.add(release)
        try:
            db.commit()
        except IntegrityError:
            raise APIError(409, "release_exists", "this model name and version exist") from None
        return release
