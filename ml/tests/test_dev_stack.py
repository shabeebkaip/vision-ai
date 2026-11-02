"""Keeps the dev stack (REP-05) consistent: site config, MediaMTX paths and compose services agree."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from vision_ml.tools.synthetic import scenarios
from vision_shared.io import load_site

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _compose() -> dict[str, Any]:
    return yaml.safe_load((DEPLOY / "docker-compose.dev.yml").read_text(encoding="utf-8"))


def test_dev_site_has_four_fake_cameras_each_with_a_rule() -> None:
    site = load_site(DEPLOY / "dev" / "site.yaml")
    assert [c.id for c in site.cameras] == ["cam1", "cam2", "cam3", "cam4"]
    for cam in site.cameras:
        assert cam.source == f"rtsp://mediamtx:8554/{cam.id}"
        assert site.rules_for(cam.id), f"{cam.id} has no rule"


def test_mediamtx_serves_every_camera_path() -> None:
    cfg = yaml.safe_load((DEPLOY / "dev" / "mediamtx.yml").read_text(encoding="utf-8"))
    site = load_site(DEPLOY / "dev" / "site.yaml")
    assert set(cfg["paths"]) == {c.id for c in site.cameras}
    for name, path in cfg["paths"].items():
        assert f"${{{name.upper()}_CLIP}}" in path["runOnInit"]


def test_compose_runs_one_edge_container_per_camera() -> None:
    services = _compose()["services"]
    edge = {name: svc for name, svc in services.items() if name.startswith("edge-")}
    site = load_site(DEPLOY / "dev" / "site.yaml")
    cameras = {svc["command"][svc["command"].index("--camera") + 1] for svc in edge.values()}
    assert cameras == {c.id for c in site.cameras}


def test_default_clips_are_synthetic_scenarios() -> None:
    env = _compose()["services"]["mediamtx"]["environment"]
    known = {s.id for s in scenarios()}
    for value in env.values():
        clip = re.fullmatch(r"\$\{CAM\d_CLIP:-(.+)\.mp4\}", value)
        assert clip and clip.group(1) in known, value


def test_env_example_documents_every_compose_variable() -> None:
    compose = (DEPLOY / "docker-compose.dev.yml").read_text(encoding="utf-8")
    example = (DEPLOY.parent / ".env.example").read_text(encoding="utf-8")
    documented = {
        line.lstrip("# ").split("=", 1)[0] for line in example.splitlines() if "=" in line
    }
    used = set(re.findall(r"(?<!\$)\$\{(\w+)", compose))
    assert used <= documented, f"add to .env.example: {sorted(used - documented)}"
