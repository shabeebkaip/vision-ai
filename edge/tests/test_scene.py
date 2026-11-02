from __future__ import annotations

from conftest import at

from vision_edge.scene import SceneState, anchor_point, point_in_polygon, segments_intersect
from vision_shared.schemas import CameraConfig, Detection, Direction, Line, Zone

SQUARE_PX = [(100.0, 100.0), (200.0, 100.0), (200.0, 200.0), (100.0, 200.0)]


def test_point_in_polygon() -> None:
    assert point_in_polygon((150, 150), SQUARE_PX)
    assert not point_in_polygon((250, 150), SQUARE_PX)
    assert point_in_polygon((100, 150), SQUARE_PX)  # on the edge counts as inside
    concave = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (5.0, 5.0), (0.0, 10.0)]
    assert not point_in_polygon((5, 8), concave)
    assert point_in_polygon((2, 2), concave)


def test_anchor_is_bottom_centre() -> None:
    assert anchor_point((10, 20, 30, 100)) == (20.0, 100.0)


def test_segments_intersect() -> None:
    assert segments_intersect((0, 0), (10, 10), (0, 10), (10, 0))
    assert not segments_intersect((0, 0), (1, 1), (5, 5), (6, 0))


def _person(x: float, y_feet: float, tid: int) -> Detection:
    return Detection(
        class_name="person",
        confidence=0.9,
        box=(x - 20, y_feet - 100, x + 20, y_feet),
        track_id=tid,
    )


def _camera() -> CameraConfig:
    return CameraConfig(
        id="cam", source="x",
        zones=[Zone(id="z", polygon=[(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)])],
        lines=[Line(id="door", start=(0.0, 0.5), end=(1.0, 0.5))],
    )  # fmt: skip


def test_zone_membership_and_dwell() -> None:
    scene = SceneState(_camera())
    obs = scene.update(at(0), [_person(200, 200, 1)], 400, 400)
    assert [o.track_id for o in obs.zones["z"]] == [1]
    obs = scene.update(at(10), [_person(200, 200, 1)], 400, 400)
    assert obs.zones["z"][0].dwell_s == 10


def test_brief_occlusion_keeps_membership_then_departs() -> None:
    scene = SceneState(_camera(), grace_s=2.0)
    scene.update(at(0), [_person(200, 200, 1)], 400, 400)
    obs = scene.update(at(1), [], 400, 400)
    assert len(obs.zones["z"]) == 1  # missing for 1 s: still counted
    obs = scene.update(at(5), [], 400, 400)
    assert obs.zones["z"] == []
    assert len(obs.departures["z"]) == 1
    assert obs.departures["z"][0].dwell_s == 0


def test_line_crossing_direction() -> None:
    scene = SceneState(_camera())
    # Line runs left to right at y=200; walking downwards crosses from left side to right side: IN.
    scene.update(at(0), [_person(100, 150, 7)], 400, 400)
    obs = scene.update(at(1), [_person(100, 250, 7)], 400, 400)
    assert [(c.track_id, c.direction) for c in obs.crossings] == [(7, Direction.IN)]
    obs = scene.update(at(2), [_person(100, 150, 7)], 400, 400)
    assert [c.direction for c in obs.crossings] == [Direction.OUT]


def test_untracked_detections_count_but_have_no_dwell() -> None:
    scene = SceneState(_camera())
    d = Detection(class_name="person", confidence=0.9, box=(180, 100, 220, 200))
    obs = scene.update(at(0), [d], 400, 400)
    assert obs.zones["z"][0].track_id is None
