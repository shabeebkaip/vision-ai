## Phase 4 — Cloud backend (weeks 3 to 12)

About 46 developer-days (BE ×2, DO, CV for the VLM check). The cloud never sees live video: it receives events, snapshots, clips and per-minute counts from edge boxes, decides who gets alerted and how, stores feedback, and serves the dashboard. Stack: FastAPI, PostgreSQL 16, Redis, S3-compatible object storage, one worker process for background jobs.

**Core data model**

| Table | Holds |
| --- | --- |
| `organisations` | Customer company, plan, language, time zone |
| `users`, `memberships` | People, their role per organisation and per site |
| `sites` | Branch or building; address, opening hours, plan limits |
| `devices` | Edge boxes: enrolment, hardware tier, versions, last heartbeat |
| `cameras` | Name, stream URL (encrypted), resolution, status, snapshot |
| `zones`, `lines` | Normalised geometry per camera |
| `rules` | Type, parameters, schedule, cooldown, severity, verify flag, recipients |
| `events` | Rule, camera, time, attributes, snapshot and clip keys, VLM verdict, status |
| `event_feedback` | True / false, by whom, through which channel, when |
| `recipients`, `notifications` | Who gets which alerts on which channel; every delivery attempt and its status |
| `aggregates_minute` | Counts per camera per minute (occupancy, in/out, queue, dwell) |
| `config_versions`, `model_releases` | What config and model each device should run |
| `audit_log` | Every change to rules, zones, recipients and every clip viewed |

Every customer-owned table carries `organisation_id`, and access is filtered on it both in code and by PostgreSQL row-level security.

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| CLD-01 | Database schema and Alembic migrations for the tables above, seed data for one demo organisation | BE | 3 | Must | REP-04 | `alembic upgrade head` builds the schema; seed loads |
| CLD-02 | Multi-tenancy and permissions: roles Code-Ox admin, organisation owner, manager, site manager, viewer; per-site access; PostgreSQL row-level security as the second lock | BE | 3 | Must | CLD-01 | Automated test: a user of organisation A cannot read any row of organisation B through any endpoint |
| CLD-03 | Login: email and password (argon2), invitation flow, password reset, optional authenticator-app 2FA, short-lived access token plus refresh token. Library choice recorded as an ADR (`fastapi-users` or Keycloak) | BE | 3 | Must | CLD-02 | Invite, sign-in, reset and 2FA work end to end |
| CLD-04 | Device API: enrolment with one-time token → device credential; heartbeat ingest; config endpoint with ETag; model release endpoint; log upload endpoint | BE | 3 | Must | CLD-01 | An edge box enrols, heartbeats and pulls config against staging |
| CLD-05 | Event ingest API: idempotent create, pre-signed upload URLs for snapshot and clip, finalise call, aggregates batch ingest, schema validation, rate limit per device | BE | 2 | Must | CLD-04 | Duplicate event submissions create one event; a 10,000-event burst is accepted |
| CLD-06 | Object storage: key layout `org/site/camera/yyyy/mm/dd/event`, server-side encryption, lifecycle rules (clips 30 days default, 7 to 90 by plan; snapshots 90 days), signed view URLs valid 5 minutes, delete-on-request job | DO, BE | 1.5 | Must | SET-09 | Expired clips disappear on schedule; a direct bucket URL without signature is refused |
| CLD-07 | Management API for the dashboard: CRUD for sites, cameras, zones, lines, rules, recipients; event list with filters (site, camera, rule, severity, date, status, verified) and pagination; event detail; feedback; aggregates queries; OpenAPI docs | BE | 4 | Must | CLD-02 | Dashboard team builds against the generated client with no hand-written calls |
| CLD-08 | Alert dispatcher worker: takes new events from a Redis queue; picks recipients by site, rule, severity and schedule; quiet hours; grouping (same camera and rule within 2 minutes becomes one alert with a count); daily cap per recipient; escalation (unacknowledged critical alert goes to the next person after 10 minutes); retries; delivery log | BE | 5 | Must | CLD-05, CLD-17 | Test: 30 events in 2 minutes from one camera produce one grouped alert |
| CLD-09 | WhatsApp channel: Cloud API client, template messages with image header and two quick-reply buttons ("Correct" / "False alarm"), English or Arabic per recipient, webhook for replies and delivery status with signature check, recipient opt-in record | BE | 3 | Must | SET-08, CLD-08 | Alert with snapshot reaches a phone; tapping "False alarm" updates the event within 5 s |
| CLD-10 | Telegram channel: bot, linking a recipient with a one-time code, photo plus inline buttons, callback handling | BE | 1 | Must | SET-07, CLD-08 | Same as CLD-09 on Telegram |
| CLD-11 | Feedback loop: store every true/false answer; per-rule and per-camera precision; events marked false or later found missed go into a review queue for the video library and labelling | BE | 1.5 | Must | CLD-09 | Precision per rule visible through the API |
| CLD-12 | VLM second opinion: for rules with `verify: true`, send the zone crop of the snapshot with a rule-specific yes/no question to Claude Haiku (Anthropic API), expect JSON `{answer, confidence, reason}`, suppress or downgrade on "no", time out after 8 s and send marked "unverified"; monthly cost cap per organisation; provider interface so a self-hosted Qwen3-VL can replace it; prompts versioned in the repo with a test set of stored snapshots | BE, CV | 4 | Must | CLD-08, SET-06 | On the spill and empty-shelf test snapshots the check removes at least half the false alerts without hiding true ones |
| CLD-13 | Daily WhatsApp summary per site at 21:00 Riyadh (alerts by type, top cameras, false-alert rate, busiest hour) | BE | 2 | Must | CLD-08 | Summary arrives daily on the office demo site |
| CLD-14 | Weekly PDF report per site by email (charts of alerts, footfall, queue times, feedback), Arabic and English | BE | 2 | Should | CLD-13 | Report renders correctly in both languages |
| CLD-15 | Fleet operations: Code-Ox admin endpoints for all devices, last heartbeat, versions, cameras offline; alert to the Code-Ox ops Telegram group when a device is silent 10 minutes or a camera 30 minutes | BE | 1.5 | Must | CLD-04 | Unplugging the office box alerts ops within 11 minutes |
| CLD-16 | Audit log of rule, zone and recipient changes and of every clip viewed (who, when, from where) | BE | 1 | Must | CLD-07 | Log entries visible to organisation owners |
| CLD-17 | Background job infrastructure: Redis queue, worker process (`arq` or `rq`), scheduler for timed jobs, dead-letter handling | BE | 1 | Must | REP-05 | A failing job retries 3 times then lands in dead-letter with its error |
| CLD-18 | Plan limits: Starter 4 cameras, Standard 8, Business 16, Enterprise 32; clip retention and features per plan; enforced on camera creation | BE | 1 | Should | CLD-07 | Adding a 5th camera on Starter is refused with an upgrade message |
| CLD-19 | API hardening: rate limits, input validation, CORS, consistent error format, request IDs, security headers | BE | 1 | Must | CLD-07 | OWASP ZAP baseline scan shows no high findings |
| CLD-20 | Staging deployment: Docker Compose on the staging server behind Caddy (TLS), nightly PostgreSQL backup to object storage with a tested restore, migrations on deploy, health checks, deploy from CI on tag | DO | 2 | Must | SET-09, REP-06 | A tag deploys to staging with no manual step; restore drill passes |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
