"""Industry rule templates (task DET-08).

A template is a ready-made rule set for one kind of site. It refers to zones and lines by *role*
("checkout_queue", "entrance") instead of id, and to schedules by keyword ("open", "closed",
"always"), so the installer only draws the zones and enters opening hours:

    rules = apply_template(load_template("restaurant"), camera_id="cam1",
                           zones={"counter_queue": "z1", "cashier": "z2"},
                           lines={"entrance": "door"},
                           opening=OpeningHours(start=time(8), end=time(23, 30)))

Rules whose zone or line role is not mapped on this camera are skipped, so one template serves
cameras that only see part of the site.
"""

from __future__ import annotations

from datetime import time
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from vision_shared.schemas import Direction, Rule, RuleType, Schedule, Severity

INDUSTRIES = ("restaurant", "retail", "clinic", "hotel", "warehouse", "factory")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleSpec(_Model):
    role: str
    name_en: str
    name_ar: str
    hint: str = Field(default="", description="where to draw it, for the installer")


class RuleSpec(_Model):
    id: str
    name_en: str
    name_ar: str
    type: RuleType
    zone_role: str | None = None
    line_role: str | None = None
    classes: list[str] = Field(default_factory=lambda: ["person"])
    threshold: int = 1
    min_duration_s: float = 0.0
    window_s: float = 60.0
    direction: Direction = Direction.ANY
    cooldown_s: float = 600.0
    clear_after_s: float = 10.0
    schedule: Literal["always", "open", "closed"] = "always"
    severity: Severity = Severity.WARNING
    verify: bool = False


class Template(_Model):
    industry: str
    name_en: str
    name_ar: str
    zones: list[RoleSpec] = Field(default_factory=list)
    lines: list[RoleSpec] = Field(default_factory=list)
    rules: list[RuleSpec]


class OpeningHours(_Model):
    days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    start: time = time(9, 0)
    end: time = time(23, 0)

    def open_schedule(self) -> Schedule:
        return Schedule(days=self.days, start=self.start, end=self.end)

    def closed_schedule(self) -> Schedule:
        # Closed = from closing time until the next opening (crosses midnight when end > start).
        return Schedule(days=[1, 2, 3, 4, 5, 6, 7], start=self.end, end=self.start)


def load_template(industry: str) -> Template:
    if industry not in INDUSTRIES:
        raise KeyError(f"unknown industry {industry!r}; choose from {', '.join(INDUSTRIES)}")
    text = (resources.files("vision_shared") / "rule_templates" / f"{industry}.yaml").read_text(
        encoding="utf-8"
    )
    return Template.model_validate(yaml.safe_load(text))


def apply_template(
    template: Template,
    camera_id: str,
    zones: dict[str, str] | None = None,
    lines: dict[str, str] | None = None,
    opening: OpeningHours | None = None,
    language: Literal["en", "ar"] = "en",
) -> list[Rule]:
    zones = zones or {}
    lines = lines or {}
    opening = opening or OpeningHours()
    rules: list[Rule] = []
    for spec in template.rules:
        zone_id = zones.get(spec.zone_role) if spec.zone_role else None
        line_id = lines.get(spec.line_role) if spec.line_role else None
        if (spec.zone_role and not zone_id) or (spec.line_role and not line_id):
            continue
        schedule = None
        if spec.schedule == "open":
            schedule = opening.open_schedule()
        elif spec.schedule == "closed":
            schedule = opening.closed_schedule()
        rules.append(
            Rule(
                id=f"{camera_id}-{spec.id}",
                name=spec.name_ar if language == "ar" else spec.name_en,
                type=spec.type,
                camera_id=camera_id,
                zone_id=zone_id,
                line_id=line_id,
                classes=spec.classes,
                threshold=spec.threshold,
                min_duration_s=spec.min_duration_s,
                window_s=spec.window_s,
                direction=spec.direction,
                cooldown_s=spec.cooldown_s,
                clear_after_s=spec.clear_after_s,
                schedule=schedule,
                severity=spec.severity,
                verify=spec.verify,
            )
        )
    return rules


def site_skeleton(
    template: Template,
    site_id: str,
    camera_id: str,
    source: str,
    opening: OpeningHours | None = None,
    timezone: str = "Asia/Riyadh",
    language: Literal["en", "ar"] = "en",
) -> dict[str, object]:
    """A starter site config with one placeholder zone per role (tiled across the frame) and the
    template's rules. The installer then reshapes the zones in the dashboard's zone editor."""
    from vision_shared.schemas import CameraConfig, Line, SiteConfig, Zone

    n = max(len(template.zones), 1)
    zones = []
    for i, role in enumerate(template.zones):
        x0 = round(0.05 + 0.9 * i / n, 3)
        x1 = round(0.05 + 0.9 * (i + 1) / n - 0.02, 3)
        zones.append(
            Zone(
                id=role.role,
                name=role.name_ar if language == "ar" else role.name_en,
                polygon=[(x0, 0.45), (x1, 0.45), (x1, 0.95), (x0, 0.95)],
            )
        )
    lines = [
        Line(id=role.role, name=role.name_ar if language == "ar" else role.name_en,
             start=(0.25, round(0.35 + 0.05 * i, 3)), end=(0.75, round(0.35 + 0.05 * i, 3)))
        for i, role in enumerate(template.lines)
    ]  # fmt: skip
    camera = CameraConfig(id=camera_id, name=camera_id, source=source, zones=zones, lines=lines)
    rules = apply_template(
        template,
        camera_id,
        zones={z.id: z.id for z in zones},
        lines={ln.id: ln.id for ln in lines},
        opening=opening,
        language=language,
    )
    site = SiteConfig(id=site_id, name=site_id, timezone=timezone, cameras=[camera], rules=rules)
    return site.model_dump(mode="json", exclude_defaults=True)
