#!/usr/bin/env bash
# Code-Ox Vision on your own machine (SET-04). macOS, Linux, and Windows through WSL2.
# Guide: docs/runbooks/local-setup.md
#
#   ./scripts/dev.sh setup     check tools, install dependencies, write .env, make demo clips
#   ./scripts/dev.sh up        start cloud, worker, dashboard and fake cameras; create the demo login
#   ./scripts/dev.sh edge      also run an edge box connected to the local cloud (big first build)
#   ./scripts/dev.sh camera URL  point the demo camera at another stream (e.g. a real camera)
#   ./scripts/dev.sh status    what is running, and the addresses
#   ./scripts/dev.sh logs [service]
#   ./scripts/dev.sh down      stop everything (data is kept)
#   ./scripts/dev.sh reset     stop everything and DELETE the local data (asks first)
#
# Written for bash 3.2 (macOS) and later.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f deploy/docker-compose.dev.yml)
# Your own tweaks (ports, a corporate proxy's CA, ...) go in this git-ignored file.
[ -f deploy/docker-compose.dev.local.yml ] && COMPOSE+=(-f deploy/docker-compose.dev.local.yml)
COMPOSE+=(--env-file .env)
ALL_PROFILES=(--profile edge --profile edge-standalone)
BUILD_FLAG="--build"
[ "${SKIP_BUILD:-0}" = "1" ] && BUILD_FLAG=""

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

env_value() { # env_value KEY -> value from .env (empty if missing)
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]$//"
}

set_env() { # set_env KEY VALUE: replace or append in .env (portable sed)
  local key="$1" value="$2"
  if grep -qE "^#? ?$key=" .env; then
    grep -vE "^#? ?$key=" .env > .env.tmp && mv .env.tmp .env
  fi
  printf '%s=%s\n' "$key" "$value" >> .env
}

wait_for() { # wait_for URL SECONDS WHAT
  local url="$1" limit="$2" what="$3" waited=0
  printf '    waiting for %s ' "$what"
  until curl -sf -o /dev/null "$url"; do
    sleep 3; waited=$((waited + 3)); printf '.'
    if [ "$waited" -ge "$limit" ]; then
      echo; die "$what did not come up in ${limit}s; see: ./scripts/dev.sh logs"
    fi
  done
  echo " ok"
}

check_tools() {
  local missing=0
  have git || { warn "git is missing"; missing=1; }
  have curl || { warn "curl is missing"; missing=1; }
  if ! have docker; then
    warn "Docker is missing: install Docker Desktop (macOS, Windows) or Docker Engine (Linux)"
    missing=1
  elif ! docker compose version >/dev/null 2>&1; then
    warn "'docker compose' (v2) is missing: update Docker"; missing=1
  elif ! docker info >/dev/null 2>&1; then
    warn "Docker is installed but not running: start Docker Desktop (or: sudo systemctl start docker)"
    missing=1
  fi
  if ! have uv; then
    warn "uv is missing. Install it with:"
    warn "  curl -LsSf https://astral.sh/uv/install.sh | sh     (then open a new terminal)"
    missing=1
  fi
  [ "$missing" = 0 ] || die "install the tools above, then run ./scripts/dev.sh setup again"
}

