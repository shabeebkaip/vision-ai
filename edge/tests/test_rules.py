from __future__ import annotations

from datetime import time

from conftest import at

from vision_edge.rules import Clear, Trigger, build_evaluator
from vision_edge.scene import Crossing, Departure, Observation, ZoneObject
from vision_shared.schemas import CameraConfig, Direction, Line, Rule, RuleType, Schedule, Zone

CAM = CameraConfig(
    id="cam", source="x",
    zones=[Zone(id="z", name="Queue", polygon=[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)])],
    lines=[Line(id="door", name="Door", start=(0.0, 0.5), end=(1.0, 0.5))],
)  # fmt: skip


def obs(
    t: float,
    n: int = 0,
    dwell: float = 0.0,
    crossings: list[Crossing] | None = None,
    departures: list[Departure] | None = None,
) -> Observation:
    objs = [
        ZoneObject(track_id=i + 1, class_name="person", confidence=0.9, dwell_s=dwell)
        for i in range(n)
    ]
    return Observation(at(t), {"z": objs}, crossings or [], {"z": departures or []}, [])


def feed(rule: Rule, frames: list[Observation]) -> list[tuple[float, str]]:
    ev = build_evaluator(rule, CAM, "Asia/Riyadh")
    out: list[tuple[float, str]] = []
    for o in frames:
        for r in ev.evaluate(o):
            t = (o.ts - at(0)).total_seconds()
            out.append((t, "trigger" if isinstance(r, Trigger) else "clear"))
    return out


def occ(**kw: object) -> Rule:
    base: dict[str, object] = dict(
        id="r",
        type=RuleType.ZONE_OCCUPANCY_OVER,
        camera_id="cam",
        zone_id="z",
        threshold=3,
        min_duration_s=10,
        clear_after_s=5,
        cooldown_s=60,
    )
    base.update(kw)
    return Rule(**base)  # type: ignore[arg-type]


def test_occupancy_fires_after_min_duration_not_before() -> None:
    frames = [obs(t, 5) for t in range(0, 15)]
    assert feed(occ(), frames) == [(10, "trigger")]
    assert feed(occ(), frames[:10]) == []


def test_occupancy_at_threshold_is_not_over() -> None:
    assert feed(occ(), [obs(t, 3) for t in range(30)]) == []


def test_brief_dip_does_not_reset_timer() -> None:
    frames = [obs(t, 5 if t not in (4, 5) else 1) for t in range(0, 15)]
    assert feed(occ(), frames) == [(10, "trigger")]


def test_clear_after_condition_false_long_enough() -> None:
    frames = [obs(t, 5) for t in range(0, 20)] + [obs(t, 0) for t in range(20, 30)]
    assert feed(occ(), frames) == [(10, "trigger"), (25, "clear")]


def test_cooldown_blocks_second_trigger() -> None:
    frames = (
        [obs(t, 5) for t in range(0, 20)]
        + [obs(t, 0) for t in range(20, 30)]
        + [obs(t, 5) for t in range(30, 50)]
        + [obs(t, 0) for t in range(50, 60)]
        + [obs(t, 5) for t in range(60, 90)]
    )
    # Second episode (30-50 s) is inside the 60 s cooldown; third (from 60 s) fires at 70 s.
    assert feed(occ(), frames) == [(10, "trigger"), (25, "clear"), (70, "trigger")]


def test_class_and_confidence_filters() -> None:
    o = Observation(
        at(0), {"z": [ZoneObject(1, "truck", 0.9, 0), ZoneObject(2, "person", 0.2, 0)]}, [], {}, []
    )
    ev = build_evaluator(occ(threshold=0, min_duration_s=0), CAM, "Asia/Riyadh")
    assert ev.evaluate(o) == []


def test_zone_empty_respects_schedule() -> None:
    rule = Rule(
        id="e",
        type=RuleType.ZONE_EMPTY,
        camera_id="cam",
        zone_id="z",
        min_duration_s=30,
        clear_after_s=0,
        schedule=Schedule(start=time(9, 0), end=time(9, 1)),
    )
    # 09:00:00 to 09:02:00 Riyadh: empty all along, but the window closes at 09:01.
    frames = [obs(t, 0) for t in range(0, 120)]
    assert feed(rule, frames) == [(30, "trigger"), (61, "clear")]


