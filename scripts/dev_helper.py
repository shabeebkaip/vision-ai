"""API steps for scripts/dev.sh (SET-04): demo data and connecting a local edge box.

Run through `uv run python scripts/dev_helper.py <command>` from the repository root; settings come
from `.env` (the same file docker compose uses).

    seed          create the demo organisation once (skips if the demo owner can already sign in)
    device-token  print a fresh one-time enrolment token for the demo site
    prepare-edge  point the demo camera at the fake RTSP camera and make the demo alert quick
    summary       print what is in the local cloud (sites, cameras, alerts)
    set-camera URL  point the demo site's camera at another stream (a real camera's RTSP URL)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

API = "http://localhost:8000/api/v1"
ROOT = Path(__file__).resolve().parents[1]
FAKE_CAMERA = "rtsp://mediamtx:8554/cam2"  # the "desk unattended" scenario (CAM2_CLIP)


def env() -> dict[str, str]:
    """`.env` as a dict (simple KEY=VALUE lines; quotes stripped)."""
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


def demo_login() -> tuple[str, str]:
    e = env()
    return e.get("VISION_DEV_DEMO_EMAIL", "demo@codeox.local"), e["VISION_CLOUD_SEED_PASSWORD"]


def token() -> str | None:
    email, password = demo_login()
    r = httpx.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    return str(r.json()["access_token"]) if r.status_code == 200 else None


def headers() -> dict[str, str]:
    t = token()
    if t is None:
        sys.exit("cannot sign in as the demo owner: run `./scripts/dev.sh up` first")
    return {"Authorization": f"Bearer {t}"}


def demo_site(h: dict[str, str]) -> dict[str, object]:
    sites = httpx.get(f"{API}/sites", headers=h, timeout=15).json()
    if not sites:
        sys.exit("the demo organisation has no site")
    return dict(sites[0])


def cmd_seed() -> int:
    if token() is not None:
        print("demo organisation already there")
        return 0
    e = env()
    email, password = demo_login()
    owner = e.get("VISION_DEV_DB_OWNER_PASSWORD", "vision-owner-dev")
    run_env = {
        **os.environ,
        "VISION_CLOUD_DATABASE_URL": (
            f"postgresql+psycopg://vision_owner:{owner}@localhost:5432/vision"
        ),
        "VISION_CLOUD_SEED_PASSWORD": password,
        "VISION_CLOUD_STORAGE_BACKEND": "local",  # seeding stores nothing in object storage
    }
    out = subprocess.run(
        ["uv", "run", "vision-cloud", "seed-demo", "--owner-email", email],
        cwd=ROOT, env=run_env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if out.returncode != 0:
        print(out.stdout + out.stderr, file=sys.stderr)
        return 1
    h = headers()
    site = demo_site(h)
    httpx.patch(
        f"{API}/sites/{site['id']}",
        json={"industry": "restaurant", "city": "Riyadh", "name_ar": "مطعم تجريبي"},
        headers=h, timeout=15,
    )  # fmt: skip
    # Someone to alert, so the dispatcher's work shows in the dashboard. The number is a
    # placeholder; with VISION_CLOUD_ALERT_DRY_RUN=true (the default) nothing is sent anywhere.
    httpx.post(
        f"{API}/recipients",
        json={"name": "Demo manager (example number)", "name_ar": "مدير تجريبي",
              "channel": "whatsapp", "address": "+966500000000"},
        headers=h, timeout=15,
    )  # fmt: skip
    print("demo organisation created")
    return 0


def cmd_device_token() -> int:
    h = headers()
    site = demo_site(h)
    r = httpx.post(
        f"{API}/sites/{site['id']}/devices", json={"name": "local edge box"}, headers=h, timeout=15
    )
    r.raise_for_status()
    print(r.json()["enrolment_token"])
    return 0


def cmd_prepare_edge() -> int:
    h = headers()
    site = demo_site(h)
    cams = httpx.get(f"{API}/cameras", params={"site_id": site["id"]}, headers=h, timeout=15).json()
    for cam in cams:
        httpx.patch(
            f"{API}/cameras/{cam['id']}", json={"source": FAKE_CAMERA}, headers=h, timeout=15
        ).raise_for_status()
    # The synthetic clips are drawings, so the model sees nobody: "station unattended" is the
    # alert they produce. Make it fire after one minute at any time of day, for a quick demo.
    rules = httpx.get(f"{API}/rules", params={"site_id": site["id"]}, headers=h, timeout=15).json()
    for rule in rules:
        if rule["type"] != "zone_empty":
            continue
        body = {k: v for k, v in rule.items() if k not in ("site_id", "created_at", "updated_at")}
        body.update(min_duration_s=60, schedule=None, cooldown_s=300)
        httpx.put(f"{API}/rules/{rule['id']}", json=body, headers=h, timeout=15).raise_for_status()
    print(f"{len(cams)} camera(s) now read {FAKE_CAMERA}; 'unattended' fires after 1 minute")
    return 0


def cmd_set_camera(url: str) -> int:
    if not url.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        sys.exit("give an rtsp:// (or http://) stream address")
    h = headers()
    site = demo_site(h)
    cams = httpx.get(f"{API}/cameras", params={"site_id": site["id"]}, headers=h, timeout=15).json()
    for cam in cams:
        httpx.patch(
            f"{API}/cameras/{cam['id']}", json={"source": url}, headers=h, timeout=15
        ).raise_for_status()
    print(f"{len(cams)} camera(s) updated; the edge box restarts on the new stream within a minute")
    return 0


def cmd_summary() -> int:
    h = headers()
    for site in httpx.get(f"{API}/sites", headers=h, timeout=15).json():
        print(
            f"  site {site['name']}: cameras online {site['cameras_online']}/"
            f"{site['cameras_total']}, alerts today {site['alerts_today']}"
        )
    return 0


COMMANDS = {
    "seed": cmd_seed,
    "device-token": cmd_device_token,
    "prepare-edge": cmd_prepare_edge,
    "summary": cmd_summary,
}

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "set-camera":
        sys.exit(cmd_set_camera(sys.argv[2]))
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: dev_helper.py {{{'|'.join(COMMANDS)}|set-camera URL}}")
    try:
        sys.exit(COMMANDS[sys.argv[1]]())
    except httpx.HTTPError as exc:
        sys.exit(f"the local API did not answer as expected: {exc}")
