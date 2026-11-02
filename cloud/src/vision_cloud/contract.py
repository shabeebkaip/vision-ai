"""Device <-> cloud messages that are not yet in `vision_shared`.

`Event`, `SiteConfig`, `Rule` etc. come from `vision_shared.schemas` and are used as they are. The
models below are the rest of the device API (enrolment, heartbeat, upload receipts, per-minute
aggregates, model release, log upload). They are PROPOSED for `shared/` (see
`docs/proposals/shared-device-api-schemas.md`) so EDG-12/EDG-13 can import the same types; until that
pull request lands they live here, and the field names are already the agreed contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return v


# --------------------------------------------------------------------------- enrolment


class EnrolmentRequest(_Model):
    token: str = Field(min_length=16, max_length=256, description="one-time enrolment token")
    name: str = Field(default="", max_length=200)
    hardware_tier: str | None = Field(default=None, max_length=32)
    software_version: str | None = Field(default=None, max_length=64)


class EnrolmentResponse(_Model):
    device_id: str
    site_id: str = Field(description="SiteConfig.id (site key) this box serves")
    credential: str = Field(
        description="device secret, shown once; send as `Authorization: Bearer <credential>`"
    )


# --------------------------------------------------------------------------- heartbeat


class CameraHealth(_Model):
    camera_id: str = Field(min_length=1, max_length=64)
    online: bool
    fps: float | None = Field(default=None, ge=0)
    resolution: str | None = Field(default=None, max_length=32)
    codec: str | None = Field(default=None, max_length=32)
    last_frame_at: datetime | None = None
    error: str | None = Field(default=None, max_length=500)

    _aware_ts = field_validator("last_frame_at")(_aware)


class Heartbeat(_Model):
    sent_at: datetime
    software_version: str = Field(max_length=64)
    model_version: str | None = Field(default=None, max_length=128)
    applied_config_version: int | None = Field(default=None, ge=0)
    uptime_s: float | None = Field(default=None, ge=0)
    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    gpu_percent: float | None = Field(default=None, ge=0, le=100)
    ram_percent: float | None = Field(default=None, ge=0, le=100)
    disk_percent: float | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = Field(default=None, ge=-40, le=150)
    outbox_pending: int | None = Field(default=None, ge=0)
    cameras: list[CameraHealth] = Field(default_factory=list, max_length=64)

    _aware_ts = field_validator("sent_at")(_aware)


class HeartbeatResponse(_Model):
    server_time: datetime
    config_version: int | None = Field(description="latest config version for this site")
    logs_requested: bool = False


# --------------------------------------------------------------------------- uploads


class UploadTarget(_Model):
    """A pre-signed POST form: send `fields` plus the file as the multipart field `file`."""

    method: str = "POST"
    url: str
    fields: dict[str, str]
    key: str
    expires_at: datetime
    max_bytes: int


class MediaKind(str, Enum):
    SNAPSHOT = "snapshot"
    CLIP = "clip"


class IngestStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    DUPLICATE = "duplicate"


class EventReceipt(_Model):
    event_id: str
    status: IngestStatus
    snapshot_upload: UploadTarget | None = None
    clip_upload: UploadTarget | None = None


class EventBatch(_Model):
    """Each item is a `vision_shared.schemas.Event`. Items are validated one by one so a single bad
    event is rejected on its own instead of failing the whole batch."""

    events: list[dict[str, Any]] = Field(min_length=1)


class RejectedItem(_Model):
    index: int
    id: str | None = None
    code: str
    message: str


class EventBatchReceipt(_Model):
    receipts: list[EventReceipt]
    rejected: list[RejectedItem] = Field(default_factory=list)


class MediaFinalised(_Model):
    event_id: str
    kind: MediaKind
    key: str
    size_bytes: int


# --------------------------------------------------------------------------- aggregates (EDG-10)


class AggregateMinute(_Model):
    """Counts for one camera over one minute. `minute` is the start of the minute (UTC, :00 s)."""

    camera_id: str = Field(min_length=1, max_length=64)
    minute: datetime
    occupancy_avg: float | None = Field(default=None, ge=0)
    occupancy_max: int | None = Field(default=None, ge=0)
    entries: int | None = Field(default=None, ge=0)
    exits: int | None = Field(default=None, ge=0)
    queue_length_max: int | None = Field(default=None, ge=0)
    dwell_avg_s: float | None = Field(default=None, ge=0)
    dwell_max_s: float | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="per-zone / per-line breakdown"
    )

    @field_validator("minute")
    @classmethod
    def _minute(cls, v: datetime) -> datetime:
        _aware(v)
        if v.second or v.microsecond:
            raise ValueError("minute must be the start of a minute (seconds = 0)")
        return v


class AggregateBatch(_Model):
    site_id: str = Field(min_length=1, max_length=64)
    items: list[AggregateMinute] = Field(min_length=1)


class AggregateReceipt(_Model):
    accepted: int
    rejected: list[RejectedItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- models and logs


class ModelReleaseInfo(_Model):
    id: str
    name: str
    version: str
    channel: str
    sha256: str
    size_bytes: int
    download_url: str
    expires_at: datetime


class LogUploadRequest(_Model):
    size_bytes: int = Field(gt=0)
    reason: str = Field(default="", max_length=200)


class LogUploadResponse(_Model):
    upload: UploadTarget
