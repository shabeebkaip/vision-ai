# Approved libraries

Only these may be added as dependencies. Ask before adding anything new and add it here in the same
pull request, with its licence and why we need it. `scripts/licence_check.py` runs in CI and fails on
banned packages and copyleft or non-commercial licences.

## Python (edge, shared, ml, cloud)

| Library | Licence | Why |
| --- | --- | --- |
| pydantic, pydantic-settings | MIT | Schemas, config validation |
| pyyaml | MIT | Site configs and manifests |
| tzdata | Apache-2.0 | Time-zone database on boxes without one |
| numpy | BSD-3 | Arrays |
| scipy | BSD-3 | Hungarian matching in the tracker |
| opencv-python-headless | Apache-2.0 | Video decode, drawing, JPEG. Headless only: edge boxes have no display |
| onnxruntime / onnxruntime-gpu | MIT | Production inference |
| rfdetr (no `[plus]` extra) | Apache-2.0 | RF-DETR Nano–Large for development, fine-tuning, ONNX export |
| torch, torchvision | BSD-3 | Through `rfdetr`, development and training only, never on edge boxes |
| httpx | BSD-3 | HTTP (Telegram, cloud upload) |
| structlog | MIT / Apache-2.0 | Structured logs |
| fastapi, uvicorn, sqlalchemy, alembic, psycopg, redis, boto3 | MIT / BSD / Apache-2.0 / LGPL (psycopg) | Cloud backend (Phase 4) |
| anthropic | MIT | AI second opinion (CLD-12) |
| supervision | MIT | Allowed for drawing and examples; not used for tracking (ADR 007) |
| trackers | Apache-2.0 | Allowed only if it stops requiring non-headless OpenCV |
| pytest, pytest-cov, ruff, mypy, pre-commit | MIT / Apache-2.0 | Development |

## Web (Phase 5)

react, vite, typescript, tailwindcss, @tanstack/react-query, react-router, react-konva, react-i18next,
vitest, eslint, prettier, playwright (all MIT or Apache-2.0).

## Tools and services (not shipped in the product)

go2rtc (MIT), MediaMTX (MIT), FFmpeg (LGPL build), Frigate (MIT, reference only), CVAT (MIT),
Label Studio (Apache-2.0), MLflow (Apache-2.0), Grafana (AGPL: internal monitoring only, never
bundled or modified), Tailscale.

## Banned

`ultralytics` (AGPL-3.0), `boxmot` (AGPL-3.0), original `deep_sort` / `deep-sort-realtime` (GPL-3.0),
`yolo-world` (GPL-3.0), `super-gradients` / YOLO-NAS weights (non-commercial), `rfdetr-plus`
(PML-1.0), DEIMv2 (custom licence), any face recognition or re-identification model.
