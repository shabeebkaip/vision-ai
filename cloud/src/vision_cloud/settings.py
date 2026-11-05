"""Cloud settings from environment variables (prefix VISION_CLOUD_) or a .env file.

Secrets (JWT key, field-encryption key, storage keys) have no defaults: the API refuses to start
without them. See `.env.example` at the repository root for every variable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_CLOUD_", env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "staging", "production"] = "dev"
    database_url: str = Field(
        default="postgresql+psycopg://vision:vision@localhost:5432/vision",
        description="SQLAlchemy URL. The API should connect as a role without BYPASSRLS.",
    )
    database_echo: bool = False

    # --- auth (CLD-03)
    jwt_secret: SecretStr = Field(description="HS256 signing key, at least 32 random bytes")
    jwt_issuer: str = "codeox-vision"
    access_token_ttl_s: int = Field(default=900, gt=0)
    refresh_token_ttl_s: int = Field(default=30 * 24 * 3600, gt=0)
    invitation_ttl_s: int = Field(default=7 * 24 * 3600, gt=0)
    enrolment_token_ttl_s: int = Field(default=24 * 3600, gt=0)

    # --- encryption of camera stream URLs at rest (Fernet key, urlsafe base64 of 32 bytes)
    field_encryption_key: SecretStr

    # --- background jobs (CLD-17)
    redis_url: str | None = Field(
        default=None, description="redis://host:6379/0. Unset: jobs are only logged (no worker)."
    )
    job_max_retries: int = Field(default=3, ge=0, le=10)
    job_retry_intervals_s: list[int] = Field(default_factory=lambda: [10, 60, 300])
    job_dead_letter_ttl_days: float = Field(default=30, gt=0)
    job_timeout_s: int = Field(default=120, gt=0)

    # --- alert dispatch (CLD-08)
    alert_group_window_s: float = Field(
        default=120, gt=0, description="events of one camera and rule this close form one alert"
    )
    alert_escalation_after_s: float = Field(
        default=600, gt=0, description="an unacknowledged alert goes to the next rank after this"
    )
    alert_escalate_severities: list[str] = Field(default_factory=lambda: ["critical"])
    alert_dry_run: bool = Field(
        default=True,
        description="log alerts instead of sending them; set false once channels are configured",
    )

    alert_media_wait_s: float = Field(
        default=20,
        ge=0,
        description="wait this long for the event's snapshot before sending an alert without it",
    )

    # --- Telegram channel (CLD-10)
    telegram_bot_token: SecretStr | None = Field(default=None, description="from @BotFather")
    telegram_bot_username: str | None = Field(
        default=None, description="the bot's @name without @, for t.me link codes"
    )
    telegram_webhook_secret: SecretStr | None = Field(
        default=None, description="Telegram sends it in X-Telegram-Bot-Api-Secret-Token"
    )
    telegram_api_base: str = "https://api.telegram.org"
    telegram_link_ttl_s: int = Field(default=24 * 3600, gt=0)

    # --- object storage (CLD-06)
    storage_backend: Literal["s3", "local"] = "s3"
    storage_bucket: str = "vision-media"
    storage_endpoint_url: str | None = Field(
        default=None, description="S3-compatible endpoint (SeaweedFS in dev); empty for AWS S3"
    )
    storage_public_endpoint_url: str | None = Field(
        default=None,
        description="endpoint used in pre-signed URLs when edge boxes and browsers reach the store "
        "under another address than the API does (e.g. storage inside docker compose)",
    )
    storage_device_endpoint_url: str | None = Field(
        default=None,
        description="endpoint in the upload URLs given to edge boxes, when they reach the store "
        "under another address than browsers do (local dev stack); default: the public one",
    )
    storage_region: str = "us-east-1"
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    storage_sse: str | None = Field(
        default=None, description="server-side encryption header value, e.g. AES256"
    )
    storage_local_dir: Path = Path("var/cloud-storage")
    upload_url_ttl_s: int = Field(default=900, gt=0)
    view_url_ttl_s: int = Field(default=300, gt=0)
    max_snapshot_bytes: int = 2 * 1024 * 1024
    max_clip_bytes: int = 50 * 1024 * 1024

    # --- API
    public_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=list)
    max_events_per_batch: int = 500
    max_aggregates_per_batch: int = 5000
    max_log_upload_bytes: int = 5 * 1024 * 1024
    log_json: bool = True
