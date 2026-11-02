## Phase 1 — Repository and standards (weeks 1 to 2)

All Must, about 11 developer-days, mostly LD and DO. This phase decides how every later task is written, so it is done before feature work starts. The most important single file is the shared event and rule schema (REP-04): edge, cloud and dashboard all speak it.

**Repository layout (one monorepo)**

```
codeox-vision/
  CLAUDE.md                 root rules every Claude Code session reads
  edge/                     runs at the customer site (Python)
    ingest/                 camera streams, reconnects, frame sampling
    inference/              detector runtime (PyTorch dev, ONNX/TensorRT prod)
    tracking/               ByteTrack, zones, lines, dwell
    rules/                  rule types, evaluator, cooldowns
    clips/                  ring buffer, snapshot and clip cutting
    uploader/               event + clip upload, offline queue
    agent/                  heartbeat, config/model pull, logs, self-update
  cloud/                    API, workers, alert dispatcher (Python, FastAPI)
  web/                      dashboard (React, Vite, TypeScript)
  ml/                       datasets, training, export, model registry
  shared/                   Event, Rule, Camera, Site schemas (pydantic -> JSON Schema -> TypeScript)
  test-videos/              manifest.yaml + expected results (clips live in object storage)
  deploy/                   docker-compose files, edge image build, Ansible
  docs/                     ADRs, approved libraries, runbooks
  .claude/commands/         /test-videos, /new-rule, /new-detection, /licence-check
  .claude/agents/           video-evaluator subagent
```

| ID | Task | Owner | Days | Needs | Done when |
| --- | --- | --- | --- | --- | --- |
| REP-01 | Create the folder layout above with a placeholder README in each folder | LD | 0.25 | SET-03 | Layout merged |
| REP-02 | Python tooling: `uv` for environments, `ruff` for lint and format, `mypy` for types, `pytest`, `pre-commit` hooks. Web tooling: `pnpm`, ESLint, Prettier, Vitest | LD | 1 | REP-01 | `pre-commit run --all-files` and `pnpm lint` pass on a clean clone |
| REP-03 | Root `CLAUDE.md`: product summary, architecture diagram in text, folder map, approved and banned libraries, naming rules, how to run each service and test, the privacy rules (no face recognition, no identity tracking, video never leaves the site), "plan before code" rule. Short `CLAUDE.md` in `edge/`, `cloud/`, `web/`, `ml/` | LD | 1 | REP-01 | A fresh Claude Code session, asked "how do I add a rule type", answers correctly from the file |
| REP-04 | Shared schemas in `shared/`: `Detection`, `Track`, `Zone` (polygon in normalised 0–1 coordinates), `Line`, `Rule` (type, camera, zone, condition, schedule, cooldown, severity), `Event` (id, site, camera, rule, time, snapshot key, clip key, attributes), `CameraConfig`, `SiteConfig`. Generate JSON Schema and TypeScript types from them | LD, BE | 2 | REP-01 | Edge, cloud and web import the same generated types; a schema change breaks the build if a consumer is not updated |
| REP-05 | `deploy/docker-compose.dev.yml`: PostgreSQL 16, Redis 7, MinIO, MediaMTX (plays test clips as fake RTSP cameras), cloud API, edge service, web | DO | 1.5 | REP-01 | `docker compose up` brings the whole system up on a laptop with 4 fake cameras |
| REP-06 | CI in GitHub Actions: on each pull request run lint, type check, unit tests, schema generation check, licence check, Docker builds; nightly run of the full video regression suite with the scorecard posted to the Telegram dev group | DO | 1.5 | REP-02, REP-07 | Red CI blocks merge; nightly scorecard arrives |
| REP-07 | Licence guard: `pip-licenses` and `license-checker` against an allowlist (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0); hard block on AGPL/GPL and on the names `ultralytics`, `boxmot`, `deep_sort`, `yolo-world`, `yolo-nas`, `deimv2` | DO | 0.5 | REP-02 | A test pull request that adds `ultralytics` fails CI |
| REP-08 | `docs/approved-libraries.md`: every allowed library, its licence and why we use it (seed list: rfdetr, supervision, opencv-python, torch, onnxruntime, numpy, pydantic, httpx, fastapi, uvicorn, sqlalchemy, alembic, psycopg, redis, boto3, anthropic, structlog; web: react, vite, tailwind, react-konva, react-i18next, tanstack-query) | LD | 0.25 |  | List merged and linked from CLAUDE.md |
| REP-09 | Configuration convention: `pydantic-settings` per service, `.env.example` per package, no secrets in Git, settings validated at start-up with a clear error | LD | 0.5 | REP-02 | A missing setting stops the service with a readable message |
| REP-10 | Logging convention: JSON logs via `structlog`, correlation ID per event and request, all times stored in UTC and shown in Asia/Riyadh | LD | 0.5 | REP-02 | Logs from edge and cloud for the same event share one ID |
| REP-11 | Claude Code commands and subagent: `/test-videos`, `/new-rule`, `/new-detection`, `/licence-check`, and a `video-evaluator` subagent that runs the harness and explains regressions | LD | 0.5 | REP-03, VID-05 | Each command works from a clean clone |
| REP-12 | Architecture decision records in `docs/adr/`: 001 edge-first processing, 002 RF-DETR instead of YOLO, 003 no face recognition, 004 PostgreSQL + object storage, 005 WhatsApp as primary alert channel, 006 per-site pricing drives plan limits | LD | 0.5 |  | Six ADRs merged |
| REP-13 | Pull request and issue templates carrying the task ID and the definition-of-done checklist; `CODEOWNERS` per folder | DO | 0.25 | REP-01 | New pull requests open with the checklist |
| REP-14 | Versioning: semantic version tags per component (`edge-v`, `cloud-v`, `web-v`, `model-`), automatic changelog from pull request titles | DO | 0.25 | REP-06 | First tags `v0.1.0` cut |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
