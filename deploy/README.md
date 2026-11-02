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
| `redis` | Redis 7.2 | `127.0.0.1:6379` |
| `s3` | SeaweedFS, S3-compatible object storage (stands in for MinIO, see below) | `http://127.0.0.1:9000` |
| `s3-setup` | One-shot: creates buckets `vision-media` and `cv-test-videos` | |
| `migrate` | One-shot: `vision-cloud migrate` as the schema owner | |
| `api` | Cloud API | `http://localhost:8000/docs` |
| `web` | Dashboard dev server (Vite) | `http://localhost:5173` |
| `mediamtx` | Fake cameras: four clips looped as RTSP, H.264 1280×720 10 fps like an NVR sub-stream | `rtsp://127.0.0.1:8554/cam1` … `cam4` |
| `edge-cam1` … `edge-cam4` | Edge pipeline, one container per camera (the CLI runs one camera per process), config `dev/site.yaml` | |

### Run it

From the repository root:

```bash
cp .env.example .env
uv run vision-cloud gen-keys        # paste the two lines into .env
uv run vision-eval synth --out test-videos/synthetic --video
docker compose -f deploy/docker-compose.dev.yml --env-file .env up --build -d
docker compose -f deploy/docker-compose.dev.yml --env-file .env logs -f edge-cam1
```

The first build downloads PyTorch (several GB) for RF-DETR. Each edge container downloads the
RF-DETR Nano weights into the `edgedata` volume on first start (`RF_HOME`); on a machine without
internet, copy `rf-detr-nano.pth` into `/var/lib/vision/cache/rfdetr/` in that volume.

Demo login data for the API: `uv run vision-cloud seed-demo --owner-email you@example.com` with
`VISION_CLOUD_DATABASE_URL` pointing at `localhost:5432` as `vision_owner` (see `cloud/README.md`).

Check a fake camera from the host, or play it in VLC:

```bash
uv run vision-edge check-camera rtsp://127.0.0.1:8554/cam1
```

Events land in the outbox in the `edgedata` volume:

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file .env exec edge-cam1 ls -R /var/lib/vision/outbox
```

Stop with `down`; add `-v` to also delete the database, buckets, outboxes and model cache.

Not wired yet: the edge does not upload to the API until the uploader (EDG-12) lands, and the
dashboard uses its built-in demo data (`VITE_API_BASE_URL` empty) until its API contract and the
cloud routes are aligned.

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
