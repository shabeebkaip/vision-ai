"""Shared contract between edge, cloud and dashboard.

All geometry in configuration is normalised to 0..1 (x to the right, y downwards) so a zone drawn on a
snapshot survives a change of stream resolution. The edge converts to pixels per frame size.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

Point = tuple[float, float]


def _check_point(p: Point) -> Point:
    x, y = p
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"point {p} must be normalised to 0..1")
    return (float(x), float(y))


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


# --------------------------------------------------------------------------- geometry


class Zone(_Model):
    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    polygon: list[Point] = Field(min_length=3)

    @field_validator("polygon")
    @classmethod
    def _normalised(cls, v: list[Point]) -> list[Point]:
        return [_check_point(p) for p in v]


class Line(_Model):
    """A counting line. "in" means crossing from the left side to the right side when walking
    from `start` to `end` (the dashboard draws an arrow to show it)."""

    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    start: Point
    end: Point

    @field_validator("start", "end")
    @classmethod
    def _normalised(cls, v: Point) -> Point:
        return _check_point(v)

    @model_validator(mode="after")
    def _not_degenerate(self) -> Line:
        if self.start == self.end:
            raise ValueError("line start and end must differ")
        return self


# --------------------------------------------------------------------------- schedules


class Schedule(_Model):
    """Active window in the site's local time. `start > end` means the window crosses midnight
    (e.g. 23:00 to 06:00). `days` are ISO weekdays of the window's start: 1=Monday .. 7=Sunday."""

    days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    start: time = time(0, 0)
    end: time = time(23, 59, 59)

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if not v or any(d < 1 or d > 7 for d in v):
            raise ValueError("days must be ISO weekdays 1..7")
        return sorted(set(v))

    def is_active(self, at: datetime, tz: str = "Asia/Riyadh") -> bool:
        if at.tzinfo is None:
            raise ValueError("schedule checks need a timezone-aware datetime")
        local = at.astimezone(ZoneInfo(tz))
        t = local.time()
        if self.start <= self.end:
            return local.isoweekday() in self.days and self.start <= t <= self.end
        # Overnight window: the part after midnight belongs to the previous day's window.
        if t >= self.start:
            return local.isoweekday() in self.days
        if t <= self.end:
            previous_day = (local.isoweekday() - 2) % 7 + 1
            return previous_day in self.days
        return False


# --------------------------------------------------------------------------- rules


class RuleType(str, Enum):
    ZONE_OCCUPANCY_OVER = "zone_occupancy_over"
    ZONE_EMPTY = "zone_empty"
    QUEUE_LENGTH_OVER = "queue_length_over"
    DWELL_OVER = "dwell_over"
    LINE_CROSSING = "line_crossing"
    PRESENCE_AFTER_HOURS = "presence_after_hours"


ZONE_RULES = {
    RuleType.ZONE_OCCUPANCY_OVER,
    RuleType.ZONE_EMPTY,
    RuleType.QUEUE_LENGTH_OVER,
    RuleType.DWELL_OVER,
    RuleType.PRESENCE_AFTER_HOURS,
}


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Direction(str, Enum):
    IN = "in"
    OUT = "out"
    ANY = "any"


class Rule(_Model):
    """One alert rule on one camera.

    Meaning of `threshold` and `min_duration_s` per type:
      zone_occupancy_over / queue_length_over: more than `threshold` objects in the zone for
          at least `min_duration_s`.
      zone_empty: no object in the zone for at least `min_duration_s` (threshold unused).
      dwell_over: any single object stays in the zone longer than `min_duration_s`.
      line_crossing: at least `threshold` crossings in `direction` within `window_s`.
      presence_after_hours: at least `threshold` objects in the zone for `min_duration_s` while
          the schedule (the after-hours window) is active.
    """

    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    type: RuleType
    camera_id: str = Field(min_length=1)
    zone_id: str | None = None
    line_id: str | None = None
    classes: list[str] = Field(default_factory=lambda: ["person"], min_length=1)
    threshold: int = Field(default=1, ge=0)
    min_duration_s: float = Field(default=0.0, ge=0)
    window_s: float = Field(default=60.0, gt=0)
    direction: Direction = Direction.ANY
    clear_after_s: float = Field(default=10.0, ge=0)
    cooldown_s: float = Field(default=300.0, ge=0)
    min_confidence: float = Field(default=0.4, ge=0, le=1)
    schedule: Schedule | None = None
    severity: Severity = Severity.WARNING
    verify: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def _targets(self) -> Rule:
        if self.type in ZONE_RULES and not self.zone_id:
            raise ValueError(f"rule type {self.type.value} needs zone_id")
        if self.type is RuleType.LINE_CROSSING and not self.line_id:
            raise ValueError("line_crossing needs line_id")
        if self.type is RuleType.PRESENCE_AFTER_HOURS and self.schedule is None:
            raise ValueError("presence_after_hours needs a schedule (the after-hours window)")
        return self


