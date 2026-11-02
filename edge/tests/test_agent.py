"""EDG-13: enrolment, heartbeat, config pulling and live reconfiguration of the pipeline.

Done-when from the plan: "changing a rule in the cloud takes effect on the box within 2 minutes".
"""

from __future__ import annotations

import json
import os
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from vision_edge.agent import (
    Agent,
    CameraStatusFile,
    DeviceState,
    EnrolmentError,
    enrol,
    read_camera_statuses,
    write_atomic,
)
from vision_edge.config_watch import ConfigWatcher, RestartRequired
from vision_edge.detection import ReplayDetector
from vision_edge.frames import Frame
from vision_edge.pipeline import CameraPipeline
from vision_edge.sinks import MemorySink
from vision_edge.sysinfo import SystemProbe
from vision_shared.api import CameraStatus
from vision_shared.schemas import (
    CameraConfig,
    Detection,
    EventState,
    Rule,
    RuleType,
    SiteConfig,
    Zone,
)

T0 = datetime(2026, 11, 8, 6, 0, tzinfo=timezone.utc)
ZONE = Zone(id="z", polygon=[(0.1, 0.3), (0.9, 0.3), (0.9, 0.95), (0.1, 0.95)])


def site(
    threshold: int = 2, version: int = 1, extra_rule: bool = True, **cam: object
) -> SiteConfig:
    camera = CameraConfig(id="cam", source="rtsp://nvr/1", zones=[ZONE], **cam)  # type: ignore[arg-type]
    rules = [
        Rule(
            id="crowd",
            type=RuleType.ZONE_OCCUPANCY_OVER,
            camera_id="cam",
            zone_id="z",
            threshold=threshold,
            min_duration_s=5,
            clear_after_s=3,
        )
    ]
    if extra_rule:
        rules.append(
            Rule(
                id="busy",
                type=RuleType.ZONE_OCCUPANCY_OVER,
                camera_id="cam",
                zone_id="z",
                threshold=1,
                min_duration_s=5,
                clear_after_s=3,
            )
        )
    return SiteConfig(id="site", version=version, cameras=[camera], rules=rules)


def frame(i: int, people: int) -> Frame:
    dets = [
        Detection(class_name="person", confidence=0.9, box=(300 + 120 * k, 300, 360 + 120 * k, 600))
        for k in range(people)
    ]
    return Frame(
        camera_id="cam",
        index=i,
        ts=T0 + timedelta(seconds=i / 5),
        width=1280,
        height=720,
        detections=dets,
        video_time_s=i / 5,
    )


def run(p: CameraPipeline, start: int, seconds: float, people: int) -> int:
    n = int(seconds * 5)
    for i in range(start, start + n):
        p.process(frame(i, people))
    return start + n


def pipeline(cfg: SiteConfig, sink: MemorySink) -> CameraPipeline:
    return CameraPipeline(site=cfg, camera=cfg.cameras[0], detector=ReplayDetector(), sinks=[sink])


# --------------------------------------------------------------------------- live reconfiguration


def test_raised_threshold_applies_without_restart() -> None:
    sink = MemorySink()
    p = pipeline(site(threshold=5, extra_rule=False), sink)
    i = run(p, 0, 10, people=3)
    assert sink.triggered == []  # 3 people, limit 5
    assert p.reconfigure(site(threshold=2, version=2, extra_rule=False))
    run(p, i, 10, people=3)
    [event] = sink.triggered
    assert event.rule_id == "crowd" and event.value == 3


def test_unchanged_rule_keeps_its_state_changed_rule_clears_its_alert() -> None:
    sink = MemorySink()
    p = pipeline(site(threshold=2), sink)
    i = run(p, 0, 10, people=3)
    assert {e.rule_id for e in sink.triggered} == {"crowd", "busy"}
    busy_before = next(e for e in p.evaluators if e.rule.id == "busy")
    assert p.reconfigure(site(threshold=9, version=2), now=T0 + timedelta(seconds=11))
    busy_after = next(e for e in p.evaluators if e.rule.id == "busy")
    assert busy_after is busy_before  # same evaluator object: durations and cooldown kept
    crowd = next(e for e in sink.triggered if e.rule_id == "crowd")
    busy = next(e for e in sink.triggered if e.rule_id == "busy")
    assert crowd.state is EventState.CLEARED  # its rule changed: the open alert is closed
    assert crowd.attributes["cleared_by"] == "config_change"
    assert busy.state is EventState.TRIGGERED  # still open, still tracked
    run(p, i, 10, people=0)
    assert busy.state is EventState.CLEARED  # clears normally afterwards


def test_removed_rule_and_disabled_camera() -> None:
    sink = MemorySink()
    p = pipeline(site(), sink)
    run(p, 0, 10, people=3)
    assert p.reconfigure(site(version=2, enabled=False))
    assert p.evaluators == []
    assert all(e.state is EventState.CLEARED for e in sink.triggered)


