"""Loading site configuration files."""

from __future__ import annotations

from pathlib import Path

import yaml

from vision_shared.schemas import SiteConfig


def load_site(path: str | Path) -> SiteConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return SiteConfig.model_validate(data)
