"""CLD-03: sign-in, refresh rotation, invitations; CLD-02: roles and per-site access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from vision_cloud.db import system_session
from vision_cloud.models import Invitation, User
from vision_cloud.security import hash_password, verify_password

from .conftest import PASSWORD, World, auth


def test_login_and_me(world: World) -> None:
    c = world.client
    r = c.post("/api/v1/auth/login", json={"email": "OWNER@alpha.test", "password": PASSWORD})
    assert r.status_code == 200
    tokens = r.json()
    assert tokens["organisation_id"] == world.a.org_id
    assert tokens["role"] == "owner"
    me = c.get("/api/v1/auth/me", headers=auth(tokens["access_token"])).json()
    assert me["email"] == "owner@alpha.test"
    assert me["site_ids"] is None
    assert [o["id"] for o in me["organisations"]] == [world.a.org_id]


def test_wrong_password_and_unknown_user_look_the_same(world: World) -> None:
    c = world.client
    r1 = c.post("/api/v1/auth/login", json={"email": "owner@alpha.test", "password": "nope-nope"})
    r2 = c.post("/api/v1/auth/login", json={"email": "ghost@alpha.test", "password": "nope-nope"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"]
    assert r1.json()["error"]["code"] == "invalid_credentials"


def test_no_token_bad_token_expired_token(world: World) -> None:
    c = world.client
    assert c.get("/api/v1/sites").status_code == 401
    assert c.get("/api/v1/sites", headers=auth("garbage")).status_code == 401
    state = c.app.state.vision  # type: ignore[attr-defined]
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "iss": state.settings.jwt_issuer,
            "sub": "u",
            "org": world.a.org_id,
            "typ": "access",
            "jti": "j",
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        },
        state.settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    r = c.get("/api/v1/sites", headers=auth(expired))
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    # A token signed with another key is refused.
    forged = jwt.encode(
        {
            "iss": "codeox-vision",
            "sub": "u",
            "org": world.b.org_id,
            "typ": "access",
            "jti": "j",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        "not-the-key-not-the-key-not-the-key",
        algorithm="HS256",
    )
    assert c.get("/api/v1/sites", headers=auth(forged)).status_code == 401
    # A device token is not a user token.
    assert c.get("/api/v1/sites", headers=auth(world.a.device_token)).status_code == 401


def test_token_for_an_org_without_membership_is_refused(world: World) -> None:
    """A valid signature is not enough: the user must belong to the token's organisation."""
    c = world.client
    state = c.app.state.vision  # type: ignore[attr-defined]
    me = c.get("/api/v1/auth/me", headers=auth(world.a.owner_token)).json()
    from vision_cloud.security import issue_access_token

    token, _ = issue_access_token(
        secret=state.settings.jwt_secret.get_secret_value(),
        issuer=state.settings.jwt_issuer,
        user_id=me["user_id"],
        organisation_id=world.b.org_id,
        ttl_s=60,
    )
    assert c.get("/api/v1/sites", headers=auth(token)).status_code == 401


def test_refresh_rotates_and_reuse_signs_out_everywhere(world: World) -> None:
    c = world.client
    first = c.post(
        "/api/v1/auth/login", json={"email": "owner@alpha.test", "password": PASSWORD}
    ).json()
    second = c.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    second_tokens = second.json()
    assert second_tokens["refresh_token"] != first["refresh_token"]
    assert c.get("/api/v1/sites", headers=auth(second_tokens["access_token"])).status_code == 200
    # Reusing the rotated token: refused, and the newer token is revoked too.
    reuse = c.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "token_reused"
    again = c.post("/api/v1/auth/refresh", json={"refresh_token": second_tokens["refresh_token"]})
    assert again.status_code == 401


