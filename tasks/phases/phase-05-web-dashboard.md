## Phase 5 — Web dashboard (weeks 5 to 14)

About 38 developer-days (FE, with BE support). Most managers will live in WhatsApp; the dashboard is where owners set things up, review clips, see trends and where Code-Ox runs the fleet. Arabic and English from the first screen, right-to-left done properly, and it must work on a phone because managers tap through from WhatsApp. Stack: React, Vite, TypeScript, Tailwind, TanStack Query, React Router, `react-konva` for drawing, `react-i18next`, an API client generated from the backend's OpenAPI.

**Screens**

| Screen | Used by | Purpose |
| --- | --- | --- |
| Sign-in, invite, reset, 2FA | Everyone | Access |
| Site overview | Owner, manager | Today's alerts by type, false-alert rate, footfall by hour, queue trend, camera status |
| Event feed | Manager | Live list of alerts with thumbnails and filters |
| Event detail | Manager | Clip, snapshot, rule, AI check verdict and reason, true/false buttons, notes |
| Cameras | Owner, Code-Ox installer | Cameras per site, health, snapshot, add/edit |
| Zone editor | Owner, installer | Draw zones and lines on the camera snapshot |
| Rule builder | Owner, manager | Create rules from templates, with a plain-language preview |
| Recipients | Owner | Who is alerted, on which channel, quiet hours |
| All sites | Owner of a chain | Every branch in one table |
| Users and roles, audit log | Owner | Access control and accountability |
| Code-Ox admin console | Code-Ox ops | Organisations, devices, enrolment tokens, model rollout, support view |

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| WEB-01 | Scaffold the web app: Vite, TypeScript, Tailwind, React Router, TanStack Query, generated API client, auth token handling with refresh | FE | 1.5 | Must | CLD-07 | App builds in CI and calls staging |
| WEB-02 | Design basics: colour and type scale, Arabic-capable font (e.g. IBM Plex Sans Arabic), buttons, forms, tables, modals, empty and error states, light theme | FE | 2 | Must | WEB-01 | Component page reviewed by PO |
| WEB-03 | Arabic and English: `react-i18next`, every string in `en.json` and `ar.json`, right-to-left layout switch, Arabic or Western digits option, dates in Asia/Riyadh; CI check that fails on missing translation keys | FE | 1.5 | Must | WEB-01 | Every screen reviewed in Arabic by a native speaker |
| WEB-04 | Sign-in, invitation acceptance, password reset and 2FA screens | FE | 1.5 | Must | CLD-03 | Full flow works on staging |
| WEB-05 | Event feed: refreshes every 10 s (server-sent events later), filters by site, camera, rule, severity, date, status and verified; severity colours; thumbnails; infinite scroll | FE | 3 | Must | CLD-07 | 1,000 events scroll smoothly on a mid-range phone |
| WEB-06 | Event detail: clip player, snapshot with boxes and zone, rule summary, AI check verdict and reason, "Correct" / "False alarm" buttons, note field, link to the camera | FE | 2 | Must | WEB-05 | Feedback given here shows in the API precision figures |
| WEB-07 | Sites and cameras: list, add camera by URL or from edge discovery (EDG-04), status and last frame time, snapshot refresh | FE | 2 | Must | CLD-07 | A camera is added and goes online without touching the database |
| WEB-08 | Zone and line editor: draw, move, reshape and delete polygons and lines on the latest snapshot; names and colours; saves normalised coordinates; shows live count per zone when the box reports it | FE | 4 | Must | WEB-07 | Installer draws three zones on a real camera in under 3 minutes |
| WEB-09 | Rule builder: choose a rule type or an industry template, then a form per type (threshold, duration, schedule by day and hour, cooldown, severity, AI check on/off, recipients); plain-language preview such as "Alert Store Manager on WhatsApp when more than 5 people wait in Checkout Queue for 2 minutes, daily 09:00–23:00" | FE | 4 | Must | WEB-08 | A non-technical person creates a working queue rule unaided |
| WEB-10 | Recipients: add people with WhatsApp number (opt-in captured), Telegram link code, email; assign to rules; quiet hours; language per recipient | FE | 2 | Must | CLD-09 | New recipient receives a test alert from the screen |
| WEB-11 | Site overview: alerts today by type, false-alert rate this week, footfall by hour chart, queue length trend, cameras online | FE | 3 | Must | CLD-07, EDG-10 | Overview for the office demo matches the scorecard numbers |
| WEB-12 | All-sites view for chains: one row per site with status, alerts today, false-alert rate, worst camera | FE | 1.5 | Should | WEB-11 | Works with 20 demo sites |
| WEB-13 | Users and roles: invite, change role, limit to sites, remove | FE | 1.5 | Must | CLD-02 | Removed user loses access immediately |
| WEB-14 | Audit log viewer with filters | FE | 0.5 | Should | CLD-16 | Owner sees who changed a rule and when |
| WEB-15 | Code-Ox admin console: organisations, devices and their health, enrolment token generator, model rollout per device group, read-only support view of a customer (audited) | FE | 3 | Must | CLD-15 | Ops enrols and monitors a box without database access |
| WEB-16 | Phone layout for every manager screen (feed, detail, overview) | FE | 1.5 | Must | WEB-06 | Usable one-handed on a 6-inch phone |
| WEB-17 | Deep link from WhatsApp: a signed link that opens one event for 24 h without full sign-in, scoped to that event only, logged in the audit log | BE, FE | 1 | Must | CLD-09 | Link opens on the phone; editing the link to another event fails |
| WEB-18 | Performance and accessibility pass: bundle size budget, lazy-loaded clips, keyboard navigation, contrast | FE | 1 | Should | WEB-11 | Lighthouse score 90+ on the overview page |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
