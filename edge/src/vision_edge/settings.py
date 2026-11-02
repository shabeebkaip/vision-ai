"""Runtime settings from environment variables (prefix VISION_) or a .env file (task REP-09)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
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

    # Cloud upload (EDG-12). The uploader runs when both are set; the device token comes from
    # enrolment (EDG-13). Until then, create a device in the cloud and set it here.
    cloud_url: str | None = None
    """e.g. https://api.vision.code-ox.com (the device API lives under /device/v1)"""
    device_token: SecretStr | None = None
    upload_batch_size: int = Field(default=100, ge=1, le=500)
    outbox_clip_quota_mb: int = Field(default=2048, ge=0)
    """oldest clips are deleted beyond this; events are never dropped"""
    outbox_retention_days: float = Field(default=7.0, gt=0)
    """delivered events and media are forgotten after this"""
