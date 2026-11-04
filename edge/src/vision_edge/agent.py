"""Edge agent (EDG-13): enrolment, heartbeat and site config from the cloud.

One agent process per box, next to one `vision-edge run` process per camera. They share a state
directory (`VISION_STATE_DIR`, default `var/state`):

    state/device.json          device id, site id, cloud URL and token (mode 0600), from `enrol`
    state/site.json            the site config pulled from the cloud; camera processes watch it
    state/site.etag            ETag of that config, for conditional polling
    state/status/<camera>.json written by each camera process, read for the heartbeat

Every `interval_s` (60 s) the agent sends a heartbeat (box health, per-camera status, versions,
applied config version, outbox backlog). The answer carries the current config ETag; when it
differs from ours the agent fetches `/device/v1/config` right away (and also polls with
`If-None-Match` each cycle), writes `site.json` atomically, and the camera processes apply it
without restarting (`vision_edge.config_watch`). A rule changed in the cloud therefore reaches the
pipeline within one interval plus a few seconds.

Model downloads and log upload on request are a follow-up (EDG-13b).
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import structlog

from vision_edge.sysinfo import SystemProbe
from vision_shared.api import (
    CameraHealth,
    CameraStatus,
    EnrolmentRequest,
    EnrolmentResponse,
    Heartbeat,
    HeartbeatResponse,
)
from vision_shared.schemas import SiteConfig

log = structlog.get_logger(__name__)

SOFTWARE_VERSION = "0.1.0"
STALE_STATUS_S = 30.0  # a camera process that has not written its status for this long is offline


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def write_atomic(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write via a temporary file and rename, so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, mode if mode is not None else 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- device identity


@dataclass(frozen=True)
class DeviceState:
    cloud_url: str
    device_id: str
    organisation_id: str
    site_id: str
    device_token: str

    @staticmethod
    def path(state_dir: Path) -> Path:
        return state_dir / "device.json"

    def save(self, state_dir: Path) -> None:
        write_atomic(self.path(state_dir), json.dumps(asdict(self), indent=2).encode(), mode=0o600)

    @classmethod
    def load(cls, state_dir: Path) -> DeviceState | None:
        p = cls.path(state_dir)
        if not p.is_file():
            return None
        return cls(**json.loads(p.read_text(encoding="utf-8")))


class EnrolmentError(Exception):
    pass


def enrol(
    cloud_url: str,
    enrolment_token: str,
    state_dir: Path,
    *,
    hardware_tier: str | None = None,
    http: httpx.Client | None = None,
) -> DeviceState:
    """Exchange the one-time enrolment token for the device token and store it."""
    client = http or httpx.Client(timeout=30)
    body = EnrolmentRequest(
        enrolment_token=enrolment_token,
        hardware_tier=hardware_tier,
        software_version=SOFTWARE_VERSION,
        hostname=socket.gethostname()[:200],
    )
    try:
        r = client.post(
            f"{cloud_url.rstrip('/')}/device/v1/enrol",
            content=body.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise EnrolmentError(f"cloud unreachable: {exc}") from exc
    if r.status_code == 401:
        raise EnrolmentError("the enrolment token is invalid, already used or expired")
    if r.status_code != 200:
        raise EnrolmentError(f"enrolment failed: HTTP {r.status_code} {r.text[:200]}")
    res = EnrolmentResponse.model_validate_json(r.content)
    state = DeviceState(
        cloud_url=cloud_url.rstrip("/"),
        device_id=res.device_id,
        organisation_id=res.organisation_id,
        site_id=res.site_id,
        device_token=res.device_token,
    )
    state.save(state_dir)
    log.info("device.enrolled", device_id=res.device_id, site_id=res.site_id)
    return state


# --------------------------------------------------------------------------- camera status files


@dataclass
class CameraStatusFile:
    """Written by a camera process (throttled), read by the agent for the heartbeat."""

    state_dir: Path
    camera_id: str
    every_s: float = 5.0
    clock: Callable[[], float] = time.monotonic
    _last_write: float = -1e9
    _frames: int = 0
    _window_start: float | None = None
    _fps: float = 0.0
    _last_frame_at: datetime | None = None
    _config_version: int | None = None

    @property
    def path(self) -> Path:
        return self.state_dir / "status" / f"{self.camera_id}.json"

    def set_config_version(self, version: int) -> None:
        self._config_version = version
        self.write(force=True)

    def mark_frame(self, at: datetime | None = None) -> None:
        now = self.clock()
        if self._window_start is None:
            self._window_start = now
        self._frames += 1
        first = self._last_frame_at is None
        self._last_frame_at = at or _utcnow()
        span = now - self._window_start
        if span >= self.every_s:
            self._fps = self._frames / span
            self._frames, self._window_start = 0, now
        self.write(force=first)  # the first frame is reported at once: the camera is up

    def write(self, force: bool = False, message: str = "") -> None:
        now = self.clock()
        if not force and now - self._last_write < self.every_s:
            return
        self._last_write = now
        body = {
            "camera_id": self.camera_id,
            "fps": round(self._fps, 2),
            "last_frame_at": self._last_frame_at.isoformat() if self._last_frame_at else None,
            "config_version": self._config_version,
            "written_at": _utcnow().isoformat(),
            "message": message,
        }
        write_atomic(self.path, json.dumps(body).encode())


def read_camera_statuses(
    state_dir: Path, camera_ids: list[str], now: datetime | None = None
) -> tuple[list[CameraHealth], int | None]:
    """Heartbeat camera list plus the config version every reporting camera has applied
    (None until all of them report one)."""
    now = now or _utcnow()
    healths: list[CameraHealth] = []
    versions: list[int | None] = []
    for cam in camera_ids:
        p = state_dir / "status" / f"{cam}.json"
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            healths.append(
                CameraHealth(camera_id=cam, status=CameraStatus.OFFLINE, message="not running")
            )
            versions.append(None)
            continue
        written = datetime.fromisoformat(s["written_at"])
        last = datetime.fromisoformat(s["last_frame_at"]) if s.get("last_frame_at") else None
        fresh = (now - written).total_seconds() <= STALE_STATUS_S
        frames = last is not None and (now - last).total_seconds() <= STALE_STATUS_S
        status = CameraStatus.ONLINE if fresh and frames else CameraStatus.OFFLINE
        message = "" if status is CameraStatus.ONLINE else ("no frames" if fresh else "stopped")
        healths.append(
            CameraHealth(
                camera_id=cam,
                status=status,
                fps=s.get("fps"),
                last_frame_at=last,
                message=s.get("message") or message,
            )
        )
        versions.append(s.get("config_version"))
    applied = (
        None if not versions or None in versions else min(v for v in versions if v is not None)
    )
    return healths, applied


# --------------------------------------------------------------------------- the agent


class Agent:
    def __init__(
        self,
        state_dir: Path,
        device: DeviceState,
        *,
        http: httpx.Client | None = None,
        probe: SystemProbe | None = None,
        outbox_dirs: list[Path] | None = None,
        model_version: str | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.device = device
        self.http = http or httpx.Client(timeout=30)
        self.probe = probe or SystemProbe(disk_path=state_dir)
        self.outbox_dirs = outbox_dirs or []
        self.model_version = model_version
        self._headers = {"Authorization": f"Bearer {device.device_token}"}
        self.config_path = state_dir / "site.json"
        self.etag_path = state_dir / "site.etag"

    def _url(self, path: str) -> str:
        return f"{self.device.cloud_url}/device/v1{path}"

    # ---------------------------------------------------------------- config
    @property
    def etag(self) -> str | None:
        try:
            return self.etag_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def current_config(self) -> SiteConfig | None:
        try:
            return SiteConfig.model_validate_json(self.config_path.read_bytes())
        except (OSError, ValueError):
            return None

    def pull_config(self) -> bool:
        """Conditional GET of the site config. True when a new config was written."""
        headers = dict(self._headers)
        if self.etag and self.config_path.is_file():
            headers["If-None-Match"] = self.etag
        r = self.http.get(self._url("/config"), headers=headers)
        if r.status_code == 304:
            return False
        r.raise_for_status()
        config = SiteConfig.model_validate_json(r.content)  # never write a config we cannot read
        write_atomic(self.config_path, config.model_dump_json(indent=2).encode())
        self.etag_path.write_text(r.headers.get("ETag", ""), encoding="utf-8")
        log.info(
            "agent.config_updated",
            site_id=config.id,
            config_version=config.version,
            cameras=len(config.cameras),
            rules=len(config.rules),
        )
        return True

    # ---------------------------------------------------------------- heartbeat
    def _outbox_pending(self) -> int | None:
        from vision_edge.outbox import Outbox

        total, seen = 0, False
        for d in self.outbox_dirs:
            if (d / "outbox.db").is_file():
                ob = Outbox(d)
                s = ob.stats()
                ob.close()
                total += s.pending_events + s.pending_media
                seen = True
        return total if seen else None

    def heartbeat(self) -> HeartbeatResponse:
        config = self.current_config()
        cameras = [c.id for c in config.cameras if c.enabled] if config else []
        healths, applied = read_camera_statuses(self.state_dir, cameras)
        reading = self.probe.read()
        body = Heartbeat(
            sent_at=_utcnow(),
            software_version=SOFTWARE_VERSION,
            model_version=self.model_version,
            config_version=applied,
            uptime_s=reading.uptime_s,
            cpu_pct=reading.cpu_pct,
            ram_pct=reading.ram_pct,
            disk_free_pct=reading.disk_free_pct,
            temperature_c=reading.temperature_c,
            outbox_pending=self._outbox_pending(),
            cameras=healths,
        )
        r = self.http.post(
            self._url("/heartbeat"),
            content=body.model_dump_json(),
            headers={**self._headers, "Content-Type": "application/json"},
        )
        r.raise_for_status()
        return HeartbeatResponse.model_validate_json(r.content)

    # ---------------------------------------------------------------- loop
    def tick(self) -> None:
        """One cycle: heartbeat, then pull the config when it changed (or is missing)."""
        resp = self.heartbeat()
        known = (self.etag or "").strip('"')
        if resp.config_etag != known or not self.config_path.is_file():
            self.pull_config()

    def run_forever(
        self,
        stop: threading.Event,
        *,
        interval_s: float = 60.0,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        wait = sleep or stop.wait
        while not stop.is_set():
            try:
                self.tick()
                wait(interval_s)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 401:
                    log.error("agent.unauthorised", hint="device revoked or token wrong: re-enrol")
                else:
                    log.warning("agent.cloud_error", status=code)
                wait(interval_s)
            except httpx.HTTPError as exc:
                log.warning("agent.offline", error=str(exc), retry_in_s=interval_s)
                wait(interval_s)
