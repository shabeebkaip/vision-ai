# Code-Ox Vision cloud backend

FastAPI + PostgreSQL 16 service that stores events from edge boxes, serves their configuration and
backs the dashboard. Tasks CLD-01 to CLD-05 of `docs/development-task-plan.md` are implemented
here:

| Task | What | Where |
| --- | --- | --- |
| CLD-01 | Schema for every table in the plan, Alembic migration, demo seed | `models.py`, `migrations/`, `seed.py` |
| CLD-02 | Roles, per-site access, PostgreSQL row-level security | `permissions.py`, `tenancy.py`, `db.py`, `api/deps.py`, `api/orgs.py` |
| CLD-03 | argon2 passwords, invitations, password reset, TOTP 2FA, JWT access + rotating refresh tokens | `security.py`, `api/auth.py`, `docs/adr/0001-cloud-authentication.md` |
| CLD-04 | Device enrolment, heartbeat, config with ETag, model release, log upload | `api/device.py`, `siteconfig.py` |
| CLD-05 | Idempotent event ingest, batches, pre-signed uploads + finalise, aggregates, per-device rate limit | `api/ingest.py`, `services/ingest.py`, `storage.py`, `ratelimit.py` |

## Run it locally

You need PostgreSQL 16 (Redis and MinIO are optional in development; `deploy/docker-compose.dev.yml`
from REP-05 will start all three).

```bash
# 1. a database and an ordinary (non-superuser) role
createuser --createdb vision --pwprompt
createdb -O vision vision

# 2. settings
cp cloud/.env.example cloud/.env      # fill in VISION_JWT_SECRET and VISION_ENCRYPTION_KEY
uv run vision-cloud gen-key           # prints a VISION_ENCRYPTION_KEY

# 3. schema, demo data, a Code-Ox admin
cd cloud
uv run vision-cloud migrate
uv run vision-cloud seed              # prints the demo owner's password once
uv run vision-cloud create-admin you@code-ox.com

# 4. API on http://localhost:8000 (OpenAPI docs at /docs)
uv run vision-cloud serve --reload
```

Enrol an edge box: `uv run vision-cloud enrolment-token <site-uuid>` (or
`POST /api/v1/admin/enrolment-tokens`), then on the box `POST /device/v1/enrol` with the token.

## Tests

```bash
export VISION_TEST_DATABASE_URL=postgresql+psycopg://vision:vision@localhost:5432/postgres
uv run pytest cloud/tests
```

Each run creates and drops its own database. The role must be able to `CREATE DATABASE` and must
not be a superuser (superusers ignore row-level security, so the isolation tests would be
meaningless). Without a reachable server the cloud tests are skipped.

## API at a glance

Dashboard (`Authorization: Bearer <access token>`):

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/auth/login` | email + password (+ `otp` when 2FA is on) → access + refresh token |
| `POST /api/v1/auth/refresh`, `/logout` | rotate / revoke refresh token (re-use of a rotated token revokes the family) |
| `GET /api/v1/auth/invitations/{token}`, `POST /api/v1/auth/invitations/accept` | invitation preview and acceptance |
| `POST /api/v1/auth/password-reset/request`, `/confirm` | reset by email link |
| `POST /api/v1/auth/2fa/setup`, `/enable`, `/disable` | authenticator-app 2FA |
| `GET /api/v1/me` | user and memberships |
| `GET /api/v1/orgs/{org}` `/sites` `/cameras` `/devices` `/events` `/members` | tenant reads (full CRUD is CLD-07) |
| `POST /api/v1/orgs/{org}/invitations`, `DELETE /api/v1/orgs/{org}/members/{user}` | people |
| `/api/v1/admin/...` | Code-Ox admin: organisations, enrolment tokens, devices, model releases |

Edge box (`Authorization: Bearer <device credential>`):

| Method and path | Purpose |
| --- | --- |
| `POST /device/v1/enrol` | one-time token → device credential (shown once) |
| `POST /device/v1/heartbeat` | health; reply carries latest config version and "send logs" flag |
| `GET /device/v1/config` | `vision_shared` `SiteConfig`; `ETag` / `If-None-Match` → 304 |
| `GET /device/v1/model-release` | model for the device's channel with a signed download URL |
| `POST /device/v1/logs` | pre-signed upload form for a log bundle |
| `POST /device/v1/events`, `/events/batch` | `vision_shared` `Event`(s); idempotent on the event id |
| `POST /device/v1/events/{id}/media/{snapshot\|clip}/finalise` | confirm an upload landed |
| `POST /device/v1/aggregates` | per-minute counts; re-sending a minute replaces it |

### Event delivery, step by step (for EDG-12)

1. Send the event JSON exactly as `OutboxSink` writes it. The edge's `snapshot_key`/`clip_key` only
   signal that media exists; the cloud picks its own storage key.
2. The receipt holds `snapshot_upload` / `clip_upload`: a pre-signed POST form (`url`, `fields`,
   `max_bytes`). POST the fields plus the file as `file` straight to storage.
3. Call `.../media/{kind}/finalise`. The cloud checks the object exists.
4. Re-send the same event any time (lost response, cleared state, clip ready): the id is the
   idempotency key. A receipt `duplicate` means nothing changed; `updated` means it moved forward.

Sites with `events_only` never receive upload forms.

## Layout

```
cloud/
  alembic.ini
  src/vision_cloud/
    app.py  main.py  cli.py  settings.py  logs.py  errors.py
    models.py  tenancy.py  db.py  migrations/     schema, RLS, sessions
    security.py  permissions.py  crypto.py         auth building blocks
    api/   auth.py  orgs.py  admin.py  device.py  ingest.py  deps.py  schemas.py
    services/  auth.py  ingest.py  audit.py
    contract.py                                    device messages proposed for shared/
    siteconfig.py  storage.py  ratelimit.py  mailer.py  seed.py  i18n/
  tests/
```
