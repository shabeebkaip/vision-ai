"""CLD-04: an edge box enrols, heartbeats and pulls config."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import add_user, auth, enrol_device, login, make_tenant
from vision_cloud import models as m
from vision_cloud.db import system_session
from vision_shared.schemas import SiteConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bearer(cred: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {cred}"}


def test_enrolment_via_admin_token(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    add_user(sessions, a, "ops@code-ox.test", "", platform_admin=True)
    admin = auth(login(client, "ops@code-ox.test"))
    r = client.post(
        "/api/v1/admin/enrolment-tokens",
        json={"organisation_id": str(a.org_id), "site_id": str(a.site_id), "device_name": "box-1"},
        headers=admin,
    )
    assert r.status_code == 201
    token = r.json()["token"]

    body = {"token": token, "hardware_tier": "jetson_orin_nano", "software_version": "0.1.0"}
    r = client.post("/device/v1/enrol", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["site_id"] == "demo-restaurant" and data["credential"].startswith("dev_")
    # The token is single use.
    assert client.post("/device/v1/enrol", json=body).status_code == 401

    devices = client.get("/api/v1/admin/devices", headers=admin).json()
    assert devices[0]["name"] == "box-1"
    owner = auth(login(client, a.owner_email))
    assert len(client.get(f"/api/v1/orgs/{a.org_id}/devices", headers=owner).json()) == 1


def test_wrong_org_site_pair_is_refused(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    b = make_tenant(sessions, "org-b")
    add_user(sessions, a, "ops@code-ox.test", "", platform_admin=True)
    admin = auth(login(client, "ops@code-ox.test"))
    r = client.post(
        "/api/v1/admin/enrolment-tokens",
        json={"organisation_id": str(a.org_id), "site_id": str(b.site_id)},
        headers=admin,
    )
    assert r.status_code == 404


def test_heartbeat_updates_device_and_cameras(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    client.get("/device/v1/config", headers=_bearer(cred))
    hb = {
        "sent_at": _now(),
        "software_version": "0.2.0",
        "model_version": "rfdetr-nano-2026.10",
        "applied_config_version": 1,
        "cpu_percent": 41.5,
        "temperature_c": 63,
        "cameras": [
            {
                "camera_id": "counter",
                "online": True,
                "fps": 5.0,
                "resolution": "1920x1080",
                "last_frame_at": _now(),
            },
            {"camera_id": "deleted-in-cloud", "online": False},
        ],
    }
    r = client.post("/device/v1/heartbeat", json=hb, headers=_bearer(cred))
    assert r.status_code == 200, r.text
    assert r.json()["config_version"] == 1 and r.json()["logs_requested"] is False
    with system_session(sessions) as db:
        device = db.query(m.Device).one()
        cam = db.query(m.Camera).one()
    assert device.software_version == "0.2.0" and device.applied_config_version == 1
    assert device.last_heartbeat and device.last_heartbeat["cpu_percent"] == 41.5
    assert cam.status is m.CameraStatus.ONLINE and cam.resolution == "1920x1080"


def test_bad_credentials(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    assert client.get("/device/v1/config").status_code == 401
    assert client.get("/device/v1/config", headers=_bearer("dev_nope")).status_code == 401
    # A user's access token is not a device credential.
    user = auth(login(client, a.owner_email))
    assert client.get("/device/v1/config", headers=user).status_code == 401


def test_config_etag_and_change(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    r = client.get("/device/v1/config", headers=_bearer(cred))
    assert r.status_code == 200
    config = SiteConfig.model_validate(r.json())  # the edge can load what we serve
    assert config.version == 1 and config.cameras[0].source == "rtsp://mediamtx:8554/counter"
    etag = r.headers["etag"]

    r = client.get("/device/v1/config", headers={**_bearer(cred), "If-None-Match": etag})
    assert r.status_code == 304

    with system_session(sessions) as db:
        rule = db.query(m.Rule).filter(m.Rule.key == "queue").one()
        rule.threshold = 7
        db.commit()
    r = client.get("/device/v1/config", headers={**_bearer(cred), "If-None-Match": etag})
    assert r.status_code == 200 and r.headers["etag"] != etag
    config = SiteConfig.model_validate(r.json())
    assert config.version == 2
    assert next(rl for rl in config.rules if rl.id == "queue").threshold == 7


def test_revoked_device_is_locked_out(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    add_user(sessions, a, "ops@code-ox.test", "", platform_admin=True)
    admin = auth(login(client, "ops@code-ox.test"))
    with system_session(sessions) as db:
        device_id = db.query(m.Device).one().id
    assert (
        client.post(f"/api/v1/admin/devices/{device_id}/revoke", headers=admin).status_code == 204
    )
    assert client.get("/device/v1/config", headers=_bearer(cred)).status_code == 401


def test_model_release(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    assert client.get("/device/v1/model-release", headers=_bearer(cred)).status_code == 204
    add_user(sessions, a, "ops@code-ox.test", "", platform_admin=True)
    admin = auth(login(client, "ops@code-ox.test"))
    release = {
        "name": "rfdetr-nano-person",
        "version": "2026.11.0",
        "channel": "stable",
        "file_key": "models/rfdetr-nano-person/2026.11.0/model.onnx",
        "sha256": "a" * 64,
        "size_bytes": 1234,
    }
    assert (
        client.post("/api/v1/admin/model-releases", json=release, headers=admin).status_code == 201
    )
    r = client.get("/device/v1/model-release", headers=_bearer(cred))
    assert r.status_code == 200
    info: dict[str, Any] = r.json()
    assert info["version"] == "2026.11.0" and info["download_url"].startswith("memory://")
    r = client.get(
        "/device/v1/model-release", headers={**_bearer(cred), "If-None-Match": r.headers["etag"]}
    )
    assert r.status_code == 304
    canary = {**release, "version": "2026.12.0-rc1", "channel": "canary"}
    client.post("/api/v1/admin/model-releases", json=canary, headers=admin)
    assert (
        client.get("/device/v1/model-release", headers=_bearer(cred)).json()["version"]
        == "2026.11.0"
    )


def test_log_upload_on_request(client: TestClient, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    add_user(sessions, a, "ops@code-ox.test", "", platform_admin=True)
    admin = auth(login(client, "ops@code-ox.test"))
    with system_session(sessions) as db:
        device_id = db.query(m.Device).one().id
    client.post(f"/api/v1/admin/devices/{device_id}/request-logs", headers=admin)
    hb = {"sent_at": _now(), "software_version": "0.2.0"}
    assert client.post("/device/v1/heartbeat", json=hb, headers=_bearer(cred)).json()[
        "logs_requested"
    ]
    r = client.post("/device/v1/logs", json={"size_bytes": 4096}, headers=_bearer(cred))
    assert r.status_code == 201
    assert f"/devices/{device_id}/logs/" in r.json()["upload"]["key"]
    assert not client.post("/device/v1/heartbeat", json=hb, headers=_bearer(cred)).json()[
        "logs_requested"
    ]
    r = client.post("/device/v1/logs", json={"size_bytes": 10**9}, headers=_bearer(cred))
    assert r.status_code == 413


def test_device_rate_limit(client: TestClient, app: Any, sessions: sessionmaker[Session]) -> None:
    a = make_tenant(sessions, "org-a")
    cred = enrol_device(client, sessions, a)
    original = app.state.settings
    app.state.settings = original.model_copy(
        update={"device_rate_limit_per_min": 1, "device_rate_limit_burst": 5}
    )
    try:
        codes = [
            client.get("/device/v1/model-release", headers=_bearer(cred)).status_code
            for _ in range(6)
        ]
    finally:
        app.state.settings = original
    assert codes[:5] == [204] * 5
    assert codes[5] == 429
