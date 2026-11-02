"""CLD-04: enrolment, heartbeat, config with ETag, model release, log upload stub."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vision_cloud.db import system_session
from vision_cloud.models import Device, ModelRelease
from vision_shared.api import HeartbeatResponse
from vision_shared.schemas import SiteConfig

from .conftest import World, auth


def _new_device(world: World) -> str:
    r = world.client.post(
        f"/api/v1/sites/{world.a.site_ids[1]}/devices",
        json={"name": "box 2", "hardware_tier": "pro"},
        headers=auth(world.a.owner_token),
    )
    assert r.status_code == 201
    assert r.json()["device"]["status"] == "pending"
    return str(r.json()["enrolment_token"])


def test_enrolment_token_is_one_time(world: World) -> None:
    c = world.client
    token = _new_device(world)
    r = c.post("/device/v1/enrol", json={"enrolment_token": token, "hostname": "jetson-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["site_id"] == world.a.site_ids[1]
    assert body["organisation_id"] == world.a.org_id
    assert body["device_token"].startswith("cxd_")
    again = c.post("/device/v1/enrol", json={"enrolment_token": token})
    assert again.status_code == 401
    devices = c.get(
        f"/api/v1/devices?site_id={world.a.site_ids[1]}", headers=auth(world.a.owner_token)
    ).json()
    assert devices[0]["status"] == "active" and devices[0]["hardware_tier"] == "pro"


def test_expired_enrolment_token(world: World) -> None:
    c = world.client
    token = _new_device(world)
    with system_session(c.app.state.vision.sessions) as db:  # type: ignore[attr-defined]
        for d in db.query(Device).filter(Device.status == "pending"):
            d.enrolment_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert c.post("/device/v1/enrol", json={"enrolment_token": token}).status_code == 401


def test_heartbeat_updates_device_and_cameras(world: World) -> None:
    c, a = world.client, world.a
    r = c.post(
        "/device/v1/heartbeat",
        json={
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "software_version": "0.2.0",
            "model_version": "rfdetr-nano-1",
            "config_version": 1,
            "cpu_pct": 41.5,
            "cameras": [
                {"camera_id": a.camera_ids[0], "status": "offline", "message": "no frames"},
                {"camera_id": world.b.camera_ids[0], "status": "offline"},  # ignored
            ],
        },
        headers=auth(a.device_token),
    )
    assert r.status_code == 200, r.text
    hb = HeartbeatResponse.model_validate(r.json())
    assert hb.config_version >= 1 and len(hb.config_etag) == 64
    owner = auth(a.owner_token)
    dev = c.get("/api/v1/devices", headers=owner).json()[0]
    assert dev["software_version"] == "0.2.0"
    assert dev["applied_config_version"] == 1
    assert dev["last_heartbeat_at"] is not None
    cam = c.get(f"/api/v1/cameras/{a.camera_ids[0]}", headers=owner).json()
    assert cam["status"] == "offline"
    other = c.get(f"/api/v1/cameras/{world.b.camera_ids[0]}", headers=auth(world.b.owner_token))
    assert other.json()["status"] == "unknown"


def test_heartbeat_rejects_naive_time(world: World) -> None:
    r = world.client.post(
        "/device/v1/heartbeat",
        json={"sent_at": "2026-11-01T09:00:00"},
        headers=auth(world.a.device_token),
    )
    assert r.status_code == 422


def test_config_etag_and_version_bump(world: World) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    r = c.get("/device/v1/config", headers=dev)
    assert r.status_code == 200
    config = SiteConfig.model_validate(r.json())  # the shared contract, validated
    etag = r.headers["ETag"]
    assert config.id == a.site_ids[0]
    assert config.cameras[0].source.startswith("rtsp://admin:secret1@")  # devices get the secret
    assert [rule.id for rule in config.rules] == [a.rule_id]
    assert r.headers["X-Config-Version"] == str(config.version)

    same = c.get("/device/v1/config", headers={**dev, "If-None-Match": etag})
    assert same.status_code == 304 and same.headers["ETag"] == etag

    # A rule change produces a new version and ETag.
    owner = auth(a.owner_token)
    rule = c.get(f"/api/v1/rules/{a.rule_id}", headers=owner).json()
    rule["threshold"] = 7
    for k in ("site_id", "created_at", "updated_at"):
        rule.pop(k)
    assert c.put(f"/api/v1/rules/{a.rule_id}", json=rule, headers=owner).status_code == 200
    changed = c.get("/device/v1/config", headers={**dev, "If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["ETag"] != etag
    new = SiteConfig.model_validate(changed.json())
    assert new.version == config.version + 1
    assert new.rules[0].threshold == 7


def test_dashboard_config_preview_is_redacted(world: World) -> None:
    r = world.client.get(
        f"/api/v1/sites/{world.a.site_ids[0]}/config", headers=auth(world.a.owner_token)
    )
    assert r.status_code == 200
    source = r.json()["cameras"][0]["source"]
    assert "secret" not in source and source.startswith("rtsp://***@10.0.0.1")


def test_revoked_device_is_locked_out(world: World) -> None:
    c, a = world.client, world.a
    r = c.post(f"/api/v1/devices/{a.device_id}/revoke", headers=auth(a.owner_token))
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert c.get("/device/v1/config", headers=auth(a.device_token)).status_code == 401
    assert c.get("/device/v1/config").status_code == 401


def test_model_release(world: World) -> None:
    c, a = world.client, world.a
    dev = auth(a.device_token)
    assert c.get("/device/v1/model-release", headers=dev).status_code == 204
    with system_session(c.app.state.vision.sessions) as db:  # type: ignore[attr-defined]
        db.add(
            ModelRelease(
                hardware_tier="standard",
                version="rfdetr-nano-2026.11",
                storage_key="models/standard/rfdetr-nano-2026.11.onnx",
                sha256="a" * 64,
                is_current=True,
            )
        )
        db.commit()
    r = c.get("/device/v1/model-release", headers=dev)
    assert r.status_code == 200
    assert r.json()["version"] == "rfdetr-nano-2026.11"
    assert "signature=" in r.json()["download_url"]


def test_log_upload_stub(world: World) -> None:
    r = world.client.post(
        "/device/v1/logs", content=b"line 1\nline 2\n", headers=auth(world.a.device_token)
    )
    assert r.status_code == 202 and r.json() == {"received_bytes": 14}
