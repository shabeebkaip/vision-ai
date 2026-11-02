# ADR 0001 — Cloud authentication: a small in-house layer, not fastapi-users or Keycloak

- Status: proposed (CLD-03)
- Date: 2 November 2026
- Deciders: BE, LD, PO

## Context

CLD-03 asks for email and password sign-in (argon2), an invitation flow, password reset, optional
authenticator-app 2FA, and short-lived access tokens with refresh tokens, and for the library choice
to be recorded here. The plan named two candidates: `fastapi-users` or Keycloak.

What we need on top of plain sign-in is unusual for both candidates:

- Users are global, but access is per organisation and per site (`memberships`,
  `membership_sites`), checked on every request and enforced again by PostgreSQL row-level security.
- Invitations create a membership with a role and site list, and may attach to an existing account.
- The Code-Ox admin is a flag that crosses tenants.
- Removing a member, resetting a password or disabling a user must take effect immediately.

## Options

1. **fastapi-users** (MIT). Gives register/login/reset/verify routes and JWT or database strategies.
   It has no invitations, no TOTP, and no organisations; we would override most routes anyway. The
   project announced it is in maintenance mode (security fixes only), which is a poor base for a
   component we will own for years.
2. **Keycloak** (Apache-2.0). Full identity server: TOTP, reset, invitations by admin API, SSO later.
   Costs another stateful Java service on the staging and production servers (memory, upgrades,
   backups, its own database), a second place where roles live, and Arabic email templates in its
   theme system. Worth it when customers ask for SSO/SAML; not for the MVP.
3. **Small in-house layer on vetted primitives** (chosen): `argon2-cffi` (MIT) for argon2id,
   `PyJWT` (MIT) for HS256 access tokens, `pyotp` (MIT) for RFC 6238 TOTP, `cryptography`
   (Apache-2.0/BSD) for encrypting the TOTP secret at rest. About 400 lines in
   `cloud/src/vision_cloud/security.py`, `services/auth.py` and `api/auth.py`, fully tested.

## Decision

Option 3.

- Access token: JWT HS256, 15 minutes, claims `sub`, `ver` (user's token version), `iat`, `exp`,
  `iss`, `typ`. The API loads the user on each request and rejects the token if the user is
  inactive or `ver` changed, so a password reset signs every session out immediately.
- Refresh token: random 256-bit opaque value, 30 days, stored as SHA-256 only, rotated on every
  use. Presenting an already-rotated token revokes its whole family (theft detection).
- Passwords: argon2id with the library's current parameters, rehashed on login when they change;
  minimum 10 characters. Sign-in is rate-limited per email.
- Invitations and password resets: random one-time tokens stored as SHA-256, sent as URL fragments
  (`#token=`) so they do not land in web-server logs or `Referer` headers; 7 days and 1 hour.
- 2FA: TOTP (30 s, 6 digits, ±1 step), secret encrypted with Fernet; enabling needs a valid code,
  disabling needs password and code.
- The reset endpoint always answers 202 so it does not reveal which emails have accounts; wrong
  password and unknown email give the same error.

## Consequences

- We own security-sensitive code: it stays small, uses no home-made cryptography, and every path
  has a test (`cloud/tests/test_auth.py`).
- When an enterprise customer needs SSO (SAML/OIDC), revisit: Keycloak or a hosted IdP can be put
  in front and mapped onto `users` and `memberships` without changing the tenancy model.
- New dependencies `argon2-cffi`, `pyjwt`, `pyotp`, `cryptography` are added to
  `docs/approved-libraries.md`.
