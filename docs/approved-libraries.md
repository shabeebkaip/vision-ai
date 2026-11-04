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
| psycopg[binary] (psycopg, psycopg-binary) | LGPL-3.0 (used as an unmodified, dynamically imported library) | PostgreSQL driver for SQLAlchemy (CLD-01) |
| argon2-cffi (+ argon2-cffi-bindings, cffi MIT-0, pycparser BSD-3) | MIT | Password hashing, argon2id (CLD-03, ADR 008) |
| pyjwt | MIT | Short-lived HS256 access tokens (CLD-03, ADR 008) |
| rq (+ croniter MIT, click BSD-3) | BSD-2 | Background jobs: Redis queue, worker, retries, delayed jobs, failed-job registry (CLD-17) |
| cryptography | Apache-2.0 OR BSD-3-Clause | Fernet encryption of camera stream URLs at rest (CLD-01) |
| Transitive cloud dependencies: starlette, click, markupsafe (BSD-3); mako, h11, jmespath, urllib3, annotated-doc (MIT); botocore, s3transfer, opentelemetry-api (Apache-2.0, via boto3 / FastAPI); python-dateutil (Apache-2.0 / BSD) | as listed | Pulled in by FastAPI, Alembic and boto3; checked by `scripts/licence_check.py` |
| anthropic | MIT | AI second opinion (CLD-12) |
| supervision | MIT | Allowed for drawing and examples; not used for tracking (ADR 007) |
| trackers | Apache-2.0 | Allowed only if it stops requiring non-headless OpenCV |
| pytest, pytest-cov, ruff, mypy, pre-commit | MIT / Apache-2.0 | Development |

## Web (Phase 5)

`web/scripts/check-licences.mjs` (`npm run licences`, run in the Web workflow) fails on copyleft or
non-commercial npm licences.

| Library | Licence | Why |
| --- | --- | --- |
| react, react-dom | MIT | UI |
| vite, @vitejs/plugin-react | MIT | Dev server and build |
| typescript | Apache-2.0 | Types |
| tailwindcss, @tailwindcss/vite | MIT | Styling (logical properties for right-to-left). Pulls in lightningcss (MPL-2.0) as a build-time tool only; nothing of it ships |
| @tanstack/react-query | MIT | Server state, polling, caching |
| react-router | MIT | Routing |
| konva, react-konva | MIT | Zone and line editor canvas |
| i18next, react-i18next | MIT | Arabic and English |
| recharts | MIT | Footfall chart |
| lucide-react | ISC | Icons |
| json-schema-to-typescript | MIT | Generates `web/src/api/types.ts` from the shared pydantic schemas |
| vitest, jsdom, @testing-library/react, @testing-library/dom, @testing-library/jest-dom | MIT | Tests |
| eslint, @eslint/js, typescript-eslint, eslint-plugin-react-hooks, globals | MIT | Lint |
| prettier | MIT | Formatting |
| playwright | Apache-2.0 | Screenshots and browser checks (dev tool, not a dependency of the app) |
| @types/react, @types/react-dom, @types/node | MIT | Type definitions |

Font: IBM Plex Sans Arabic (SIL Open Font License 1.1), self-hosted in `web/public/fonts/` with its
licence file. A font, not a code library; OFL allows bundling and redistribution.

## Tools and services (not shipped in the product)

go2rtc (MIT), MediaMTX (MIT), FFmpeg (LGPL build), Frigate (MIT, reference only), CVAT (MIT),
Label Studio (Apache-2.0), MLflow (Apache-2.0), Grafana (AGPL: internal monitoring only, never
bundled or modified), Tailscale.

Local development stack (`deploy/docker-compose.dev.yml`, never shipped to customers):
PostgreSQL 16 (PostgreSQL licence), Redis 7.2 (BSD-3; Redis 7.4 and later are under RSALv2/SSPL or
AGPL, so the compose file pins 7.2), SeaweedFS (Apache-2.0: local S3 stand-in; staging and
production use the hosting provider's S3-compatible storage), MediaMTX (MIT: fake RTSP cameras),
Node 22 (MIT: dashboard dev server). MinIO was the first choice but no longer publishes images.

## Banned

`ultralytics` (AGPL-3.0), `boxmot` (AGPL-3.0), original `deep_sort` / `deep-sort-realtime` (GPL-3.0),
`yolo-world` (GPL-3.0), `super-gradients` / YOLO-NAS weights (non-commercial), `rfdetr-plus`
(PML-1.0), DEIMv2 (custom licence), any face recognition or re-identification model.
