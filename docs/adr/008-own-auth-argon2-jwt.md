# ADR 008: Our own small auth module (argon2id + short-lived JWT + rotating refresh tokens)

Status: accepted (2 Nov 2026)

**Decision.** The cloud signs users in itself instead of using `fastapi-users` or Keycloak:
passwords hashed with argon2id (`argon2-cffi`), a 15-minute HS256 access token (`pyjwt`) that
carries the user and the organisation they act in, and an opaque 30-day refresh token stored only as
a SHA-256 hash and rotated on every use (re-use of a rotated token revokes all of that user's
refresh tokens). People join by invitation (one-time token, 7 days). Device credentials, enrolment
tokens and invitation tokens follow the same "random token, store the hash" pattern.

**Why.** We need exactly email + password, invitations, per-organisation roles and per-site access,
and the tenant id in the token so every request runs inside one organisation (CLD-02). Keycloak is a
second service to run, back up and secure on every in-Kingdom deployment for a few dozen users per
customer; `fastapi-users` brings its own user model and does not know organisations or sites. The
code we need is about 300 lines on two small, widely used libraries.

**Consequences.** We own the security-sensitive code, so it is covered by tests (rotation, re-use,
expiry, cross-organisation tokens) and must be reviewed when changed. Still to do in CLD-03:
password reset (needs email delivery), optional authenticator-app 2FA (TOTP), rate limiting of
sign-in attempts. If a customer requires SSO (SAML/OIDC), revisit Keycloak then.
