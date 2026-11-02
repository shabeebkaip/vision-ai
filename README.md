# Code-Ox Vision AI

Real-time operational alerts from the CCTV cameras customers already own. AI runs on a small edge box at the site, a manager gets a WhatsApp message with a short clip the moment something goes wrong (queue building, desk unattended, after-hours entry, helmet missing, forklift too close, exit blocked), and video never leaves the building.

## Status

The plans are complete and the edge pipeline core is built: camera / video / replay sources, RF-DETR and ONNX detectors, an anonymous tracker, zones and lines, the six MVP rule types, snapshots and H.264 clips, outbox and Telegram alerts, and a scoring harness with synthetic scenarios. The cloud backend (Phase 4) and dashboard (Phase 5) are next.

## Quick start

```bash
uv sync --all-packages                     # Python 3.11+; add --extra rfdetr for the real model
uv run pytest                              # unit tests
uv run vision-eval run --strict            # score the pipeline on the test clips
uv run vision-eval synth --video           # render synthetic videos, then:
uv run vision-edge run examples/synthetic-restaurant/site.yaml --camera counter \
    --video test-videos/synthetic/syn-queue-001.mp4 --outbox var/outbox-demo
uv run vision-edge check-camera "rtsp://USER:PASS@NVR_IP:554/Streaming/Channels/102"
```

Real camera: copy `examples/office-hikvision/site.yaml`, fill in the stream URL, draw zones as 0–1 coordinates, then `uv run --extra rfdetr vision-edge run your-site.yaml --camera reception --detector rfdetr-nano` (weights download on first run). Telegram alerts: set `VISION_TELEGRAM_BOT_TOKEN` and `VISION_TELEGRAM_CHAT_ID` and add `--telegram`.

Whole system on a laptop (Postgres, Redis, S3 storage, four fake RTSP cameras, edge pipeline): see [deploy/README.md](deploy/README.md).

## Documents

| Document | What it covers |
| --- | --- |
| [Product plan](docs/product-plan.md) | Market and competitors, features per industry, system architecture, AI models and open-source stack, CCTV integration, hardware tiers, budget, roadmap, risks, compliance, go-to-market and pricing |
| [Development task plan](docs/development-task-plan.md) | Every task from an empty repository to commercial launch: team and Claude Code working model, 14 phases, owners, estimates, dependencies, "done when" tests, gates, decisions and risks |
| [All tasks as CSV](tasks/tasks.csv) | 221 tasks, one row each, ready for GitHub Projects, Jira or a spreadsheet |
| [Tasks by phase](tasks/README.md) | One file per phase |
| [AI models](docs/models.md) | Which models we use, their licences, weight URLs, and what is banned |
| [Approved libraries](docs/approved-libraries.md) · [Decisions](docs/adr/README.md) | Dependency rules and architecture decision records |
| [CLAUDE.md](CLAUDE.md) | Instructions every Claude Code session follows in this repo |

## Phases

Week 1 starts Sunday 8 November 2026. Gates: G0 office demo (~3 Dec 2026), G1 MVP complete (~25 Feb 2027), G2 pilots decide (~22 Apr 2027), G3 commercial launch (~29 Jul 2027).

| Phase | Name | Weeks | Tasks | Must |
| --- | --- | --- | --- | --- |
| 0 | [Accounts, access and machines](tasks/phases/phase-00-accounts-access-and-machines.md) | 1 | 16 | 16 |
| 1 | [Repository and standards](tasks/phases/phase-01-repository-and-standards.md) | 1–2 | 14 | 14 |
| 2 | [Video test library and evaluation harness](tasks/phases/phase-02-video-test-library-and-evaluation-harness.md) | 1–4, then ongoing | 12 | 12 |
| 3 | [Edge pipeline](tasks/phases/phase-03-edge-pipeline.md) | 2–10 | 19 | 16 |
| 4 | [Cloud backend](tasks/phases/phase-04-cloud-backend.md) | 3–12 | 20 | 18 |
| 5 | [Web dashboard](tasks/phases/phase-05-web-dashboard.md) | 5–14 | 18 | 15 |
| 6 | [Detection use cases](tasks/phases/phase-06-detection-use-cases.md) | MVP 3–14, V1 18–32 | 19 | 8 |
| 7 | [Model training pipeline](tasks/phases/phase-07-model-training-pipeline.md) | 8–20 | 14 | 10 |
| 8 | [Edge packaging and hardware](tasks/phases/phase-08-edge-packaging-and-hardware.md) | 10–16 | 13 | 11 |
| 9 | [Security, privacy and Saudi compliance](tasks/phases/phase-09-security-privacy-and-saudi-compliance.md) | 4–16, launch check 36 | 15 | 13 |
| 10 | [Testing and QA](tasks/phases/phase-10-testing-and-qa.md) | Continuous, soak 14–16 | 14 | 14 |
| 11 | [Office demo, friendly site and pilots](tasks/phases/phase-11-office-demo-friendly-site-and-pilots.md) | 4, 13–16, 17–24 | 14 | 13 |
| 12 | [Commercial launch](tasks/phases/phase-12-commercial-launch.md) | 25–38 | 16 | 14 |
| 13 | [V2 backlog](tasks/phases/phase-13-v2-backlog.md) | 39 onwards | 17 | 0 |

![Development timeline](docs/images/development-timeline.png)

## Ground rules

- **Edge-first:** inference runs on the box at the customer site; only events, snapshots and short clips go to the cloud.
- **Licences:** RF-DETR (Apache-2.0), Supervision (MIT) and other permissive libraries only. Never `ultralytics`, `boxmot`, original `deep_sort` or other AGPL/GPL code.
- **Privacy:** no face recognition, no identity tracking, customer recordings are never altered or exported.
- **Built with Claude Code:** one root `CLAUDE.md` (task REP-03), plan before code, one task per branch and pull request (`<TASK-ID>-short-name`), tests with every change, the video regression suite as the source of truth on accuracy.

## Turning tasks into GitHub issues

```bash
python3 scripts/create_github_issues.py                 # dry run, prints what it would create
python3 scripts/create_github_issues.py --apply         # creates labels + one issue per task
python3 scripts/create_github_issues.py --apply --phase 0 1 2   # only some phases
```

Issues get labels for phase, priority and owner role, the task's details, estimate, dependencies, "done when" test and the definition-of-done checklist. Re-running skips tasks that already have an issue.
