# Code-Ox Vision dashboard (`web/`)

React dashboard for managers and owners: site overview, the live event feed, event detail with
"Correct" / "False alarm" review, sites and cameras, the zone and line editor, and the rule builder.
Arabic and English with right-to-left layout, and a phone layout for managers who tap through from
WhatsApp. Tasks WEB-01 to WEB-09, WEB-11 and WEB-16 in `docs/development-task-plan.md`.

Stack: Vite, React, TypeScript, Tailwind CSS, TanStack Query, React Router, react-konva, react-i18next,
Recharts, lucide-react. All MIT, Apache-2.0 or ISC (see `docs/approved-libraries.md`).

## Run it

Node 22.22 or newer.

```bash
cd web
npm ci
npm run dev          # http://localhost:5173 with demo data
```

Sign in with any email address and the password `demo1234` (mock mode only).

| Command               | What it does                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------------- |
| `npm run dev`         | Dev server                                                                                         |
| `npm run build`       | Type-check, then production build into `dist/`                                                     |
| `npm run preview`     | Serve the build on http://localhost:4173                                                           |
| `npm test`            | Vitest unit and component tests                                                                    |
| `npm run lint`        | ESLint and Prettier check                                                                          |
| `npm run typecheck`   | TypeScript only                                                                                    |
| `npm run i18n:check`  | Fails if `en.json` and `ar.json` differ in keys or `{{placeholders}}`, or code uses an unknown key |
| `npm run licences`    | Fails on copyleft or non-commercial npm licences                                                   |
| `npm run gen:types`   | Regenerates `src/api/types.ts` from `src/api/schema.json`                                          |
| `npm run screenshots` | Retakes `docs/screenshots/*.png` from a running preview (needs Playwright with Chromium)           |

CI: `.github/workflows/web.yml` runs install, licence guard, lint, typecheck, i18n check, tests and
build, plus a contract job that fails if the generated schema or types are out of date.

## How the data layer works

```
vision_shared (pydantic) --scripts/export_json_schema.py--> src/api/schema.json
                         --json-schema-to-typescript-----> src/api/types.ts   (Zone, Line, Rule, Event, ...)
src/api/models.ts   view types the API adds around them (camera status, signed media URLs, feedback)
src/api/client.ts   ApiClient interface: the only way screens reach data
src/api/http.ts     HttpApiClient: fetch against VITE_API_BASE_URL with a bearer token
src/api/mock/       MockApiClient: in-memory demo data
```

When a shared schema changes: `uv run python scripts/export_json_schema.py` from the repo root, then
`npm run gen:types` here, and commit both files. Every field is required in the generated types
because the cloud always serialises defaults.

Coordinates: zones and lines are stored normalised 0..1 (x right, y down), exactly as in
`vision_shared.schemas`. The editor converts to stage pixels only for drawing
(`src/lib/geometry.ts`, unit tested). For a counting line, "in" means crossing from the left to the
right of start -> end; the editor draws an arrow on the "in" side.

Times: the API speaks ISO 8601 UTC. Screens show the site's timezone (default `Asia/Riyadh`), using
the Gregorian calendar in Arabic and a 24-hour clock. Users can pick Western or Arabic-Indic digits.

## The mock

With `VITE_API_BASE_URL` empty, `createApiClient()` returns `MockApiClient`:

- Three fictional Riyadh sites: a restaurant (4 cameras), a pharmacy (3, industry retail) and a
  distribution centre (4), with English and Arabic names, zones, lines, recipients and 16 rules across the six rule types.
- About 60 events over the last 7 days, generated from a fixed seed relative to "now", inside each
  rule's schedule, with edge-style messages, detection boxes, AI check results and reviews.
- Snapshots are drawn as SVG scenes (counter, entrance, dining hall, corridor, dock, racking aisle)
  with faceless silhouettes; clips are animated SVGs. No photos.
- Writes are validated like the pydantic models: points outside 0..1, duplicate ids, rules without
  a zone or line, and deleting a zone or line that a rule uses are all rejected.
- A new queue alert appears every 90 seconds so the feed's 10-second polling has something to show.
- State lives in memory and resets on reload.

## Pointing at the real API

