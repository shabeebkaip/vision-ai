# Deploy

Docker files for running Code-Ox Vision. Production edge images (Jetson, mini-PC) come with the
HW-* tasks and cloud deployment with LCH-*; this folder holds the development stack for now.

## Development stack (REP-05)

`docker-compose.dev.yml` brings the system up on one laptop with four fake cameras:

| Service | What it is | On the host |
| --- | --- | --- |
| `postgres` | PostgreSQL 16, the cloud database | `127.0.0.1:5432` |
| `redis` | Redis 7.2 (BSD-3), queues and cache | `127.0.0.1:6379` |
| `s3` | SeaweedFS, S3-compatible object storage (stands in for MinIO, see below) | `http://127.0.0.1:8333` |
| `s3-init` | One-shot: creates buckets `vision-media` and `cv-test-videos` | |
| `mediamtx` | Fake cameras: loops four clips as RTSP, H.264 1280×720 10 fps like an NVR sub-stream | `rtsp://127.0.0.1:8554/cam1` … `cam4` |
| `edge-cam1` … `edge-cam4` | The edge pipeline, one container per camera, config `dev/site.yaml` | |

The cloud API (CLD-01) and the web dashboard (WEB-01) are added to this file when they exist.

### Run it

From the repository root:

```bash
cp deploy/.env.example deploy/.env
uv run vision-eval synth --out test-videos/synthetic --video
docker compose -f deploy/docker-compose.dev.yml --env-file deploy/.env up --build -d
docker compose -f deploy/docker-compose.dev.yml --env-file deploy/.env logs -f edge-cam1
```

The first build downloads PyTorch (several GB) for RF-DETR; later builds reuse the layer. The first
start of each edge container downloads the RF-DETR Nano weights into the `edge-data` volume.

Check a fake camera from the host, or play it in VLC:

```bash
uv run vision-edge check-camera rtsp://127.0.0.1:8554/cam1
```

Events are written to the outbox in the `edge-data` volume (`/data/outbox/<camera>`):

```bash
docker compose -f deploy/docker-compose.dev.yml --env-file deploy/.env exec edge-cam1 ls -R /data/outbox
```

Stop with `down`; add `-v` to also delete the database, buckets and outboxes.

### Fake cameras and what they detect

By default the cameras loop the synthetic scenarios (`syn-queue-001`, `syn-unattended-001`,
`syn-entrance-001`, `syn-crowd-001`). Those videos are drawn shapes, so the stack proves the
plumbing (RTSP in, reconnects, decode, inference, rules, outbox) but RF-DETR will not see people in
them. Rule accuracy on synthetic data is measured by `vision-eval run`, which replays their cached
detections.

To use real footage, put the clips in a folder (never in Git), point `CLIPS_DIR` and `CAM1_CLIP` …
`CAM4_CLIP` in `deploy/.env` at them, and change the zones and rules in `dev/site.yaml` to fit the
scenes. `VISION_DETECTOR` picks the model (`rfdetr-nano` … `rfdetr-large`); with
`EDGE_EXTRAS=` (empty) the image is built without PyTorch and only the `onnx` detector works.

### Why SeaweedFS and not MinIO

The plan named MinIO, but MinIO no longer publishes images on Docker Hub (`minio/minio` and
`minio/mc` are gone), and the server is AGPL-3.0. SeaweedFS is Apache-2.0 and speaks the same S3 API,
so the cloud code (boto3) does not change. Production uses an in-Kingdom S3-compatible service.

### Licences

All services are tools, not shipped in the product: PostgreSQL (PostgreSQL licence), Redis 7.2
(BSD-3; 7.4 and later are RSALv2/SSPL, so do not bump the tag), SeaweedFS (Apache-2.0), MediaMTX
(MIT), FFmpeg (LGPL build). The edge dev image includes PyTorch for RF-DETR; production edge boxes
run the exported ONNX/TensorRT model without it.
