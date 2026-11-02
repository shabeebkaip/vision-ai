"""Zones, lines and per-frame scene state (task EDG-08).

Geometry in configuration is normalised 0..1; here it is scaled to the frame size. Each tracked
object is placed by an anchor point (bottom-centre: where a person stands), so a person counts as
"in the queue" when their feet are in the queue zone, not when their head overlaps it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from vision_shared.schemas import CameraConfig, Detection, Direction, Line, Zone

PxPoint = tuple[float, float]


def scale_polygon(zone: Zone, width: int, height: int) -> list[PxPoint]:
    return [(x * width, y * height) for x, y in zone.polygon]


def point_in_polygon(p: PxPoint, poly: list[PxPoint]) -> bool:
    """Ray casting; points on an edge count as inside."""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        # On-edge check (collinear and within the segment's bounding box).
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if (
            abs(cross) < 1e-9
            and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9
            and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9
        ):
            return True
        if (y1 > y) != (y2 > y):
            x_at = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_at:
                inside = not inside
    return inside


def anchor_point(box: tuple[float, float, float, float]) -> PxPoint:
    x1, _, x2, y2 = box
    return ((x1 + x2) / 2.0, y2)


def side_of_line(p: PxPoint, a: PxPoint, b: PxPoint) -> float:
    """> 0 when p is on the right of a->b in image coordinates (y down), < 0 on the left."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def segments_intersect(p1: PxPoint, p2: PxPoint, a: PxPoint, b: PxPoint) -> bool:
    d1 = side_of_line(p1, a, b)
    d2 = side_of_line(p2, a, b)
    d3 = side_of_line(a, p1, p2)
    d4 = side_of_line(b, p1, p2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


@dataclass
class ZoneObject:
    track_id: int | None
    class_name: str
    confidence: float
    dwell_s: float


@dataclass
class Crossing:
    line_id: str
    track_id: int
    class_name: str
    direction: Direction  # IN = left -> right of start->end, OUT = the reverse
    at: datetime


@dataclass
class Departure:
    track_id: int
    class_name: str
    dwell_s: float
    at: datetime


@dataclass
class Observation:
    """What the rules see for one analysed frame."""

    ts: datetime
    zones: dict[str, list[ZoneObject]]
    crossings: list[Crossing]
    departures: dict[str, list[Departure]]
    detections: list[Detection]


@dataclass
class _Member:
    entered: datetime
    last_seen: datetime
    class_name: str
    confidence: float


@dataclass
class SceneState:
    """Keeps zone membership and line sides per track across frames for one camera."""

    camera: CameraConfig
    grace_s: float = 2.0
    """A tracked object missing for less than this keeps its zone membership (brief occlusion)."""
    _members: dict[str, dict[int, _Member]] = field(default_factory=dict)
    _last_anchor: dict[int, PxPoint] = field(default_factory=dict)
    _last_anchor_at: dict[int, datetime] = field(default_factory=dict)
    recent_departures: dict[str, deque[Departure]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for z in self.camera.zones:
            self._members[z.id] = {}
            self.recent_departures[z.id] = deque(maxlen=50)

    def update(
        self, ts: datetime, detections: list[Detection], width: int, height: int
    ) -> Observation:
        zones_px = {z.id: scale_polygon(z, width, height) for z in self.camera.zones}
        lines_px: dict[str, tuple[PxPoint, PxPoint]] = {
            ln.id: _scale_line(ln, width, height) for ln in self.camera.lines
        }

        observed: dict[str, list[ZoneObject]] = {zid: [] for zid in zones_px}
        departures: dict[str, list[Departure]] = {zid: [] for zid in zones_px}
        crossings: list[Crossing] = []

        for d in detections:
            p = anchor_point(d.box)
            for zid, poly in zones_px.items():
                if not point_in_polygon(p, poly):
                    continue
                if d.track_id is None:
                    observed[zid].append(ZoneObject(None, d.class_name, d.confidence, 0.0))
                    continue
                m = self._members[zid].get(d.track_id)
                if m is None:
                    m = _Member(
                        entered=ts, last_seen=ts, class_name=d.class_name, confidence=d.confidence
                    )
                    self._members[zid][d.track_id] = m
                m.last_seen = ts
                m.confidence = d.confidence

            if d.track_id is not None:
                prev = self._last_anchor.get(d.track_id)
                if prev is not None:
                    for lid, (a, b) in lines_px.items():
                        if segments_intersect(prev, p, a, b):
                            direction = Direction.IN if side_of_line(p, a, b) > 0 else Direction.OUT
                            crossings.append(Crossing(lid, d.track_id, d.class_name, direction, ts))
                self._last_anchor[d.track_id] = p
                self._last_anchor_at[d.track_id] = ts

        # Members still within grace are "present"; older ones have departed.
        for zid, members in self._members.items():
            gone: list[int] = []
            for tid, m in members.items():
                if (ts - m.last_seen).total_seconds() <= self.grace_s:
                    observed[zid].append(
                        ZoneObject(
                            tid, m.class_name, m.confidence, (ts - m.entered).total_seconds()
                        )
                    )
                else:
                    gone.append(tid)
            for tid in gone:
                m = members.pop(tid)
                dep = Departure(tid, m.class_name, (m.last_seen - m.entered).total_seconds(), ts)
                departures[zid].append(dep)
                self.recent_departures[zid].append(dep)

        stale = [
            tid
            for tid, at in self._last_anchor_at.items()
            if (ts - at).total_seconds() > max(self.grace_s * 5, 10.0)
        ]
        for tid in stale:
            self._last_anchor.pop(tid, None)
            self._last_anchor_at.pop(tid, None)

        return Observation(ts, observed, crossings, departures, detections)


def _scale_line(ln: Line, width: int, height: int) -> tuple[PxPoint, PxPoint]:
    return (ln.start[0] * width, ln.start[1] * height), (ln.end[0] * width, ln.end[1] * height)