def test_stream_change_needs_restart() -> None:
    p = pipeline(site(), MemorySink())
    changed = site(version=2).model_copy(deep=True)
    changed.cameras[0].source = "rtsp://nvr/2"
    assert p.reconfigure(changed) is False
    assert p.site.version == 1


def test_config_watcher_applies_a_new_file(tmp_path: Path) -> None:
    path = tmp_path / "site.json"
    write_atomic(path, site(threshold=5, extra_rule=False).model_dump_json().encode())
    sink = MemorySink()
    p = pipeline(site(threshold=5, extra_rule=False), sink)
    clock = [0.0]
    applied: list[int] = []
    watch = ConfigWatcher(path, clock=lambda: clock[0], on_applied=applied.append)
    p.after_frame.append(watch)
    i = run(p, 0, 2, people=3)
    write_atomic(path, b"{ not json")  # a broken file is ignored
    os.utime(path, ns=(1, 1))
    clock[0] += 3
    i = run(p, i, 1, people=3)
    assert applied == [] and p.site.version == 1
    write_atomic(path, site(threshold=2, version=7, extra_rule=False).model_dump_json().encode())
    clock[0] += 3
    i = run(p, i, 10, people=3)
    assert applied == [7] and p.site.version == 7
    assert [e.rule_id for e in sink.triggered] == ["crowd"]


def test_config_watcher_asks_for_restart_on_stream_change(tmp_path: Path) -> None:
    path = tmp_path / "site.json"
    cfg = site()
    write_atomic(path, cfg.model_dump_json().encode())
    p = pipeline(cfg, MemorySink())
    clock = [0.0]
    p.after_frame.append(ConfigWatcher(path, clock=lambda: clock[0]))
    changed = site(version=2).model_copy(deep=True)
    changed.cameras[0].fps = 10
    write_atomic(path, changed.model_dump_json().encode())
    clock[0] += 3
    with pytest.raises(RestartRequired):
        run(p, 0, 1, people=0)


# --------------------------------------------------------------------------- enrolment


