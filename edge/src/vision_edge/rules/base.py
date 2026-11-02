"""Rule evaluation framework (task EDG-09).

A rule watches one camera's observations and reports outcomes:
  - `Trigger` when its condition has held for `min_duration_s` (and cooldown allows),
  - `Clear` when the condition has been false for `clear_after_s` after a trigger.

The condition state machine (idle -> pending -> triggered -> idle) gives hysteresis, so one real
situation produces one alert, not one per frame.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from vision_edge.scene import Observation, ZoneObject
from vision_shared.schemas import Rule


@dataclass
class Trigger:
    rule: Rule
    key: str
    condition_started_at: datetime
    triggered_at: datetime
    value: float
    message: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Clear:
    rule: Rule
    key: str
    cleared_at: datetime
    attributes: dict[str, Any] = field(default_factory=dict)


Outcome = Trigger | Clear


def fmt_duration(seconds: float) -> str:
    s = round(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


class RuleEvaluator(ABC):
    def __init__(self, rule: Rule, timezone: str, zone_name: str = "", line_name: str = "") -> None:
        self.rule = rule
        self.timezone = timezone
        self.zone_name = zone_name or (rule.zone_id or "")
        self.line_name = line_name or (rule.line_id or "")
        self.last_trigger_at: datetime | None = None

    def schedule_active(self, ts: datetime) -> bool:
        return self.rule.schedule is None or self.rule.schedule.is_active(ts, self.timezone)

    def objects_in_zone(self, obs: Observation) -> list[ZoneObject]:
        if not self.rule.zone_id:
            return []
        return [
            o
            for o in obs.zones.get(self.rule.zone_id, [])
            if o.class_name in self.rule.classes and o.confidence >= self.rule.min_confidence
        ]

    def cooldown_ok(self, ts: datetime) -> bool:
        return (
            self.last_trigger_at is None
            or (ts - self.last_trigger_at).total_seconds() >= self.rule.cooldown_s
        )

    @abstractmethod
    def evaluate(self, obs: Observation) -> list[Outcome]: ...


class ConditionRule(RuleEvaluator):
    """Base for rules of the form "condition true for at least min_duration_s"."""

    def __init__(self, rule: Rule, timezone: str, zone_name: str = "", line_name: str = "") -> None:
        super().__init__(rule, timezone, zone_name, line_name)
        self.pending_since: datetime | None = None
        self.false_since: datetime | None = None
        self.triggered = False
        self.peak = 0.0

    @abstractmethod
    def condition(self, obs: Observation) -> tuple[bool, float, dict[str, Any]]:
        """Return (condition_true, value, attributes) for this frame."""

    @abstractmethod
    def message(self, value: float, held_s: float, attributes: dict[str, Any]) -> str: ...

    def evaluate(self, obs: Observation) -> list[Outcome]:
        ts = obs.ts
        ok, value, attrs = self.condition(obs)
        if not self.schedule_active(ts):
            ok = False
        out: list[Outcome] = []
        if ok:
            self.false_since = None
            if self.pending_since is None:
                self.pending_since = ts
                self.peak = value
            self.peak = max(self.peak, value)
            held = (ts - self.pending_since).total_seconds()
            if not self.triggered and held >= self.rule.min_duration_s and self.cooldown_ok(ts):
                self.triggered = True
                self.last_trigger_at = ts
                out.append(
                    Trigger(
                        rule=self.rule,
                        key=self.rule.id,
                        condition_started_at=self.pending_since,
                        triggered_at=ts,
                        value=value,
                        message=self.message(value, held, attrs),
                        attributes=attrs,
                    )
                )
        else:
            if self.pending_since is not None:
                if self.false_since is None:
                    self.false_since = ts
                if (ts - self.false_since).total_seconds() >= self.rule.clear_after_s:
                    if self.triggered:
                        out.append(
                            Clear(
                                rule=self.rule,
                                key=self.rule.id,
                                cleared_at=ts,
                                attributes={"peak": self.peak},
                            )
                        )
                    self.pending_since = None
                    self.false_since = None
                    self.triggered = False
                    self.peak = 0.0
        return out
