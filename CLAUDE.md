# Code-Ox Vision — instructions for Claude Code

Code-Ox Vision turns the CCTV cameras a customer already owns into real-time operational alerts
(queue building, desk unattended, after-hours presence, helmet missing, forklift too close, exit
blocked). AI runs on an **edge box at the customer site**; only events, snapshots and short clips go
to a Saudi-hosted cloud. Managers get alerts on WhatsApp with a clip and tap "Correct" / "False alarm".

The full plans live in `docs/` (also `docs/models.md` for model licences, `docs/adr/` for decisions):
- `docs/product-plan.md` — market, architecture, models, hardware, budget, compliance, pricing
- `docs/development-task-plan.md` — every task with an ID (e.g. `EDG-09`), owner, estimate, "done when"
- `tasks/tasks.csv` — the same tasks as rows

Always work against a task ID from the plan. If a request has no task, say which task it belongs to
or propose a new one.

## Architecture in one paragraph

camera (RTSP via NVR) → `edge/ingest` frame source (5–10 fps, reconnects) → `edge/detection`
detector (RF-DETR; ONNX/TensorRT in production) → `edge/tracking` ByteTrack-style tracker (our own, ADR 007) →
`edge/scene` zones and lines (normalised 0–1 coordinates) → `edge/rules` rules engine (six MVP rule
types, schedules, cooldowns, hysteresis) → `edge/events` event + snapshot + clip → `edge/sinks`
(SQLite outbox shipped to the cloud by `edge/uploader`, EDG-12; Telegram/console in dev). The cloud (`cloud/`, FastAPI + PostgreSQL) stores events,
dispatches WhatsApp/Telegram alerts, runs the AI second-opinion check and serves the dashboard
(`web/`, React). `shared/` holds the pydantic schemas every part speaks. `ml/` holds the evaluation
harness and training tools.

## Repository layout

```
shared/   vision_shared   schemas: Zone, Line, Schedule, Rule, CameraConfig, SiteConfig, Detection, Event, clip manifest
edge/     vision_edge     the on-site pipeline and the `vision-edge` CLI
ml/       vision_ml       evaluation harness (`vision-eval`), synthetic clips, later training/export
cloud/                    FastAPI backend (Phase 4, not started)
web/                      React dashboard (Phase 5, not started)
test-videos/              manifest.yaml + expected results; clips live in object storage, never in Git
deploy/                   Docker / compose files
docs/                     plans, ADRs, approved libraries, model notes
```

## Commands

```bash
uv sync --all-packages                 # install everything (add --extra rfdetr in edge for the real model)
uv run pytest                          # all tests
uv run ruff check . && uv run ruff format --check .
uv run mypy shared/src edge/src ml/src
uv run python scripts/licence_check.py # fails on banned or non-permissive licences
uv run vision-edge --help              # edge CLI: run, upload, detect-file, survey, check-camera
uv run vision-eval run --strict        # harness: score the pipeline against test-videos/manifest.yaml
```

## Rules that are never broken

1. **Licences.** Only libraries in `docs/approved-libraries.md`. Never add `ultralytics`, `boxmot`,
   original `deep_sort`, `yolo-world`, `yolo-nas`, `deimv2`, or any AGPL/GPL package. Ultralytics YOLO
   is the obvious default for "object detection" and it is banned: use RF-DETR (`rfdetr`, Nano–Large
   only; Atto/Femto/Pico/XL/2XL weights are under a different licence) or D-FINE. Ask before adding
   any new dependency and add it to `docs/approved-libraries.md` in the same pull request.
2. **Privacy.** No face recognition, face embeddings, re-identification or identity tracking, ever.
   Tracker IDs are anonymous and live only in memory. Raw video never leaves the edge box; only
   events, snapshots and event clips are uploaded, and a site flag can disable clips entirely. We never
   alter, delete or export the customer's NVR recordings.
3. **The schemas in `shared/` are the contract.** Change them first, then every consumer, in the same
   pull request. Coordinates in configs are normalised 0–1; convert to pixels only inside the edge.
4. **Time.** Store and compute in UTC (timezone-aware `datetime`); schedules are evaluated in the
   site's timezone (default `Asia/Riyadh`). Never use naive datetimes.
5. **Config and secrets.** Settings come from YAML config files or environment variables
   (`VISION_` prefix, see `vision_edge.settings`). Never hard-code tokens, IPs, passwords or customer
   names. `.env` is never committed.
6. **Edge code must stay Python 3.10-compatible** (Jetson JetPack 6), even though development uses 3.11+. Do not use 3.11+ only features
   (`typing.Self`, `except*`, `tomllib`, `StrEnum`). Use `from __future__ import annotations`.

## How we work

- Plan first: for anything over ~1 day, write a short plan in the issue before coding.
- One task, one branch, one pull request: branch `<TASK-ID>-short-name`, PR title `[TASK-ID] ...`,
  under ~400 changed lines where possible.
- Every change ships with tests. Rules, zones and tracking changes also need a case in the video
  regression suite (`test-videos/manifest.yaml`, run with `/test-videos`).
- Keep the edge free of heavy optional imports at module import time: `rfdetr`/`torch` are imported
  lazily inside the detector that needs them, so the pipeline and tests run without them.
- Logs are structured (`structlog`), one event per line, with `site_id`, `camera_id`, `rule_id` keys.
- Update `docs/` when behaviour, setup or an API changes. Record architecture decisions in `docs/adr/`.

## Adding a new rule type

1. Add the value to `RuleType` and any new fields to `Rule` in `shared/src/vision_shared/schemas.py`
   (with validation).
2. Implement a class in `edge/src/vision_edge/rules/` that subclasses `RuleEvaluator` and register it
   in `rules/__init__.py` (`EVALUATORS`).
3. Unit tests in `edge/tests/test_rules_*.py` covering: fires after the minimum duration, does not fire
   before it, clears, respects cooldown and schedule.
4. At least three positive and three negative clips in `test-videos/manifest.yaml`.
