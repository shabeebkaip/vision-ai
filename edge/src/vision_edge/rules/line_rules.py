"""Line-crossing rule type."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from vision_edge.rules.base import Outcome, RuleEvaluator, Trigger, fmt_duration
from vision_edge.scene import Observation
from vision_shared.schemas import Direction


class LineCrossing(RuleEvaluator):
    """At least `threshold` crossings in `direction` within a sliding `window_s`.

    With threshold 1 this is "anyone crosses into a restricted side". Counting resets after each
    trigger, so a steady flow produces one alert per window, subject to the cooldown.
    """

    def __init__(self, rule: Any, timezone: str, zone_name: str = "", line_name: str = "") -> None:
        super().__init__(rule, timezone, zone_name, line_name)
        self.crossings: deque[datetime] = deque()
        self.total_in = 0
        self.total_out = 0

    def evaluate(self, obs: Observation) -> list[Outcome]:
        for c in obs.crossings:
            if c.line_id != self.rule.line_id or c.class_name not in self.rule.classes:
                continue
            if c.direction is Direction.IN:
                self.total_in += 1
            else:
                self.total_out += 1
            if self.rule.direction in (Direction.ANY, c.direction) and self.schedule_active(c.at):
                self.crossings.append(c.at)
        while self.crossings and (obs.ts - self.crossings[0]).total_seconds() > self.rule.window_s:
            self.crossings.popleft()

        n = len(self.crossings)
        if n >= max(self.rule.threshold, 1) and self.cooldown_ok(obs.ts):
            started = self.crossings[0]
            self.crossings.clear()
            self.last_trigger_at = obs.ts
            where = (
                self.rule.direction.value
                if self.rule.direction is not Direction.ANY
                else "either way"
            )
            return [
                Trigger(
                    rule=self.rule,
                    key=f"{self.rule.id}:{obs.ts.timestamp():.0f}",
                    condition_started_at=started,
                    triggered_at=obs.ts,
                    value=float(n),
                    message=(
                        f"{n} crossing{'s' if n != 1 else ''} of '{self.line_name}' ({where}) "
                        f"in {fmt_duration(max((obs.ts - started).total_seconds(), 0))}"
                    ),
                    attributes={
                        "crossings": n,
                        "total_in": self.total_in,
                        "total_out": self.total_out,
                    },
                )
            ]
        return []