def test_zone_empty_resets_when_someone_returns() -> None:
    rule = Rule(
        id="e",
        type=RuleType.ZONE_EMPTY,
        camera_id="cam",
        zone_id="z",
        min_duration_s=30,
        clear_after_s=0,
    )
    frames = (
        [obs(t, 0) for t in range(0, 20)]
        + [obs(t, 1) for t in range(20, 25)]
        + [obs(t, 0) for t in range(25, 50)]
    )
    assert feed(rule, frames) == []


def test_after_hours_presence() -> None:
    rule = Rule(
        id="a",
        type=RuleType.PRESENCE_AFTER_HOURS,
        camera_id="cam",
        zone_id="z",
        min_duration_s=5,
        schedule=Schedule(start=time(8, 0), end=time(10, 0)),
    )
    assert feed(rule, [obs(t, 1) for t in range(10)]) == [(5, "trigger")]
    closed = Rule(
        id="a",
        type=RuleType.PRESENCE_AFTER_HOURS,
        camera_id="cam",
        zone_id="z",
        min_duration_s=5,
        schedule=Schedule(start=time(20, 0), end=time(6, 0)),
    )
    assert feed(closed, [obs(t, 1) for t in range(10)]) == []


def test_dwell_fires_once_per_visit_and_clears_on_departure() -> None:
    rule = Rule(
        id="d",
        type=RuleType.DWELL_OVER,
        camera_id="cam",
        zone_id="z",
        min_duration_s=60,
        cooldown_s=0,
    )
    frames = [obs(t, 1, dwell=float(t)) for t in range(0, 100)]
    frames.append(obs(100, 0, departures=[Departure(1, "person", 99, at(100))]))
    assert feed(rule, frames) == [(60, "trigger"), (100, "clear")]


def test_queue_reports_longest_wait() -> None:
    rule = Rule(
        id="q",
        type=RuleType.QUEUE_LENGTH_OVER,
        camera_id="cam",
        zone_id="z",
        threshold=2,
        min_duration_s=0,
    )
    ev = build_evaluator(rule, CAM, "Asia/Riyadh")
    out = ev.evaluate(obs(0, 3, dwell=95))
    assert isinstance(out[0], Trigger)
    assert out[0].attributes["longest_wait_s"] == 95
    assert "Queue of 3" in out[0].message


def _crossing(t: float, d: Direction, tid: int) -> Crossing:
    return Crossing("door", tid, "person", d, at(t))


def test_line_crossing_counts_direction_in_window() -> None:
    rule = Rule(
        id="l",
        type=RuleType.LINE_CROSSING,
        camera_id="cam",
        line_id="door",
        direction=Direction.IN,
        threshold=3,
        window_s=60,
        cooldown_s=0,
    )
    frames = [
        obs(0, crossings=[_crossing(0, Direction.IN, 1)]),
        obs(10, crossings=[_crossing(10, Direction.OUT, 2)]),
        obs(20, crossings=[_crossing(20, Direction.IN, 3)]),
        obs(100, crossings=[_crossing(100, Direction.IN, 4)]),  # first two expired from the window
        obs(110, crossings=[_crossing(110, Direction.IN, 5)]),
        obs(120, crossings=[_crossing(120, Direction.IN, 6)]),
    ]
    assert feed(rule, frames) == [(120, "trigger")]


def test_line_crossing_any_direction_threshold_one() -> None:
    rule = Rule(
        id="l",
        type=RuleType.LINE_CROSSING,
        camera_id="cam",
        line_id="door",
        threshold=1,
        cooldown_s=30,
    )
    frames = [
        obs(0, crossings=[_crossing(0, Direction.OUT, 1)]),
        obs(10, crossings=[_crossing(10, Direction.IN, 2)]),
        obs(40, crossings=[_crossing(40, Direction.IN, 3)]),
    ]
    assert feed(rule, frames) == [(0, "trigger"), (40, "trigger")]


def test_outcome_types_exported() -> None:
    assert Trigger and Clear
