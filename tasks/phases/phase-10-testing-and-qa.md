## Phase 10 — Testing and QA (continuous, soak test weeks 14 to 16)

About 19 developer-days of dedicated QA work, on top of the tests written inside every task. Testing starts in week 1, not at the end: the video library (Phase 2) is the heart of it, and every layer below runs automatically in CI so that Claude Code's output is checked on every pull request.

**Test layers**

| Layer | What it proves | Tool | When it runs |
| --- | --- | --- | --- |
| Unit | Each function and rule behaves on edge cases | pytest, Vitest | Every pull request |
| Video regression | Detection, tracking and rules catch what they should and stay quiet otherwise | Harness VID-05 | Subset on every edge pull request, full set nightly |
| Integration | Camera → box → cloud → alert → feedback works as one system | Docker Compose with fake cameras | Every pull request to `main` |
| Contract | Older edge versions still work with the newer cloud | Schema tests | Every pull request touching `shared/` |
| End-to-end web | Real user flows in the browser, English and Arabic | Playwright | Nightly and before release |
| Load | Cloud copes with 200 boxes and alert bursts | k6 or Locust | Before pilots and before launch |
| Chaos | Box survives unplugged cameras, lost internet, power cuts, full disk | Scripted on the office box | Before each edge release |
| Soak | Everything runs 7 days unattended without leaks or alert storms | Office box, all MVP rules live | Weeks 14 to 16, then before each major release |
| Field acceptance | A real site works as sold | Installer script QA-14 | Every installation |

**Coverage targets:** rules engine and tracking 85% or more, rest of edge 75%, cloud 75%, every web flow in the screens table covered by an end-to-end test.

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| QA-01 | Test strategy document: the layers above, coverage targets, who owns which tests, how flaky tests are handled | QA, LD | 1 | Must | REP-06 | Document merged and linked from CLAUDE.md |
| QA-02 | Coverage gates in CI per package | LD | 0.5 | Must | REP-06 | Pull request lowering coverage below target fails |
| QA-03 | Integration test suite: full stack in Docker Compose, a clip plays on a fake camera, the event reaches the cloud, the alert reaches a mocked WhatsApp, feedback flows back | QA, BE | 3 | Must | EDG-12, CLD-09 | Runs in CI in under 10 minutes |
| QA-04 | Contract tests: cloud accepts events and serves config to the two previous edge versions | BE | 1 | Must | REP-04 | Breaking change in `shared/` caught in CI |
| QA-05 | Playwright end-to-end tests: sign in, add camera, draw zone, create rule from template, see event, give feedback, switch to Arabic | QA | 3 | Must | WEB-09 | Nightly run green |
| QA-06 | Channel mocks: fake WhatsApp and Telegram servers for CI and local development, so tests never send real messages | BE | 1 | Must | CLD-09 | No real message sent from CI in a month of logs |
| QA-07 | Cloud load test: 200 boxes × 16 cameras sending heartbeats, per-minute counts and a burst of 5,000 events in 5 minutes | DO, QA | 2 | Must | CLD-20 | API p95 under 500 ms; no lost events |
| QA-08 | Edge stress test per tier: maximum cameras with 30% headroom, 72-hour memory leak check | CV, QA | 1 | Must | HW-02 | Memory flat within 5% over 72 h |
| QA-09 | Edge chaos tests: camera unplugged, NVR reboot, internet down 2 h, power cut, disk full, clock jump | QA | 2 | Must | HW-07, HW-10 | Every case recovers by itself with no lost events |
| QA-10 | 7-day soak on the office box with all MVP rules live; daily scorecard; restart count; memory; false alerts per camera per day | QA | 1 (+ daily checks) | Must | HW-05 | Soak report meets the MVP pass marks |
| QA-11 | Arabic quality check by a native speaker: every screen, WhatsApp template, daily summary, PDF report; right-to-left layout screenshots | PO | 1 | Must | WEB-03 | Sign-off with no open language issues |
| QA-12 | Release checklist per component (edge, cloud, web, model): tests green, changelog, migration tested, rollback plan, staging verified | QA | 0.5 | Must | REP-14 | Used for every release from week 12 |
| QA-13 | Bug triage rules: severity levels and fix times during pilots (critical 24 h, major 3 days, minor next sprint) | QA, PO | 0.5 | Must |  | Agreed and posted on the board |
| QA-14 | Field acceptance script per site, run by the installer: each camera online, zones drawn, one walk-through test per rule, each recipient receives the test alert, customer signs the acceptance sheet | QA, FLD | 1 | Must | WEB-07, SEC-06 | Script used at the friendly site and every pilot |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
