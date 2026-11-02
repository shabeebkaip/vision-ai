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

    # --- object storage (CLD-06)
    storage_backend: Literal["s3", "local"] = "s3"
    storage_bucket: str = "vision-media"
    storage_endpoint_url: str | None = Field(
        default=None, description="MinIO or other S3-compatible endpoint; empty for AWS S3"
    )
    storage_public_endpoint_url: str | None = Field(
        default=None,
        description="endpoint used in pre-signed URLs when edge boxes and browsers reach the store "
        "under another address than the API does (e.g. MinIO inside docker compose)",
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
