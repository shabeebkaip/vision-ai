## Phase 0 — Accounts, access and machines (week 1)

All Must. About 12 developer-days of effort, but three items have outside waiting time (WhatsApp verification, the CV hire, client footage), so they start on day one even though nothing waits on them until later.

| ID | Task | Owner | Days | Needs | Done when |
| --- | --- | --- | --- | --- | --- |
| SET-01 | Name the people in each role (PO, LD, BE ×2, FE, DO, QA) and their time share | PO | 0.5 |  | Names written in this plan and in the GitHub team |
| SET-02 | Hire or contract the senior CV engineer: job description, shortlist, a paid take-home task (read a clip, detect people, count them in a zone, export a CSV), technical interview | PO, LD | 5 (spread over 3 weeks) |  | Contract signed, start date set |
| SET-03 | Create GitHub organisation repo `codeox-vision` (private), teams, branch protection on `main` (review + green CI required) | DO | 0.5 |  | Repo exists, protection on |
| SET-04 | Developer machine setup script `scripts/setup-dev.sh` for macOS, Ubuntu and Windows WSL2: Python 3.11, Docker Desktop, Node 20, Git, FFmpeg, MediaMTX, VS Code, Claude Code | DO | 1 | SET-03 | A new developer goes from blank laptop to running the test suite in under 2 hours |
| SET-05 | Confirm Claude Code access for every developer; commit shared project settings in `.claude/settings.json` | DO | 0.25 | SET-03 | Each developer has opened the repo in Claude Code |
| SET-06 | Anthropic Console account and API keys for the vision-language check: separate dev and production keys, monthly spend limit | PO | 0.25 |  | Keys in the secrets vault, limit set |
| SET-07 | Telegram bot via BotFather plus a "Vision Dev Alerts" group | LD | 0.25 |  | Test message arrives in the group from a script |
| SET-08 | WhatsApp Cloud API: Meta Business verification, dedicated phone number, display name approval, three utility templates in English and Arabic (alert with image, daily summary, system warning) | PO | 1 (+1 to 3 weeks waiting) |  | Templates approved; a test alert reaches the PO's phone |
| SET-09 | Staging server (8 vCPU, 32 GB RAM, 200 GB disk) with Docker, firewall, backups; DNS `staging.vision.code-ox.com` and `vision.code-ox.com` with TLS | DO | 0.5 |  | Server reachable over HTTPS, nightly backup running |
| SET-10 | Roboflow free workspace and RunPod account with a monthly spend cap for training GPUs | CV | 0.25 | SET-02 | Both accounts in the vault |
| SET-11 | Office NVR access: admin login, channel list, sub-stream set to 1280×720, 10 fps, H.264 on 2 to 4 cameras; NVR on a fixed IP | PO, DO | 1 |  | `ffprobe` reads the sub-stream from a laptop on the office network |
| SET-12 | Secure remote access to the office cameras for the India team: Tailscale on a small always-on office machine that relays RTSP | DO | 0.5 | SET-11 | A developer in India plays the office stream in VLC |
| SET-13 | Shared secrets vault (Bitwarden or 1Password) with folders per environment | DO | 0.25 |  | All keys from SET-06 to SET-12 stored there, none in chat |
| SET-14 | GitHub Projects board: import every task in this plan, labels per phase and priority, sprint field | PO, LD | 0.5 | SET-03 | Board shows all tasks with IDs |
| SET-15 | Ask 2 to 3 friendly clients (restaurant, shop, warehouse) for 1 to 2 hours of exported CCTV footage each, from busy and quiet periods, day and night | PO | 1 | SET-16 | Footage received for at least 2 sites |
| SET-16 | Footage consent letter: what we use it for (testing and training only), where it is stored, deletion on request, no faces used for identification | PO | 0.5 |  | Signed by each client before footage is handed over |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
