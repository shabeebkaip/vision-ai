"""Runtime settings from environment variables (prefix VISION_) or a .env file (task REP-09)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EdgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    detector: str = "rfdetr-nano"
    """replay | rfdetr-nano | rfdetr-small | rfdetr-medium | rfdetr-large | onnx"""
    model_path: str | None = None
    detector_threshold: float = 0.35
    outbox_dir: Path = Path("var/outbox")
    clip_pre_s: float = 5.0
    clip_post_s: float = 5.0
    log_json: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