def fake_enrol_cloud(seen: list[dict[str, object]]) -> httpx.Client:
    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        if body["enrolment_token"] != "cxe_good_token_123456":
            return httpx.Response(401, json={"detail": "invalid"})
        return httpx.Response(
            200,
            json={
                "device_id": "dev-1",
                "organisation_id": "org-1",
                "site_id": "site",
                "device_token": "cxd_secret",
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_enrol_stores_credentials_privately(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []
    state = enrol(
        "http://cloud.test/", "cxe_good_token_123456", tmp_path, http=fake_enrol_cloud(seen)
    )
    assert state.device_token == "cxd_secret" and state.cloud_url == "http://cloud.test"
    path = DeviceState.path(tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert DeviceState.load(tmp_path) == state
    assert seen[0]["software_version"]


def test_enrol_with_a_bad_token_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(EnrolmentError, match="invalid, already used or expired"):
        enrol("http://cloud.test", "cxe_used_token_1234567", tmp_path, http=fake_enrol_cloud([]))
    assert DeviceState.load(tmp_path) is None


# --------------------------------------------------------------------------- camera status


def test_camera_status_files(tmp_path: Path) -> None:
    clock = [0.0]
    a = CameraStatusFile(tmp_path, "a", clock=lambda: clock[0])
    a.set_config_version(4)
    for _ in range(60):
        clock[0] += 0.2
        a.mark_frame(datetime.now(timezone.utc))
    b = CameraStatusFile(tmp_path, "b", clock=lambda: clock[0])
    b.set_config_version(3)  # running, but no frames yet
    health, applied = read_camera_statuses(tmp_path, ["a", "b", "c"])
    by_id = {h.camera_id: h for h in health}
    assert by_id["a"].status is CameraStatus.ONLINE and by_id["a"].fps == pytest.approx(5, abs=0.5)
    assert by_id["b"].status is CameraStatus.OFFLINE and by_id["b"].message == "no frames"
    assert by_id["c"].status is CameraStatus.OFFLINE and by_id["c"].message == "not running"
    assert applied is None  # camera c has not applied anything
    _, applied = read_camera_statuses(tmp_path, ["a", "b"])
    assert applied == 3  # the oldest version still running
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    health, _ = read_camera_statuses(tmp_path, ["a"], now=later)
    assert health[0].status is CameraStatus.OFFLINE and health[0].message == "stopped"


# --------------------------------------------------------------------------- system probe


def test_system_probe_reads_proc_and_sys(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    (proc / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 250 kB\n")
    (proc / "uptime").write_text("1234.5 999.0\n")
    for n, t in ((0, "45000"), (1, "61500")):
        z = tmp_path / f"sys/class/thermal/thermal_zone{n}"
        z.mkdir(parents=True)
        (z / "temp").write_text(t)
    probe = SystemProbe(tmp_path, disk_path=tmp_path)
    (proc / "stat").write_text("cpu  150 0 150 900 0 0 0 0 0 0\n")  # 100 busy of 200 since then
    r = probe.read()
    assert r.cpu_pct == 50.0 and r.ram_pct == 75.0 and r.temperature_c == 61.5
    assert r.uptime_s == 1234.5 and r.disk_free_pct is not None


def test_system_probe_tolerates_missing_files(tmp_path: Path) -> None:
    r = SystemProbe(tmp_path / "nothing", disk_path=tmp_path).read()
    assert (r.cpu_pct, r.ram_pct, r.temperature_c, r.uptime_s) == (None, None, None, None)


# --------------------------------------------------------------------------- the agent


class FakeConfigCloud:
    """Heartbeat answers with the current config ETag; /config honours If-None-Match."""

    def __init__(self) -> None:
        self.config = site(threshold=4)
        self.online = True
        self.heartbeats: list[dict[str, object]] = []
        self.config_gets = 0

    @property
    def etag(self) -> str:
        return f"v{self.config.version}-{self.config.rules[0].threshold}"

    def handle(self, req: httpx.Request) -> httpx.Response:
        if not self.online:
            raise httpx.ConnectError("down", request=req)
        assert req.headers["authorization"] == "Bearer cxd_secret"
        if req.url.path == "/device/v1/heartbeat":
            self.heartbeats.append(json.loads(req.content))
            return httpx.Response(
                200,
                json={
                    "server_time": T0.isoformat(),
                    "config_version": self.config.version,
                    "config_etag": self.etag,
                },
            )
        if req.url.path == "/device/v1/config":
            self.config_gets += 1
            quoted = f'"{self.etag}"'
            if req.headers.get("if-none-match") == quoted:
                return httpx.Response(304, headers={"ETag": quoted})
            return httpx.Response(
                200, content=self.config.model_dump_json(), headers={"ETag": quoted}
            )
        return httpx.Response(404)


def make_agent(tmp_path: Path, cloud: FakeConfigCloud) -> Agent:
    device = DeviceState("http://cloud.test", "dev-1", "org-1", "site", "cxd_secret")
    return Agent(
        tmp_path,
        device,
        http=httpx.Client(transport=httpx.MockTransport(cloud.handle)),
        probe=SystemProbe(tmp_path / "noproc", disk_path=tmp_path),
    )


def test_agent_pulls_config_only_when_it_changes(tmp_path: Path) -> None:
    cloud = FakeConfigCloud()
    agent = make_agent(tmp_path, cloud)
    agent.tick()
    assert agent.current_config() == cloud.config
    agent.tick()
    agent.tick()
    assert cloud.config_gets == 1  # heartbeat ETag unchanged: no fetch
    cloud.config = site(threshold=2, version=2)
    agent.tick()
    assert cloud.config_gets == 2
    cfg = agent.current_config()
    assert cfg is not None and cfg.version == 2 and cfg.rules[0].threshold == 2


def test_heartbeat_reports_cameras_and_applied_version(tmp_path: Path) -> None:
    cloud = FakeConfigCloud()
    agent = make_agent(tmp_path, cloud)
    agent.tick()
    status = CameraStatusFile(tmp_path, "cam")
    status.set_config_version(1)
    status.mark_frame(datetime.now(timezone.utc))
    agent.tick()
    hb = cloud.heartbeats[-1]
    assert hb["config_version"] == 1 and hb["software_version"]
    cams = hb["cameras"]
    assert isinstance(cams, list) and cams[0]["camera_id"] == "cam"
    assert cams[0]["status"] == "online"


def test_rule_change_reaches_the_running_pipeline_within_two_minutes(tmp_path: Path) -> None:
    """The done-when, with simulated time: agent cycle 60 s, camera checks the file every 2 s."""
    cloud = FakeConfigCloud()
    agent = make_agent(tmp_path, cloud)
    agent.tick()  # box starts with threshold 4
    cfg = agent.current_config()
    assert cfg is not None
    sink = MemorySink()
    p = pipeline(cfg, sink)
    clock = [0.0]
    p.after_frame.append(ConfigWatcher(agent.config_path, clock=lambda: clock[0]))

    i = 0
    cloud.config = site(threshold=2, version=2)  # someone lowers the threshold in the dashboard
    changed_at = clock[0]
    fired_at = None
    for second in range(180):  # 3 minutes of 5 fps video with 3 people in the zone
        clock[0] += 1
        if second % 60 == 59:
            agent.tick()
        i = run(p, i, 1, people=3)
        if sink.triggered and fired_at is None:
            fired_at = clock[0]
    assert fired_at is not None and fired_at - changed_at <= 120
    assert p.site.version == 2


def test_agent_keeps_going_while_offline(tmp_path: Path) -> None:
    cloud = FakeConfigCloud()
    agent = make_agent(tmp_path, cloud)
    agent.tick()
    cloud.online = False
    stop = threading.Event()
    waits: list[float] = []

    def sleep(s: float) -> None:
        waits.append(s)
        if len(waits) == 3:
            cloud.online = True
        if len(waits) == 4:
            stop.set()

    agent.run_forever(stop, interval_s=60, sleep=sleep)
    assert waits == [60, 60, 60, 60]
    assert agent.current_config() == cloud.config  # the cached config survived the outage
    assert len(cloud.heartbeats) == 2
