"""Rules engine: one evaluator class per `RuleType`."""

from __future__ import annotations

from vision_edge.rules.base import Clear, ConditionRule, Outcome, RuleEvaluator, Trigger
from vision_edge.rules.line_rules import LineCrossing
from vision_edge.rules.zone_rules import (
    DwellOver,
    PresenceAfterHours,
    QueueLengthOver,
    ZoneEmpty,
    ZoneOccupancyOver,
)
from vision_shared.schemas import CameraConfig, Rule, RuleType

EVALUATORS: dict[RuleType, type[RuleEvaluator]] = {
    RuleType.ZONE_OCCUPANCY_OVER: ZoneOccupancyOver,
    RuleType.QUEUE_LENGTH_OVER: QueueLengthOver,
    RuleType.ZONE_EMPTY: ZoneEmpty,
    RuleType.PRESENCE_AFTER_HOURS: PresenceAfterHours,
    RuleType.DWELL_OVER: DwellOver,
    RuleType.LINE_CROSSING: LineCrossing,
}


def build_evaluator(rule: Rule, camera: CameraConfig, timezone: str) -> RuleEvaluator:
    zone_name = camera.zone(rule.zone_id).name or rule.zone_id if rule.zone_id else ""
    line_name = camera.line(rule.line_id).name or rule.line_id if rule.line_id else ""
    return EVALUATORS[rule.type](rule, timezone, zone_name or "", line_name or "")


__all__ = [
    "EVALUATORS",
    "Clear",
    "ConditionRule",
    "Outcome",
    "RuleEvaluator",
    "Trigger",
    "build_evaluator",
]
