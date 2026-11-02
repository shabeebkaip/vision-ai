from __future__ import annotations

import numpy as np

from vision_edge.tracking import ByteTracker, iou_matrix
from vision_shared.schemas import Detection


def det(x: float, y: float, conf: float = 0.9, cls: str = "person") -> Detection:
    return Detection(class_name=cls, confidence=conf, box=(x, y, x + 40, y + 100))


def test_iou_matrix() -> None:
    m = iou_matrix([(0, 0, 10, 10)], [(0, 0, 10, 10), (5, 0, 15, 10), (20, 20, 30, 30)])
    assert np.allclose(m, [[1.0, 1 / 3, 0.0]])


def test_two_walkers_keep_their_ids() -> None:
    tr = ByteTracker()
    ids: list[list[int | None]] = []
    for i in range(20):
        t = i * 0.2
        out = tr.update([det(100 + 10 * i, 100), det(500 - 10 * i, 300)], t)
        ids.append(sorted(d.track_id for d in out))  # type: ignore[type-var]
    assert all(row == [1, 2] for row in ids)


def test_missed_frames_do_not_change_id() -> None:
    tr = ByteTracker(lost_buffer_s=2.0)
    tr.update([det(100, 100)], 0.0)
    tr.update([det(105, 100)], 0.2)
    tr.update([], 0.4)
    tr.update([], 0.6)
    out = tr.update([det(120, 100)], 0.8)
    assert out[0].track_id == 1


def test_low_confidence_detection_continues_track_but_does_not_start_one() -> None:
    tr = ByteTracker()
    tr.update([det(100, 100, 0.9)], 0.0)
    out = tr.update([det(104, 100, 0.3)], 0.2)
    assert out[0].track_id == 1
    out = tr.update([det(400, 400, 0.3)], 0.4)
    assert out == []


def test_classes_are_never_mixed() -> None:
    tr = ByteTracker()
    tr.update([det(100, 100, cls="person")], 0.0)
    out = tr.update([det(100, 100, cls="truck")], 0.2)
    assert out[0].track_id == 2


def test_track_expires_after_buffer() -> None:
    tr = ByteTracker(lost_buffer_s=1.0)
    tr.update([det(100, 100)], 0.0)
    tr.update([], 2.0)
    out = tr.update([det(100, 100)], 2.2)
    assert out[0].track_id == 2
