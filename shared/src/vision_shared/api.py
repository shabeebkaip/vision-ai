"""Device <-> cloud API payloads (CLD-04, CLD-05; consumed by the edge agent EDG-12/EDG-13).

The event itself is the shared `Event` and the configuration is the shared `SiteConfig`
(`vision_shared.schemas`); this module only adds the envelopes around them.

Requests forbid unknown fields (catch typos early). Responses ignore unknown fields, so a newer
cloud can add fields without breaking older edge boxes in the field.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vision_shared.schemas import Event


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return v


# --------------------------------------------------------------------------- enrolment


class EnrolmentRequest(_Request):
    enrolment_token: str = Field(min_length=16, max_length=256)
    hardware_tier: str | None = Field(default=None, max_length=32)
    software_version: str | None = Field(default=None, max_length=64)
    hostname: str = Field(default="", max_length=200)


class EnrolmentResponse(_Response):
    device_id: str
    organisation_id: str
    site_id: str
    device_token: str = Field(
        description="long-lived credential; send as `Authorization: Bearer <token>`. Shown once."
    )


# --------------------------------------------------------------------------- heartbeat


class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class CameraHealth(_Request):
    camera_id: str = Field(min_length=1, max_length=64)
    status: CameraStatus
    fps: float | None = Field(default=None, ge=0)
    last_frame_at: datetime | None = None
    message: str = Field(default="", max_length=500)

    @field_validator("last_frame_at")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        return _aware(v)


class Heartbeat(_Request):
    sent_at: datetime
    software_version: str | None = Field(default=None, max_length=64)
    model_version: str | None = Field(default=None, max_length=64)
    config_version: int | None = Field(default=None, ge=0, description="config applied on the box")
    uptime_s: float | None = Field(default=None, ge=0)
    cpu_pct: float | None = Field(default=None, ge=0, le=100)
    gpu_pct: float | None = Field(default=None, ge=0, le=100)
    ram_pct: float | None = Field(default=None, ge=0, le=100)
    disk_free_pct: float | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = None
    outbox_pending: int | None = Field(default=None, ge=0)
    cameras: list[CameraHealth] = Field(default_factory=list, max_length=64)

    @field_validator("sent_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        _aware(v)
        return v


class HeartbeatResponse(_Response):
    server_time: datetime
    config_version: int
    config_etag: str
    model_version: str | None = None


# --------------------------------------------------------------------------- events and media


class MediaKind(str, Enum):
    SNAPSHOT = "snapshot"
    CLIP = "clip"


class UploadRequest(_Request):
    kinds: list[MediaKind] = Field(min_length=1, max_length=2)


class UploadTarget(_Response):
    kind: MediaKind
    key: str
    url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class UploadResponse(_Response):
    event_id: str
    uploads: list[UploadTarget]


class FinaliseRequest(_Request):
    """Sent after the PUTs: which media were uploaded. The cloud checks they exist."""

    snapshot: bool = False
    clip: bool = False


class IngestStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"  # e.g. the "cleared" version of an event already received
    UNCHANGED = "unchanged"  # duplicate submission
    REJECTED = "rejected"


class EventIngestResult(_Response):
    event_id: str
    status: IngestStatus
    error: str | None = None


class EventBatch(_Request):
    events: list[Event] = Field(min_length=1)


class EventBatchResult(_Response):
    results: list[EventIngestResult]


class EventMediaState(_Response):
    event_id: str
    snapshot_key: str | None = None
    clip_key: str | None = None


# --------------------------------------------------------------------------- aggregates


class AggregateMetric(str, Enum):
    OCCUPANCY = "occupancy"  # mean objects in the zone/frame during the minute
    OCCUPANCY_MAX = "occupancy_max"
    COUNT_IN = "count_in"
    COUNT_OUT = "count_out"
    QUEUE_LENGTH = "queue_length"
    DWELL_S = "dwell_s"


class AggregateRow(_Request):
    camera_id: str = Field(min_length=1, max_length=64)
    minute: datetime = Field(description="start of the UTC minute (seconds must be zero)")
    metric: AggregateMetric
    target: str = Field(default="", max_length=64, description="zone or line id; empty = camera")
    value: float

    @field_validator("minute")
    @classmethod
    def _whole_minute(cls, v: datetime) -> datetime:
        _aware(v)
        if v.second or v.microsecond:
            raise ValueError("minute must be truncated to the minute")
        return v


class AggregateBatch(_Request):
    rows: list[AggregateRow] = Field(min_length=1)


class AggregateBatchResult(_Response):
    accepted: int


# --------------------------------------------------------------------------- models


class ModelReleaseInfo(_Response):
    version: str
    hardware_tier: str
    sha256: str
    download_url: str
    expires_at: datetime