cmd_setup() {
  say "Checking tools"
  check_tools
  docker compose version | sed 's/^/    /'
  uv --version | sed 's/^/    /'

  say "Installing Python packages (uv downloads Python 3.11+ if needed)"
  uv sync --all-packages

  if [ ! -f .env ]; then
    say "Writing .env with fresh secret keys"
    cp .env.example .env
    while IFS= read -r line; do
      set_env "${line%%=*}" "${line#*=}"
    done < <(uv run --quiet vision-cloud gen-keys)
    set_env VISION_DEV_DEMO_EMAIL "demo@codeox.local"
    set_env VISION_CLOUD_SEED_PASSWORD "demo-$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 12)"
  else
    say ".env exists: keeping it"
    [ -n "$(env_value VISION_CLOUD_JWT_SECRET)" ] || die ".env has no VISION_CLOUD_JWT_SECRET: run 'uv run vision-cloud gen-keys' and paste both lines into .env"
    [ -n "$(env_value VISION_DEV_DEMO_EMAIL)" ] || set_env VISION_DEV_DEMO_EMAIL "demo@codeox.local"
    [ -n "$(env_value VISION_CLOUD_SEED_PASSWORD)" ] || set_env VISION_CLOUD_SEED_PASSWORD "demo-$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 12)"
  fi

  if ! ls test-videos/synthetic/*.mp4 >/dev/null 2>&1; then
    say "Rendering the synthetic clips for the fake cameras"
    uv run vision-eval synth --out test-videos/synthetic --video
  fi

  say "Setup done. Next: ./scripts/dev.sh up"
}

cmd_up() {
  [ -f .env ] || die "no .env yet: run ./scripts/dev.sh setup first"
  say "Starting the cloud, worker, dashboard and fake cameras (first build takes a few minutes)"
  "${COMPOSE[@]}" up -d $BUILD_FLAG
  wait_for http://localhost:8000/healthz 300 "the API"
  say "Demo organisation"
  uv run --quiet python scripts/dev_helper.py seed
  wait_for http://localhost:5173/ 600 "the dashboard (installs its packages on first start)"
  cmd_status
}

cmd_edge() {
  [ -f .env ] || die "no .env yet: run ./scripts/dev.sh setup first"
  curl -sf -o /dev/null http://localhost:8000/healthz || die "the cloud is not running: ./scripts/dev.sh up"
  warn "The edge image includes PyTorch for the RF-DETR model: the first build downloads several GB"
  warn "and the model runs on your CPU (a fan may spin up). Stop it with: ./scripts/dev.sh down"
  say "Building the edge image"
  [ -z "$BUILD_FLAG" ] || "${COMPOSE[@]}" --profile edge build edge-agent
  if [ ! -f var/dev/edge-enrolled ]; then
    say "Enrolling the edge box with the local cloud"
    local token
    token="$(uv run --quiet python scripts/dev_helper.py device-token)"
    "${COMPOSE[@]}" --profile edge run --rm --no-deps edge-agent enrol "$token" --cloud-url http://api:8000
    mkdir -p var/dev && date > var/dev/edge-enrolled
  fi
  say "Pointing the demo camera at a fake camera"
  uv run --quiet python scripts/dev_helper.py prepare-edge
  say "Starting the edge box"
  "${COMPOSE[@]}" --profile edge up -d edge-agent edge-box
  say "Running. Within about two minutes a 'Station unattended' alert appears in the dashboard."
  echo "    Follow it with: ./scripts/dev.sh logs edge-box"
}

cmd_status() {
  "${COMPOSE[@]}" "${ALL_PROFILES[@]}" ps --format 'table {{.Service}}\t{{.Status}}' || true
  echo
  echo "  Dashboard     http://localhost:5173"
  echo "  API docs      http://localhost:8000/docs"
  echo "  Fake cameras  rtsp://localhost:8554/cam1 ... cam4 (VLC: Media > Open Network Stream)"
  echo "  Sign in       $(env_value VISION_DEV_DEMO_EMAIL) / $(env_value VISION_CLOUD_SEED_PASSWORD)"
  if curl -sf -o /dev/null http://localhost:8000/healthz; then
    uv run --quiet python scripts/dev_helper.py summary 2>/dev/null || true
  fi
}

cmd_logs() { "${COMPOSE[@]}" "${ALL_PROFILES[@]}" logs -f --tail 100 "$@"; }

cmd_down() {
  say "Stopping everything (your data is kept)"
  "${COMPOSE[@]}" "${ALL_PROFILES[@]}" down
}

cmd_reset() {
  if [ "${1:-}" != "--yes" ]; then
    printf 'This deletes the local database, stored snapshots and the edge box enrolment. Type "reset": '
    read -r answer
    [ "$answer" = "reset" ] || die "nothing deleted"
  fi
  "${COMPOSE[@]}" "${ALL_PROFILES[@]}" down -v
  rm -f var/dev/edge-enrolled
  say "Local data deleted. Start again with: ./scripts/dev.sh up"
}

case "${1:-help}" in
  setup) cmd_setup ;;
  up) cmd_up ;;
  edge) cmd_edge ;;
  camera)
    [ -n "${2:-}" ] || die "usage: ./scripts/dev.sh camera rtsp://user:pass@camera/stream"
    uv run --quiet python scripts/dev_helper.py set-camera "$2" ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "$@" ;;
  down) cmd_down ;;
  reset) shift; cmd_reset "$@" ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