# --------------------------------------------------------------------------- sites and cameras


class CameraConfig(_Model):
    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    source: str = Field(min_length=1, description="rtsp:// URL, file path, or replay JSONL")
    fps: float = Field(default=5.0, gt=0, le=30)
    zones: list[Zone] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    enabled: bool = True

    @model_validator(mode="after")
    def _unique_ids(self) -> CameraConfig:
        ids = [z.id for z in self.zones] + [ln.id for ln in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError(f"camera {self.id}: zone and line ids must be unique")
        return self

    def zone(self, zone_id: str) -> Zone:
        for z in self.zones:
            if z.id == zone_id:
                return z
        raise KeyError(zone_id)

    def line(self, line_id: str) -> Line:
        for ln in self.lines:
            if ln.id == line_id:
                return ln
        raise KeyError(line_id)


class SiteConfig(_Model):
    id: str = Field(min_length=1, max_length=64)
    name: str = ""
    timezone: str = "Asia/Riyadh"
    version: int = 1
    events_only: bool = Field(
        default=False, description="sensitive sites: upload events without snapshots or clips"
    )
    cameras: list[CameraConfig] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (KeyError, ValueError) as exc:  # ZoneInfoNotFoundError is a KeyError
            raise ValueError(f"unknown timezone {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _references(self) -> SiteConfig:
        cams = {c.id: c for c in self.cameras}
        if len(cams) != len(self.cameras):
            raise ValueError("camera ids must be unique")
        rule_ids = [r.id for r in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule ids must be unique")
        for r in self.rules:
            cam = cams.get(r.camera_id)
            if cam is None:
                raise ValueError(f"rule {r.id}: unknown camera {r.camera_id}")
            if r.zone_id and r.zone_id not in {z.id for z in cam.zones}:
                raise ValueError(f"rule {r.id}: camera {cam.id} has no zone {r.zone_id}")
            if r.line_id and r.line_id not in {ln.id for ln in cam.lines}:
                raise ValueError(f"rule {r.id}: camera {cam.id} has no line {r.line_id}")
        return self

    def camera(self, camera_id: str) -> CameraConfig:
        for c in self.cameras:
            if c.id == camera_id:
                return c
        raise KeyError(camera_id)

    def rules_for(self, camera_id: str) -> list[Rule]:
        return [r for r in self.rules if r.camera_id == camera_id and r.enabled]


# --------------------------------------------------------------------------- runtime objects


class Detection(_Model):
    """One detected object in pixel coordinates (x1, y1, x2, y2) of the analysed frame."""

    class_name: str
    confidence: float = Field(ge=0, le=1)
    box: tuple[float, float, float, float]
    track_id: int | None = None


class EventState(str, Enum):
    TRIGGERED = "triggered"
    CLEARED = "cleared"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Event(_Model):
    schema_version: str = SCHEMA_VERSION
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    site_id: str
    camera_id: str
    rule_id: str
    rule_type: RuleType
    severity: Severity
    state: EventState = EventState.TRIGGERED
    condition_started_at: datetime
    triggered_at: datetime
    cleared_at: datetime | None = None
    value: float = Field(description="count, seconds of dwell, or number of crossings")
    message: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    snapshot_key: str | None = None
    clip_key: str | None = None
    needs_verification: bool = False
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("condition_started_at", "triggered_at", "cleared_at", "created_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return v
