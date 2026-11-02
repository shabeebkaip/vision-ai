"""CLD-03: invite, sign-in, refresh, reset and 2FA work end to end."""

from __future__ import annotations

import re
from typing import Any

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import PASSWORD, add_user, auth, login, make_tenant


def _token_from_mail(app: Any) -> str:
    body = app.state.mailer.outbox[-1].body
    match = re.search(r"#token=([\w-]+)", body)
    assert match, body
    return match.group(1)


def test_invite_accept_and_sign_in(
    client: TestClient, app: Any, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    owner = auth(login(client, a.owner_email))
    r = client.post(
        f"/api/v1/orgs/{a.org_id}/invitations",
        json={
            "email": "New.Person@Example.com",
            "role": "site_manager",
            "site_ids": [str(a.site_id)],
        },
        headers=owner,
    )
    assert r.status_code == 201, r.text
    mail = app.state.mailer.outbox[-1]
    assert mail.to == "new.person@example.com" and "Org org-a" in mail.subject
    token = _token_from_mail(app)

    preview = client.get(f"/api/v1/auth/invitations/{token}").json()
    assert preview["role"] == "site_manager" and preview["existing_account"] is False

    r = client.post("/api/v1/auth/invitations/accept", json={"token": token, "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    r = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "password": "a good long password", "name": "New Person"},
    )
    assert r.status_code == 200, r.text
    me = client.get("/api/v1/me", headers=auth(r.json())).json()
    assert me["email"] == "new.person@example.com"
    assert me["memberships"][0]["role"] == "site_manager"
    assert me["memberships"][0]["all_sites"] is False

    # One use only.
    r = client.post("/api/v1/auth/invitations/accept", json={"token": token, "password": "x" * 12})
    assert r.status_code == 400
    login(client, "NEW.person@example.com", "a good long password")


def test_existing_user_must_prove_password_to_join(
    client: TestClient, app: Any, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    b = make_tenant(sessions, "org-b")
    owner_b = auth(login(client, b.owner_email))
    r = client.post(
        f"/api/v1/orgs/{b.org_id}/invitations",
        json={"email": a.owner_email, "role": "viewer"},
        headers=owner_b,
    )
    assert r.status_code == 201
    token = _token_from_mail(app)
    bad = {"token": token, "password": "not their password"}
    assert client.post("/api/v1/auth/invitations/accept", json=bad).status_code == 401
    r = client.post("/api/v1/auth/invitations/accept", json={"token": token, "password": PASSWORD})
    assert r.status_code == 200
    me = client.get("/api/v1/me", headers=auth(r.json())).json()
    assert {ms["organisation_name"] for ms in me["memberships"]} == {"Org org-a", "Org org-b"}


def test_wrong_password_and_unknown_user_look_the_same(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    r1 = client.post("/api/v1/auth/login", json={"email": a.owner_email, "password": "wrong-pass"})
    r2 = client.post(
        "/api/v1/auth/login", json={"email": "nobody@x.test", "password": "wrong-pass"}
    )
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"] == r2.json()["error"]


def test_refresh_rotates_and_reuse_revokes_family(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    first = login(client, a.owner_email)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    # Replaying the old token is treated as theft: the new one stops working as well.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "refresh_token_reused"
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert r.status_code == 401


def test_logout_revokes_refresh_token(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    tokens = login(client, a.owner_email)
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 204
    )
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_password_reset(client: TestClient, app: Any, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    old = login(client, a.owner_email)

    r = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@x.test"})
    assert r.status_code == 202 and app.state.mailer.outbox == []
    r = client.post("/api/v1/auth/password-reset/request", json={"email": a.owner_email})
    assert r.status_code == 202
    token = _token_from_mail(app)

    r = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "a brand new password"},
    )
    assert r.status_code == 204
    # Old sessions are signed out; old password no longer works; the link is single use.
    assert client.get("/api/v1/me", headers=auth(old)).status_code == 401
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": a.owner_email, "password": PASSWORD})
    assert r.status_code == 401
    login(client, a.owner_email, "a brand new password")
    r = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": "another password"}
    )
    assert r.status_code == 400


def test_reset_email_in_arabic_for_arabic_user(
    client: TestClient, app: Any, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    add_user(sessions, a, "ar@org-a.test", "viewer")  # users default to Arabic
    client.post("/api/v1/auth/password-reset/request", json={"email": "ar@org-a.test"})
    assert "كلمة المرور" in app.state.mailer.outbox[-1].subject


def test_two_factor(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    headers = auth(login(client, a.owner_email))
    setup = client.post("/api/v1/auth/2fa/setup", headers=headers).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(setup["secret"])

    assert (
        client.post("/api/v1/auth/2fa/enable", json={"code": "000000"}, headers=headers).status_code
        == 400
    )
    r = client.post("/api/v1/auth/2fa/enable", json={"code": totp.now()}, headers=headers)
    assert r.status_code == 204

    r = client.post("/api/v1/auth/login", json={"email": a.owner_email, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_required"
    r = client.post(
        "/api/v1/auth/login", json={"email": a.owner_email, "password": PASSWORD, "otp": "123456"}
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "otp_invalid"
    tokens = login(client, a.owner_email, otp=totp.now())
    assert client.get("/api/v1/me", headers=auth(tokens)).json()["totp_enabled"] is True

    r = client.post(
        "/api/v1/auth/2fa/disable",
        json={"code": totp.now(), "password": PASSWORD},
        headers=auth(tokens),
    )
    assert r.status_code == 204
    login(client, a.owner_email)


def test_totp_secret_encrypted_at_rest(client: TestClient, sessions: sessionmaker[Session]) -> None:
    from sqlalchemy import text

    from vision_cloud.db import system_session

    a = make_tenant(sessions, "org-a")
    secret = client.post(
        "/api/v1/auth/2fa/setup", headers=auth(login(client, a.owner_email))
    ).json()["secret"]
    with system_session(sessions) as db:
        raw = db.execute(
            text("SELECT totp_secret FROM users WHERE id = :u"), {"u": a.owner_id}
        ).scalar_one()
    assert secret not in raw


def test_login_is_rate_limited(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    codes = [
        client.post(
            "/api/v1/auth/login", json={"email": a.owner_email, "password": "nope-nope"}
        ).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10 and codes[-1] == 429


def test_errors_have_one_shape(client: TestClient) -> None:
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "not_authenticated" and body["request_id"]
    r = client.post("/api/v1/auth/login", json={"email": "bad"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
