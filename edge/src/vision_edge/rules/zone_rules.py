"""Zone-based MVP rule types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from vision_edge.rules.base import (
    Clear,
    ConditionRule,
    Outcome,
    RuleEvaluator,
    Trigger,
    fmt_duration,
)
from vision_edge.scene import Observation


def _noun(classes: list[str], n: float) -> str:
    base = "people" if classes == ["person"] else "objects"
    if classes == ["person"] and int(n) == 1:
        return "person"
    return base


class ZoneOccupancyOver(ConditionRule):
    """More than `threshold` objects in the zone for at least `min_duration_s`."""

    def condition(self, obs: Observation) -> tuple[bool, float, dict[str, Any]]:
        n = len(self.objects_in_zone(obs))
        return n > self.rule.threshold, float(n), {"count": n}

    def message(self, value: float, held_s: float, attributes: dict[str, Any]) -> str:
        return (
            f"{int(value)} {_noun(self.rule.classes, value)} in '{self.zone_name}' "
            f"for {fmt_duration(held_s)} (limit {self.rule.threshold})"
        )


class QueueLengthOver(ConditionRule):
    """Queue zone holds more than `threshold` people; reports estimated wait from recent dwell."""

    def condition(self, obs: Observation) -> tuple[bool, float, dict[str, Any]]:
        objs = self.objects_in_zone(obs)
        n = len(objs)
        waits = [o.dwell_s for o in objs if o.track_id is not None]
        attrs: dict[str, Any] = {"count": n}
        if waits:
            attrs["longest_wait_s"] = round(max(waits), 1)
        return n > self.rule.threshold, float(n), attrs

    def message(self, value: float, held_s: float, attributes: dict[str, Any]) -> str:
        longest = attributes.get("longest_wait_s")
        extra = f", longest wait {fmt_duration(longest)}" if longest else ""
        return (
            f"Queue of {int(value)} in '{self.zone_name}' for {fmt_duration(held_s)}"
            f" (limit {self.rule.threshold}){extra}"
        )


class ZoneEmpty(ConditionRule):
    """Nobody in the zone for at least `min_duration_s` while the schedule is active."""

    def condition(self, obs: Observation) -> tuple[bool, float, dict[str, Any]]:
        n = len(self.objects_in_zone(obs))
        return n == 0, 0.0, {"count": n}

    def message(self, value: float, held_s: float, attributes: dict[str, Any]) -> str:
        return f"'{self.zone_name}' unattended for {fmt_duration(held_s)}"


class PresenceAfterHours(ConditionRule):
    """At least `threshold` objects (default 1) in the zone during the after-hours schedule."""

    def condition(self, obs: Observation) -> tuple[bool, float, dict[str, Any]]:
        n = len(self.objects_in_zone(obs))
        return n >= max(self.rule.threshold, 1), float(n), {"count": n}

    def message(self, value: float, held_s: float, attributes: dict[str, Any]) -> str:
        return (
            f"{int(value)} {_noun(self.rule.classes, value)} in '{self.zone_name}' outside "
            f"opening hours ({fmt_duration(held_s)})"
        )


class DwellOver(RuleEvaluator):
    """Any single tracked object stays in the zone longer than `min_duration_s`.

    Fires once per object visit; clears when that object leaves the zone.
    """

    def __init__(self, rule: Any, timezone: str, zone_name: str = "", line_name: str = "") -> None:
        super().__init__(rule, timezone, zone_name, line_name)
        self.alerted: set[int] = set()

    def evaluate(self, obs: Observation) -> list[Outcome]:
        out: list[Outcome] = []
        present: set[int] = set()
        active = self.schedule_active(obs.ts)
        for o in self.objects_in_zone(obs):
            if o.track_id is None:
                continue
            present.add(o.track_id)
            if (
                active
                and o.track_id not in self.alerted
                and o.dwell_s >= self.rule.min_duration_s
                and self.cooldown_ok(obs.ts)
            ):
                self.alerted.add(o.track_id)
                self.last_trigger_at = obs.ts
                started = obs.ts.timestamp() - o.dwell_s
                out.append(
                    Trigger(
                        rule=self.rule,
                        key=f"{self.rule.id}:{o.track_id}",
                        condition_started_at=datetime.fromtimestamp(started, tz=obs.ts.tzinfo),
                        triggered_at=obs.ts,
                        value=round(o.dwell_s, 1),
                        message=(
                            f"{'Person' if o.class_name == 'person' else o.class_name.capitalize()} "
                            f"in '{self.zone_name}' for {fmt_duration(o.dwell_s)} "
                            f"(limit {fmt_duration(self.rule.min_duration_s)})"
                        ),
                        attributes={"track": o.track_id, "class": o.class_name},
                    )
                )
        for tid in list(self.alerted):
            if tid not in present:
                self.alerted.discard(tid)
                dwell = next(
                    (
                        d.dwell_s
                        for d in obs.departures.get(self.rule.zone_id or "", [])
                        if d.track_id == tid
                    ),
                    None,
                )
                out.append(
                    Clear(
                        rule=self.rule,
                        key=f"{self.rule.id}:{tid}",
                        cleared_at=obs.ts,
                        attributes={"dwell_s": dwell} if dwell is not None else {},
                    )
                )
        return out
