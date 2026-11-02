from __future__ import annotations

from datetime import datetime, time, timezone

import pytest
from pydantic import ValidationError

from vision_shared.schemas import (
    CameraConfig,
    Event,
    Line,
    Rule,
    RuleType,
    Schedule,
    Severity,
    SiteConfig,
    Zone,
)

SQUARE = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]


def test_zone_rejects_pixel_coordinates() -> None:
    with pytest.raises(ValidationError):
        Zone(id="z", polygon=[(10, 10), (100, 10), (100, 100)])


def test_zone_needs_three_points() -> None:
    with pytest.raises(ValidationError):
        Zone(id="z", polygon=[(0.1, 0.1), (0.2, 0.2)])


def test_line_must_not_be_a_point() -> None:
    with pytest.raises(ValidationError):
        Line(id="l", start=(0.5, 0.5), end=(0.5, 0.5))


def test_zone_rule_needs_zone() -> None:
    with pytest.raises(ValidationError):
        Rule(id="r", type=RuleType.ZONE_OCCUPANCY_OVER, camera_id="c")


def test_line_rule_needs_line() -> None:
    with pytest.raises(ValidationError):
        Rule(id="r", type=RuleType.LINE_CROSSING, camera_id="c")


def test_after_hours_needs_schedule() -> None:
    with pytest.raises(ValidationError):
        Rule(id="r", type=RuleType.PRESENCE_AFTER_HOURS, camera_id="c", zone_id="z")


def test_site_checks_references() -> None:
    cam = CameraConfig(id="c", source="x.mp4", zones=[Zone(id="z", polygon=SQUARE)])
    ok = Rule(id="r", type=RuleType.ZONE_EMPTY, camera_id="c", zone_id="z")
    SiteConfig(id="s", cameras=[cam], rules=[ok])
    with pytest.raises(ValidationError):
        SiteConfig(id="s", cameras=[cam], rules=[ok.model_copy(update={"zone_id": "missing"})])
    with pytest.raises(ValidationError):
        SiteConfig(id="s", cameras=[cam], rules=[ok.model_copy(update={"camera_id": "other"})])
    with pytest.raises(ValidationError):
        SiteConfig(id="s", cameras=[cam, cam], rules=[])


def test_site_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError):
        SiteConfig(id="s", timezone="Mars/Olympus")


def _riyadh(h: int, m: int = 0, day: int = 4) -> datetime:
    # 2026-01-04 is a Sunday (ISO weekday 7); Riyadh is UTC+3 all year.
    return datetime(2026, 1, day, (h - 3) % 24, m, tzinfo=timezone.utc)


def test_schedule_daytime_window() -> None:
    s = Schedule(start=time(9, 0), end=time(18, 0))
    assert s.is_active(_riyadh(9, 0))
    assert s.is_active(_riyadh(17, 59))
    assert not s.is_active(_riyadh(8, 59))
    assert not s.is_active(_riyadh(18, 1))


def test_schedule_overnight_window_uses_start_day() -> None:
    s = Schedule(days=[7], start=time(23, 0), end=time(6, 0))  # Sunday night only
    sunday_2330 = datetime(2026, 1, 4, 20, 30, tzinfo=timezone.utc)
    monday_0300 = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    monday_2330 = datetime(2026, 1, 5, 20, 30, tzinfo=timezone.utc)
    assert s.is_active(sunday_2330)
    assert s.is_active(monday_0300)  # still Sunday night's window
    assert not s.is_active(monday_2330)


def test_schedule_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        Schedule().is_active(datetime(2026, 1, 1, 12, 0))


def test_event_requires_aware_timestamps() -> None:
    now = datetime.now(timezone.utc)
    Event(
        site_id="s",
        camera_id="c",
        rule_id="r",
        rule_type=RuleType.ZONE_EMPTY,
        severity=Severity.INFO,
        condition_started_at=now,
        triggered_at=now,
        value=0,
    )
    with pytest.raises(ValidationError):
        Event(
            site_id="s",
            camera_id="c",
            rule_id="r",
            rule_type=RuleType.ZONE_EMPTY,
            severity=Severity.INFO,
            condition_started_at=now.replace(tzinfo=None),
            triggered_at=now,
            value=0,
        )
