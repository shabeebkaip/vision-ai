# Running Code-Ox Vision on your own computer

Everything runs on one machine: the cloud API, the background worker, the dashboard, four fake
cameras, and (when you ask for it) an edge box that watches a camera and sends alerts. Two commands
after a one-time install; about 15 minutes the first time, seconds after that.

## What you need

| | macOS | Windows | Linux (Ubuntu) |
| --- | --- | --- | --- |
| Shell | Terminal | **WSL2** with Ubuntu (see below); run everything inside it | any terminal |
| Docker | Docker Desktop | Docker Desktop with *WSL integration* on for your Ubuntu | Docker Engine + Compose plugin |
| git, curl | preinstalled (or `xcode-select --install`) | `sudo apt install git curl` in Ubuntu | `sudo apt install git curl` |
| uv (Python tools) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | same, inside Ubuntu | same |

Memory and disk: 8 GB RAM and 15 GB free disk for the cloud and dashboard; the edge box adds about
10 GB of disk (its AI model needs PyTorch) and keeps a CPU core busy. An Apple Silicon or recent
Intel/AMD laptop is fine.

You do not need to install Python, PostgreSQL, Redis or Node: uv brings Python, and the rest runs in
Docker.

### Windows: set up WSL2 once

1. Open PowerShell as administrator: `wsl --install -d Ubuntu`, restart, create the Ubuntu user.
2. Install Docker Desktop; in *Settings > Resources > WSL integration* switch on **Ubuntu**.
3. From now on open the **Ubuntu** app and work there. Keep the code inside Ubuntu (for example
   `~/code`), not under `/mnt/c`: it is much faster.

### Linux: Docker without sudo

```bash
sudo usermod -aG docker "$USER"   # then log out and in again
```

## First time

```bash
git clone https://github.com/shabeebkaip/vision-ai.git
cd vision-ai
./scripts/dev.sh setup
```

`setup` checks the tools (and tells you exactly what is missing), installs the Python packages,
writes `.env` with freshly generated secret keys and a demo sign-in, and renders the clips the fake
cameras play. `.env` stays on your machine; it is never committed.

## Every day

```bash
./scripts/dev.sh up
```

It starts everything, waits until it is healthy, creates the demo organisation on the first run,
and prints:

```
  Dashboard     http://localhost:5173
  API docs      http://localhost:8000/docs
  Fake cameras  rtsp://localhost:8554/cam1 ... cam4 (VLC: Media > Open Network Stream)
  Sign in       demo@codeox.local / demo-xxxxxxxxxxxx
```

Open the dashboard and sign in with those details. The first `up` builds the images and installs
the dashboard's packages, which takes a few minutes; later starts take seconds.

| Command | What it does |
| --- | --- |
| `./scripts/dev.sh status` | what is running, the addresses and the sign-in |
| `./scripts/dev.sh camera URL` | point the demo camera at another stream |
| `./scripts/dev.sh logs` | follow all logs; `./scripts/dev.sh logs api` for one service |
| `./scripts/dev.sh down` | stop everything; your data is kept |
| `./scripts/dev.sh reset` | stop and **delete** the local data (asks first) |

## See an alert end to end

```bash
./scripts/dev.sh edge
```

This builds the edge image (the first time: several GB and 10+ minutes), registers an edge box with
your local cloud, points the demo camera at a fake camera, and starts it. Within about two minutes a
**Station unattended** alert appears in the dashboard with the box's snapshot and a clip; it is also
in the delivery log for "Demo manager (example number)".

What happens on the way: the box reads the RTSP stream, runs the RF-DETR model, the rule fires after
one minute without a person at the counter, the event and its snapshot and clip are uploaded, the
worker groups it into an alert and "sends" it. Sending is a dry run: it is only logged
(`VISION_CLOUD_ALERT_DRY_RUN=true` in `.env`). Mark it **Correct** or **False alarm** in the dashboard.

The fake cameras play drawn scenes, so the model sees no real people: "station unattended" is the
alert they produce. For real scenes, see "Using your own videos" below.

## Optional

**Real Telegram alerts.** Create a bot and set the token as in
`docs/runbooks/telegram-alerts.md`, then in `.env`:
`VISION_CLOUD_TELEGRAM_BOT_TOKEN=...` and `VISION_CLOUD_ALERT_DRY_RUN=false`, and run
`./scripts/dev.sh up` again. Messages reach Telegram straight away; the buttons and linking need a
public https address for your laptop (a tunnel, described in that runbook).

**Using your own videos.** Put MP4 files in a folder outside the repository, and in `.env`:
`CLIPS_DIR=/full/path/to/folder`, `CAM2_CLIP=yourfile.mp4`. The demo camera reads `cam2`. Then
`./scripts/dev.sh down && ./scripts/dev.sh up && ./scripts/dev.sh edge`. Adjust the zones in the
dashboard (*Sites and cameras > Zones and lines*) to fit the scene; the editor has no picture of the
camera behind it yet (that arrives with EDG-03), so place them by eye. Never commit customer footage.

**A real camera on your network.** Check the stream first, then point the demo camera at it (for a
Hikvision NVR the sub-stream is `rtsp://user:pass@NVR_IP:554/Streaming/Channels/102`):

```bash
uv run vision-edge check-camera "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102"
./scripts/dev.sh camera "rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102"
```

The edge box restarts on the new stream within a minute. The password is stored encrypted in the
local database and never shown in the dashboard.

**Demo data instead of the API.** `VITE_API_BASE_URL=` (empty) in `.env`, then `up`: the dashboard
shows its built-in demo data and needs no sign-in data.

**Your own tweaks** (other ports, a company proxy's certificate) go in
`deploy/docker-compose.dev.local.yml`, which the script includes when it exists and Git ignores.

## Working on the code

```bash
uv run pytest                     # all Python tests
cd web && npm ci && npm test      # dashboard tests (needs Node 22)
uv run vision-eval run --strict   # the video regression scorecard
```

The API and worker run from the Docker image: after changing cloud code, `./scripts/dev.sh up`
rebuilds it. The dashboard reloads by itself when you edit `web/src`.

## When something goes wrong

| What you see | What to do |
| --- | --- |
| `Docker is installed but not running` | start Docker Desktop (Linux: `sudo systemctl start docker`) |
| `port is already allocated` for 5432, 6379, 8000, 9000 or 5173 | another program uses it (often a local PostgreSQL or Redis): stop it, or change the port in `deploy/docker-compose.dev.local.yml` |
| `the API did not come up` | `./scripts/dev.sh logs api migrate`; a broken `.env` is the usual cause: compare with `.env.example` |
| sign-in fails | `./scripts/dev.sh status` shows the demo email and password from `.env` |
| the dashboard stays empty after `up` | the first start installs its packages: `./scripts/dev.sh logs web` |
| no alert after `edge` | `./scripts/dev.sh logs edge-box`: the first start downloads the model (about 350 MB); on a slow laptop give it five minutes |
| `no space left on device` | Docker Desktop: *Settings > Resources* raise the disk; or `docker system prune` |
| start completely fresh | `./scripts/dev.sh reset`, then `up` |
