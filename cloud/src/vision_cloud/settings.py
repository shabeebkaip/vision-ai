"""Cloud settings from environment variables (prefix VISION_) or a .env file (REP-09 convention).

A missing or invalid setting stops the service at start-up with a readable message.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    # --- database -------------------------------------------------------------------------
    database_url: str = Field(
        description="SQLAlchemy URL, e.g. postgresql+psycopg://vision:***@localhost:5432/vision. "
        "The role must not be a superuser or have BYPASSRLS: row-level security is our second lock."
    )

    # --- secrets --------------------------------------------------------------------------
    jwt_secret: SecretStr = Field(min_length=32, description="HMAC key for access tokens")
    encryption_key: SecretStr = Field(
        description="Fernet key (urlsafe base64, 32 bytes) for stream URLs and 2FA secrets. "
        "Generate with: vision-cloud gen-key"
    )

    # --- tokens and lifetimes (seconds) ---------------------------------------------------
    access_token_ttl_s: int = 15 * 60
    refresh_token_ttl_s: int = 30 * 24 * 3600
    invitation_ttl_s: int = 7 * 24 * 3600
    password_reset_ttl_s: int = 3600
    enrolment_token_ttl_s: int = 24 * 3600
    jwt_issuer: str = "codeox-vision"

    # --- object storage (S3-compatible: MinIO in dev, in-Kingdom S3 in production) ---------
    storage_backend: Literal["s3", "memory"] = "s3"
    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = Field(
        default=None, description="host edge boxes use for pre-signed URLs, if different"
    )
    s3_region: str = "us-east-1"
    s3_bucket: str = "vision-media"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_server_side_encryption: str | None = "AES256"
    upload_url_ttl_s: int = 15 * 60
    download_url_ttl_s: int = 5 * 60
    max_snapshot_bytes: int = 2 * 1024 * 1024
    max_clip_bytes: int = 50 * 1024 * 1024
    max_log_bytes: int = 20 * 1024 * 1024

    # --- device ingest --------------------------------------------------------------------
    redis_url: str | None = Field(
        default=None, description="Redis for rate limits; in-process limiter when unset (dev)"
    )
    device_rate_limit_per_min: int = Field(default=600, gt=0)
    device_rate_limit_burst: int = Field(default=120, gt=0)
    max_batch_events: int = Field(default=500, gt=0)
    max_batch_aggregates: int = Field(default=2000, gt=0)

    # --- mail -----------------------------------------------------------------------------
    mail_backend: Literal["console", "smtp", "memory"] = "console"
    mail_from: str = "Code-Ox Vision <no-reply@vision.code-ox.com>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    public_web_url: str = "http://localhost:5173"

    # --- http -----------------------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=list)
    log_json: bool = False
    environment: Literal["dev", "test", "staging", "production"] = "dev"


class SettingsError(SystemExit):
    pass


@lru_cache(maxsize=1)
def get_settings() -> CloudSettings:
    try:
        return CloudSettings()
    except ValidationError as exc:
        lines = ["Cloud settings are missing or invalid:"]
        for err in exc.errors():
            name = "VISION_" + "_".join(str(p) for p in err["loc"]).upper()
            lines.append(f"  {name}: {err['msg']}")
        lines.append("See cloud/.env.example for every setting.")
        raise SettingsError("\n".join(lines)) from None
