"""EDG-13 end to end: the real edge agent against the real device API.

A rule changed through the dashboard API reaches the box's site config in one agent cycle, and
the heartbeat updates the device and camera status the dashboard shows.
Skipped where the edge package is not installed (the cloud-only CI job)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from vision_shared.schemas import SiteConfig

from .conftest import World, auth

pytest.importorskip("vision_edge")

from vision_edge.agent import Agent, CameraStatusFile, DeviceState, enrol
from vision_edge.sysinfo import SystemProbe


def test_enrol_heartbeat_and_rule_change(world: World, tmp_path: Path) -> None:
    c, a = world.client, world.a
    owner = auth(a.owner_token)
    r = c.post(f"/api/v1/sites/{a.site_ids[0]}/devices", json={"name": "box 2"}, headers=owner)
    assert r.status_code == 201, r.text
    device = enrol("http://testserver", r.json()["enrolment_token"], tmp_path, http=c)
    assert DeviceState.load(tmp_path) == device

    agent = Agent(tmp_path, device, http=c, probe=SystemProbe(disk_path=tmp_path))
    agent.tick()
    config = agent.current_config()
    assert isinstance(config, SiteConfig) and config.id == a.site_ids[0]
    assert [rule.threshold for rule in config.rules] == [3]

    # The camera process reports in; the next heartbeat carries it to the dashboard.
    cam = a.camera_ids[0]
    status = CameraStatusFile(tmp_path, cam)
    status.set_config_version(config.version)
    status.mark_frame(datetime.now(timezone.utc))
    agent.tick()
    dev = next(
        d for d in c.get("/api/v1/devices", headers=owner).json() if d["id"] == device.device_id
    )
    assert dev["last_heartbeat_at"] and dev["applied_config_version"] == config.version
    assert c.get(f"/api/v1/cameras/{cam}", headers=owner).json()["status"] == "online"

    # Someone changes the rule in the dashboard; one agent cycle brings it to the box.
    rule = c.get(f"/api/v1/rules/{a.rule_id}", headers=owner).json()
    rule["threshold"] = 7
    for k in ("site_id", "created_at", "updated_at"):
        rule.pop(k)
    assert c.put(f"/api/v1/rules/{a.rule_id}", json=rule, headers=owner).status_code == 200
    agent.tick()
    new = agent.current_config()
    assert new is not None and new.version == config.version + 1
    assert [r.threshold for r in new.rules] == [7]
