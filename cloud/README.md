# vision-cloud: Code-Ox Vision cloud backend

FastAPI + PostgreSQL 16 + S3-compatible object storage. It receives events, snapshots, clips and
per-minute counts from edge boxes, keeps tenants apart, and serves the dashboard API. Tasks:
CLD-01 to CLD-07, CLD-17 and CLD-19 basics (see `docs/development-task-plan.md`, Phase 4).

## Run it

With Docker (PostgreSQL, Redis, S3 storage and the API; the same stack also runs the dashboard, fake
cameras and edge, see `deploy/README.md`):

```bash
cp .env.example .env
uv run vision-cloud gen-keys            # paste the two lines into .env
docker compose -f deploy/docker-compose.dev.yml --env-file .env up --build
# API docs: http://localhost:8000/docs
```

Without Docker, against any PostgreSQL 16 you have (or SQLite for a quick look):

```bash
uv sync --all-packages
export VISION_CLOUD_DATABASE_URL=postgresql+psycopg://vision_owner:...@localhost:5432/vision
uv run vision-cloud migrate                                   # alembic upgrade head
uv run vision-cloud seed-demo --owner-email you@example.com   # demo organisation + site + device
uv run vision-cloud create-admin --email ops@code-ox.com      # Code-Ox platform admin
export VISION_CLOUD_DATABASE_URL=postgresql+psycopg://vision_app:...@localhost:5432/vision
uv run vision-cloud serve --port 8000
```

Run migrations as the schema owner and the API as a separate role **without superuser or
BYPASSRLS**, otherwise PostgreSQL skips the row-level-security policies
(`deploy/postgres-init/01-app-role.sh` shows the grants). Settings are environment variables with
the `VISION_CLOUD_` prefix (`src/vision_cloud/settings.py`, `.env.example`).

## Tests

```bash
uv run pytest cloud/tests                    # SQLite; PostgreSQL variants are skipped
VISION_CLOUD_TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/vision_test \
  uv run pytest cloud/tests                  # also PostgreSQL: migrations, RLS, every API test
```

The PostgreSQL run drops and recreates the `public` schema of that database, applies the Alembic
migrations, and connects the API as a fresh role without BYPASSRLS. CI runs it in
`.github/workflows/cloud.yml` against a `postgres:16` service container.

## Layout

| Module | What |
| --- | --- |
| `models.py` | ORM tables (CLD-01). Ids are UUID strings shared with `SiteConfig` / `Rule` / `Event` |
| `migrations/` | Alembic: `0001` schema, `0002` row-level security |
| `db.py` | Tenant sessions: automatic `organisation_id` filter + RLS settings per transaction |
| `security.py` | argon2id passwords, JWT access tokens, hashed opaque tokens, Fernet field encryption |
| `api/deps.py` | Principal (user or device), roles, per-site filter, audit helper |
| `api/auth.py` | Sign-in, refresh, invitations, members, Code-Ox admin |
| `api/manage.py` | Sites, cameras (zones, lines), rules, devices |
| `api/events.py` | Event list (filters, cursor pagination), detail with signed media URLs, feedback |
| `api/device.py` | Edge box API: enrol, heartbeat, config (ETag), model release, logs, events, media, aggregates |
| `services/` | Config building and versioning, ingest, accounts, seed |
| `storage.py` | S3-compatible storage (boto3) and a local-filesystem backend for dev and tests |
| `jobs.py` | `JobQueue` interface; Redis worker comes with CLD-17 |
| `errors.py` | One error format, `X-Request-ID`, security headers |

## API overview

Dashboard (`Authorization: Bearer <access token>`): `/api/v1/auth/*`, `/api/v1/sites` (with camera
counts and today's alerts), `/api/v1/sites/{id}/overview?date=` (alerts by type, 7-day false-alarm
rate, footfall by local hour, cameras online), `/api/v1/sites/{id}/rules` (rules with the
recipients each alerts; POST creates a rule and its recipients together),
`/api/v1/cameras`, `/api/v1/rules`, `/api/v1/devices`, `/api/v1/events`, `/api/v1/members`,
`/api/v1/invitations`, `/api/v1/recipients` (who gets alerts: channel, sites, rules, minimum
severity, quiet hours, daily cap, escalation rank; site manager or higher),
`/api/v1/sites/{id}/recipients` (names and channels only, for the rule builder),
`/api/v1/alerts` (grouped alerts, delivery log, acknowledge),
`/api/v1/admin/organisations` (Code-Ox admin).

Edge box (`Authorization: Bearer <device token>` from enrolment), all under `/device/v1`:

1. `POST /enrol` with the one-time enrolment token from `POST /api/v1/sites/{id}/devices`.
2. `POST /heartbeat` every 60 s; the reply carries the current config version and ETag.
3. `GET /config` with `If-None-Match`; 304 when unchanged, otherwise the shared `SiteConfig`.
4. `POST /events` (or `/events/batch`): idempotent on `Event.id`; re-sending the cleared version
   of an event updates it.
5. `POST /events/{id}/uploads` → pre-signed PUT URLs; upload; `POST /events/{id}/finalise`.
6. `POST /aggregates` per-minute counts (re-sending a minute overwrites it).

Payloads are in `shared/src/vision_shared/api.py`; the full schema is at `/docs` and `/openapi.json`.

## Not done yet

Password reset and 2FA (CLD-03), rate limits (CLD-05, CLD-19), storage lifecycle rules and delete
jobs (CLD-06), queue-length and dwell trends (CLD-07 aggregates beyond footfall), the WhatsApp
channel (CLD-09), plan
limits (CLD-18), staging deployment (CLD-20).

## Alerts (CLD-08)

The worker turns every new event into an alert. Events of the same camera and rule within 2 minutes
of each other (`VISION_CLOUD_ALERT_GROUP_WINDOW_S`) are one alert with a count, so a burst of 30
events is one message. A new alert goes to every enabled recipient for that site (or all sites) at
or above their minimum severity, following that rule (or all rules), without an escalation rank or
with rank 1. During a recipient's quiet hours and after their daily cap only critical alerts are
sent; the rest are kept in the delivery log (`notifications`) as `suppressed` with the reason.
Messages are in the recipient's language (English or Arabic, `services/messages.py`).

Escalation: when a critical alert opens (or a grouped event makes it critical), a check is scheduled
for 10 minutes later (`VISION_CLOUD_ALERT_ESCALATION_AFTER_S`). If nobody has acknowledged it by
then, recipients with escalation rank 2 get an "escalated" message, then rank 3 ten minutes later,
until the chain ends. Acknowledging stops it: `POST /api/v1/alerts/{id}/acknowledge` ("I'm on it"),
or feedback on one of its events. `GET /api/v1/alerts` and `GET /api/v1/alerts/{id}` show alerts
with their delivery log (recipient names, never addresses).

## Telegram (CLD-10)

Alerts to Telegram chats: the snapshot (waiting up to 20 s for the edge to upload it), the text in
the recipient's language, and Correct / False alarm / I'm on it buttons. Taps arrive at
`POST /integrations/telegram/webhook` (checked with `X-Telegram-Bot-Api-Secret-Token`, and only
from the chat the alert went to), store feedback and acknowledge the alert. People link their chat
with a one-time code from `POST /api/v1/recipients/{id}/telegram-link`. Setup:
`docs/runbooks/telegram-alerts.md`; `vision-cloud telegram check` and `set-webhook`.
