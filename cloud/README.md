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

Dashboard (`Authorization: Bearer <access token>`): `/api/v1/auth/*`, `/api/v1/sites`,
`/api/v1/cameras`, `/api/v1/rules`, `/api/v1/devices`, `/api/v1/events`, `/api/v1/members`,
`/api/v1/invitations`, `/api/v1/admin/organisations` (Code-Ox admin).

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
jobs (CLD-06), recipients/zones/aggregates query endpoints (CLD-07), the Redis worker (CLD-17),
alert dispatch (CLD-08 onwards), plan limits (CLD-18), staging deployment (CLD-20).
