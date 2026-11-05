# Deploy

Docker files for running Code-Ox Vision:

| File | What it builds |
| --- | --- |
| `edge/Dockerfile` | Edge pipeline image (x86-64, HW-04 first version). `EDGE_EXTRAS=rfdetr` adds RF-DETR + PyTorch for development; empty gives the production-shaped ONNX image. Jetson gets its own image in HW-04 proper |
| `cloud.Dockerfile` | Cloud API image (CLD-20 hardens it) |
| `docker-compose.dev.yml` | The whole system on one laptop (REP-05), below |
| `postgres-init/` | Creates the `vision_app` role the API connects as (no superuser, no BYPASSRLS) |
| `dev/` | Dev site config and MediaMTX config for the fake cameras |

## Development stack (REP-05)

| Service | What it is | On the host |
| --- | --- | --- |
| `postgres` | PostgreSQL 16; `vision_owner` owns the schema, the API connects as `vision_app` | `127.0.0.1:5432` |
| `redis` | Redis 7.2, job queue (CLD-17) | `127.0.0.1:6379` |
| `s3` | SeaweedFS, S3-compatible object storage (stands in for MinIO, see below) | `http://127.0.0.1:9000` |
| `s3-setup` | One-shot: creates buckets `vision-media` and `cv-test-videos` | |
| `migrate` | One-shot: `vision-cloud migrate` as the schema owner | |
| `api` | Cloud API | `http://localhost:8000/docs` |
| `worker` | Background jobs (`vision-cloud worker`); `docker compose exec worker vision-cloud jobs failed` lists the dead-letter jobs | |
| `web` | Dashboard dev server (Vite) | `http://localhost:5173` |
| `mediamtx` | Fake cameras: four clips looped as RTSP, H.264 1280×720 10 fps like an NVR sub-stream | `rtsp://127.0.0.1:8554/cam1` … `cam4` |
| `edge-agent`, `edge-box` | Profile `edge`: an edge box enrolled with this cloud, running the site config it pulls | |
| `edge-cam1` … `edge-cam4` | Profile `edge-standalone`: one pipeline per fake camera on `dev/site.yaml`, no cloud | |

### Run it

The easy way is `./scripts/dev.sh` (see `docs/runbooks/local-setup.md`): `setup` once, then `up`,
`edge`, `status`, `logs`, `down`, `reset`. By hand, from the repository root:

```bash
cp .env.example .env
uv run vision-cloud gen-keys        # paste the two lines into .env
uv run vision-eval synth --out test-videos/synthetic --video
docker compose -f deploy/docker-compose.dev.yml --env-file .env up --build -d
```

Profiles add the edge: `--profile edge` (one box enrolled with this cloud; `scripts/dev.sh edge`
does the enrolment) and `--profile edge-standalone` (one pipeline per fake camera on
`dev/site.yaml`, without the cloud). Personal overrides go in `deploy/docker-compose.dev.local.yml`
(git-ignored), which `scripts/dev.sh` includes.

### Fake cameras and what they detect

By default the cameras loop the synthetic scenarios (`syn-queue-001`, `syn-unattended-001`,
`syn-entrance-001`, `syn-crowd-001`). Those videos are drawn shapes, so the stack proves the plumbing
(RTSP in, reconnects, decode, inference, rules, snapshots, clips, outbox) but RF-DETR does not see
people in them; expect "desk unattended" on cam2 and little else. Rule accuracy on synthetic data is
measured by `vision-eval run`, which replays their cached detections.

To use real footage, put the clips in a folder outside Git, set `CLIPS_DIR` and `CAM1_CLIP` …
`CAM4_CLIP` in `.env`, and change the zones and rules in `dev/site.yaml` to fit the scenes.
`VISION_DETECTOR` picks the model (`rfdetr-nano` … `rfdetr-large`).

On a 4-core laptop the four CPU-only RF-DETR processes run well under 5 fps each; performance
targets are EDG-16.

### Why SeaweedFS and not MinIO

MinIO no longer publishes images (`minio/minio` and `minio/mc` are gone from Docker Hub) and the
server is AGPL-3.0. SeaweedFS is Apache-2.0 and speaks the same S3 API with path-style addressing,
which `vision_cloud.storage` already uses, so no code changes. Staging and production use the hosting
provider's S3-compatible storage.
