from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from vision_shared.schemas import RuleType, SiteConfig
from vision_shared.templates import (
    INDUSTRIES,
    OpeningHours,
    apply_template,
    load_template,
    site_skeleton,
)


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_every_template_builds_valid_rules(industry: str) -> None:
    t = load_template(industry)
    zones = {r.role: f"z-{r.role}" for r in t.zones}
    lines = {r.role: f"l-{r.role}" for r in t.lines}
    rules = apply_template(t, "cam", zones, lines)
    assert len(rules) == len(t.rules)
    for spec in t.rules:
        assert spec.name_ar and spec.name_en
        assert spec.zone_role is None or spec.zone_role in zones, spec.id
        assert spec.line_role is None or spec.line_role in lines, spec.id


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_skeleton_is_a_valid_site(industry: str) -> None:
    data = site_skeleton(load_template(industry), "s", "cam1", "rtsp://x", language="ar")
    site = SiteConfig.model_validate(data)
    assert site.rules and site.cameras[0].zones


def test_rules_for_unmapped_roles_are_skipped() -> None:
    rules = apply_template(load_template("restaurant"), "cam", zones={"cashier": "z1"})
    assert [r.type for r in rules] == [RuleType.ZONE_EMPTY]
    assert rules[0].zone_id == "z1"
    assert rules[0].id == "cam-cashier-unattended"


def test_open_and_closed_schedules_from_opening_hours() -> None:
    opening = OpeningHours(start=time(8, 0), end=time(2, 0))  # open 08:00 to 02:00 next day
    rules = apply_template(
        load_template("restaurant"), "cam", zones={"kitchen": "k", "cashier": "c"}, opening=opening
    )
    by_type = {r.type: r for r in rules}
    closed = by_type[RuleType.PRESENCE_AFTER_HOURS].schedule
    opened = by_type[RuleType.ZONE_EMPTY].schedule
    assert closed is not None and opened is not None
    riyadh_0300 = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    riyadh_2300 = datetime(2026, 1, 4, 20, 0, tzinfo=timezone.utc)
    assert closed.is_active(riyadh_0300) and not closed.is_active(riyadh_2300)
    assert opened.is_active(riyadh_2300) and not opened.is_active(riyadh_0300)


def test_arabic_names() -> None:
    [rule] = apply_template(
        load_template("restaurant"), "cam", zones={"cashier": "z"}, language="ar"
    )
    assert rule.name == "الكاشير بدون موظف"


def test_unknown_industry() -> None:
    with pytest.raises(KeyError):
        load_template("bakery")