def test_logout_revokes_refresh_token(world: World) -> None:
    c = world.client
    t = c.post(
        "/api/v1/auth/login", json={"email": "owner@alpha.test", "password": PASSWORD}
    ).json()
    assert (
        c.post("/api/v1/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 204
    )
    r = c.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 401


def test_passwords_are_argon2_hashed(world: World) -> None:
    sessions = world.client.app.state.vision.sessions  # type: ignore[attr-defined]
    with system_session(sessions) as db:
        user = db.query(User).filter(User.email == "owner@alpha.test").one()
        assert user.password_hash and user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
    assert verify_password(hash_password("abcdefghij"), "abcdefghij")
    assert not verify_password(None, "abcdefghij")


def test_invitation_roles_and_site_scope(world: World) -> None:
    c, a = world.client, world.a
    viewer = world.invite(a, "viewer@alpha.test", "viewer", [a.site_ids[1]])
    h = auth(viewer)
    assert [s["id"] for s in c.get("/api/v1/sites", headers=h).json()] == [a.site_ids[1]]
    assert [x["id"] for x in c.get("/api/v1/cameras", headers=h).json()] == [a.camera_ids[1]]
    # The event is on site 1: invisible to a viewer of site 2.
    assert c.get("/api/v1/events", headers=h).json()["items"] == []
    assert c.get(f"/api/v1/events/{a.event_id}", headers=h).status_code == 404
    assert c.get(f"/api/v1/sites/{a.site_ids[0]}", headers=h).status_code == 404
    # Viewers cannot write.
    assert c.post("/api/v1/sites", json={"name": "x"}, headers=h).status_code == 403
    r = c.patch(f"/api/v1/cameras/{a.camera_ids[1]}", json={"name": "x"}, headers=h)
    assert r.status_code == 403
    me = c.get("/api/v1/auth/me", headers=h).json()
    assert me["role"] == "viewer" and me["site_ids"] == [a.site_ids[1]]

    site_mgr = world.invite(a, "sm@alpha.test", "site_manager", [a.site_ids[0]])
    hs = auth(site_mgr)
    r = c.post(f"/api/v1/events/{a.event_id}/feedback", json={"is_true": True}, headers=hs)
    assert r.status_code == 201
    assert c.post("/api/v1/sites", json={"name": "x"}, headers=hs).status_code == 403
    # Site managers and viewers cannot invite.
    r = c.post(
        "/api/v1/invitations",
        json={"email": "x@alpha.test", "role": "viewer", "site_ids": [a.site_ids[0]]},
        headers=hs,
    )
    assert r.status_code == 403

    manager = world.invite(a, "mgr@alpha.test", "manager", [])
    hm = auth(manager)
    r = c.post("/api/v1/invitations", json={"email": "o2@alpha.test", "role": "owner"}, headers=hm)
    assert r.status_code == 403  # only owners invite owners
    members = c.get("/api/v1/members", headers=hm).json()
    assert {m["email"] for m in members} == {
        "owner@alpha.test",
        "viewer@alpha.test",
        "sm@alpha.test",
        "mgr@alpha.test",
    }


def test_invitation_is_one_time_and_expires(world: World) -> None:
    c, a = world.client, world.a
    r = c.post(
        "/api/v1/invitations",
        json={"email": "new@alpha.test", "role": "manager"},
        headers=auth(a.owner_token),
    )
    token = r.json()["token"]
    weak = c.post("/api/v1/auth/accept-invitation", json={"token": token, "password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"
    ok = c.post("/api/v1/auth/accept-invitation", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200
    again = c.post("/api/v1/auth/accept-invitation", json={"token": token, "password": PASSWORD})
    assert again.status_code == 400

    r = c.post(
        "/api/v1/invitations",
        json={"email": "late@alpha.test", "role": "manager"},
        headers=auth(a.owner_token),
    )
    sessions = c.app.state.vision.sessions  # type: ignore[attr-defined]
    with system_session(sessions) as db:
        inv = db.query(Invitation).filter(Invitation.email == "late@alpha.test").one()
        inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    late = c.post(
        "/api/v1/auth/accept-invitation", json={"token": r.json()["token"], "password": PASSWORD}
    )
    assert late.status_code == 400


def test_existing_user_joins_second_org_and_switches(world: World) -> None:
    c, a, b = world.client, world.a, world.b
    r = c.post(
        "/api/v1/invitations",
        json={"email": "owner@alpha.test", "role": "viewer", "site_ids": [b.site_ids[0]]},
        headers=auth(b.owner_token),
    )
    token = r.json()["token"]
    # Joining with the wrong password of the existing account is refused.
    bad = c.post("/api/v1/auth/accept-invitation", json={"token": token, "password": "x" * 12})
    assert bad.status_code == 401
    ok = c.post("/api/v1/auth/accept-invitation", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["organisation_id"] == b.org_id
    # Default sign-in goes to the first organisation; switching needs an explicit choice.
    t = c.post("/api/v1/auth/login", json={"email": "owner@alpha.test", "password": PASSWORD})
    assert t.json()["organisation_id"] == a.org_id
    sw = c.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": t.json()["refresh_token"], "organisation_id": b.org_id},
    ).json()
    assert sw["organisation_id"] == b.org_id and sw["role"] == "viewer"
    sites = c.get("/api/v1/sites", headers=auth(sw["access_token"])).json()
    assert [s["id"] for s in sites] == [b.site_ids[0]]
    me = c.get("/api/v1/auth/me", headers=auth(sw["access_token"])).json()
    assert {o["id"] for o in me["organisations"]} == {a.org_id, b.org_id}
    # Cannot switch into an organisation without membership.
    other = c.post(
        "/api/v1/auth/login",
        json={"email": "viewer-none@x.test", "password": PASSWORD, "organisation_id": b.org_id},
    )
    assert other.status_code == 401


def test_only_platform_admin_creates_organisations(world: World) -> None:
    r = world.client.post(
        "/api/v1/admin/organisations",
        json={"name": "Charlie", "owner_email": "o@charlie.test"},
        headers=auth(world.a.owner_token),
    )
    assert r.status_code == 403