```bash
# web/.env.local
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

The dev stack (`deploy/docker-compose.dev.yml`) sets this by default; sign in with the demo owner
from `vision-cloud seed-demo`. The cloud must allow the dashboard's origin
(`VISION_CLOUD_CORS_ORIGINS`, `["http://localhost:5173"]` by default).

`src/api/http.ts` talks to the cloud's own routes and translates its responses into the view models
in `src/api/models.ts`, so screens never see the difference between the cloud and the mock:

| Dashboard call             | Cloud route                                       | Translation                                                       |
| -------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- |
| `login`                    | `POST /auth/login`, then `GET /auth/me`           | token + user; keeps the refresh token                             |
| `logout`                   | `POST /auth/logout`                               | revokes the refresh token                                         |
| `listSites`, `getOverview` | `GET /sites`, `GET /sites/{id}/overview?date=`    | empty Arabic name becomes `null`; every rule type in the overview |
| `listCameras`, `getCamera` | `GET /cameras`, `GET /cameras/{id}`               | `source_redacted` as `source`; status `error` shown as degraded   |
| `saveGeometry`             | `PATCH /cameras/{id}` with `{zones, lines}`       | a rule still using a removed zone or line becomes a 409           |
| `listRules`, `createRule`  | `GET/POST /sites/{id}/rules`                      | rule without the cloud-assigned fields                            |
| `listRecipients`           | `GET /sites/{id}/recipients`                      |                                                                   |
| `listEvents`, `getEvent`   | `GET /events`, `GET /events/{id}`                 | the latest feedback; Telegram answers shown by their author       |
| `submitFeedback`           | `POST /events/{id}/feedback` `{is_true, comment}` | returns the updated event                                         |

Access tokens last 15 minutes. On a 401 the client refreshes once with the refresh token (one refresh
for all the requests that failed together), retries, and signs the user out only if that fails.
Errors carry the cloud's `code` and `details` (`ApiError`).

Not yet from the cloud: snapshot thumbnails in the event list (the detail page has them) and the
latest camera frame for the zone editor (EDG-03).

Optional `Event.attributes` the dashboard reads: `boxes` (normalised `[x1, y1, x2, y2]` list drawn
over the snapshot) and `ai_check` (`{verdict: confirmed|rejected|unsure, reason}`).
`CameraConfig.source` should come back with credentials masked.

## Arabic and right-to-left

All visible strings are in `src/i18n/en.json` and `src/i18n/ar.json`. Arabic uses i18next plural
forms (zero, one, two, few, many, other), so "دقيقتين" and "5 أشخاص" come out right. Switching
language sets `lang` and `dir` on `<html>`; layouts use logical Tailwind utilities (`ms-`, `pe-`,
`start-`, `text-start`) and direction-dependent icons flip with `rtl:-scale-x-100`. The camera canvas
and snapshots stay left-to-right because the picture is not mirrored. The font is IBM Plex Sans
Arabic, self-hosted from `public/fonts/` (SIL OFL 1.1), so browsers do not call Google.

## Screenshots

Taken with `npm run screenshots` against `vite preview` (mock data), desktop 1440 px and phone 390 px.

| Screen       | English                                                                                                             | Arabic                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Overview     | [desktop](../docs/screenshots/overview-en-desktop.png) · [phone](../docs/screenshots/overview-en-phone.png)         | [desktop](../docs/screenshots/overview-ar-desktop.png) · [phone](../docs/screenshots/overview-ar-phone.png)         |
| Event feed   | [desktop](../docs/screenshots/event-feed-en-desktop.png) · [phone](../docs/screenshots/event-feed-en-phone.png)     | [desktop](../docs/screenshots/event-feed-ar-desktop.png) · [phone](../docs/screenshots/event-feed-ar-phone.png)     |
| Event detail | [desktop](../docs/screenshots/event-detail-en-desktop.png) · [phone](../docs/screenshots/event-detail-en-phone.png) | [desktop](../docs/screenshots/event-detail-ar-desktop.png) · [phone](../docs/screenshots/event-detail-ar-phone.png) |
| Zone editor  | [desktop](../docs/screenshots/zone-editor-en-desktop.png) · [phone](../docs/screenshots/zone-editor-en-phone.png)   | [desktop](../docs/screenshots/zone-editor-ar-desktop.png) · [phone](../docs/screenshots/zone-editor-ar-phone.png)   |
| Rule builder | [desktop](../docs/screenshots/rule-builder-en-desktop.png) · [phone](../docs/screenshots/rule-builder-en-phone.png) | [desktop](../docs/screenshots/rule-builder-ar-desktop.png) · [phone](../docs/screenshots/rule-builder-ar-phone.png) |
| Sign-in      | [desktop](../docs/screenshots/sign-in-en-desktop.png) · [phone](../docs/screenshots/sign-in-en-phone.png)           | [desktop](../docs/screenshots/sign-in-ar-desktop.png) · [phone](../docs/screenshots/sign-in-ar-phone.png)           |

![Overview](../docs/screenshots/overview-en-desktop.png)
![Event detail in Arabic](../docs/screenshots/event-detail-ar-desktop.png)
![Zone editor](../docs/screenshots/zone-editor-en-desktop.png)

## Not done yet

Invitation, password reset and 2FA screens (WEB-04 covers sign-in only here), token refresh,
recipients (WEB-10), all-sites view (WEB-12), users and roles (WEB-13), audit log (WEB-14), admin
console (WEB-15), WhatsApp deep links (WEB-17), the performance and accessibility pass (WEB-18),
industry rule templates (DET-08), live per-zone counts in the editor, adding cameras from the
dashboard, and editing or disabling existing rules.
