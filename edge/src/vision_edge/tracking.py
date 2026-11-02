"""Multi-object tracking (task EDG-07).

A compact ByteTrack-style tracker (Zhang et al., 2022): constant-velocity Kalman filter per track,
two-stage association (high-confidence detections first, then low-confidence ones against tracks
that are still active), IoU cost, Hungarian matching. Track ids are anonymous integers that live in
memory only; nothing here identifies a person.

Written in-house (see docs/adr/007-own-tracker.md): supervision 0.31 removed its ByteTrack, and the
`trackers` package depends on the non-headless OpenCV build that edge boxes cannot load.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from vision_shared.schemas import Detection

FloatArray = NDArray[np.float64]


def _xyxy_to_xyah(b: tuple[float, float, float, float]) -> FloatArray:
    x1, y1, x2, y2 = b
    w, h = max(x2 - x1, 1e-3), max(y2 - y1, 1e-3)
    return np.array([x1 + w / 2, y1 + h / 2, w / h, h], dtype=np.float64)


def _xyah_to_xyxy(m: FloatArray) -> tuple[float, float, float, float]:
    cx, cy, a, h = (float(v) for v in m[:4])
    w = a * h
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


class KalmanBox:
    """Constant-velocity Kalman filter on (cx, cy, aspect, height) and their velocities.
    Noise is scaled by box height, as in SORT/ByteTrack. Time step is in seconds."""

    POS_W = 1.0 / 20
    VEL_W = 1.0 / 160

    def __init__(self, box: tuple[float, float, float, float]) -> None:
        m = _xyxy_to_xyah(box)
        self.x = np.r_[m, np.zeros(4)]
        h = m[3]
        std = [
            2 * self.POS_W * h, 2 * self.POS_W * h, 1e-2, 2 * self.POS_W * h,
            10 * self.VEL_W * h, 10 * self.VEL_W * h, 1e-5, 10 * self.VEL_W * h,
        ]  # fmt: skip
        self.P = np.diag(np.square(std))

    def predict(self, dt: float) -> None:
        dt = max(dt, 1e-3)
        steps = dt * 5.0  # noise model tuned per 0.2 s step (5 fps)
        F = np.eye(8)
        F[:4, 4:] = np.eye(4) * dt
        h = self.x[3]
        q = [
            self.POS_W * h, self.POS_W * h, 1e-2, self.POS_W * h,
            self.VEL_W * h, self.VEL_W * h, 1e-5, self.VEL_W * h,
        ]  # fmt: skip
        Q = np.diag(np.square(q)) * steps
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, box: tuple[float, float, float, float]) -> None:
        z = _xyxy_to_xyah(box)
        H = np.eye(4, 8)
        h = self.x[3]
        R = np.diag(np.square([self.POS_W * h, self.POS_W * h, 1e-1, self.POS_W * h]))
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ (z - H @ self.x)
        self.P = (np.eye(8) - K @ H) @ self.P

    @property
    def box(self) -> tuple[float, float, float, float]:
        return _xyah_to_xyxy(self.x)


@dataclass
class Track:
    track_id: int
    class_name: str
    kf: KalmanBox
    confidence: float
    last_update_s: float
    hits: int = 1
    _predicted_at: float = field(default=0.0, repr=False)


def iou_matrix(
    a: list[tuple[float, float, float, float]], b: list[tuple[float, float, float, float]]
) -> FloatArray:
    if not a or not b:
        return np.zeros((len(a), len(b)))
    A = np.asarray(a, dtype=np.float64)[:, None, :]
    B = np.asarray(b, dtype=np.float64)[None, :, :]
    ix1 = np.maximum(A[..., 0], B[..., 0])
    iy1 = np.maximum(A[..., 1], B[..., 1])
    ix2 = np.minimum(A[..., 2], B[..., 2])
    iy2 = np.minimum(A[..., 3], B[..., 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    area_a = (A[..., 2] - A[..., 0]) * (A[..., 3] - A[..., 1])
    area_b = (B[..., 2] - B[..., 0]) * (B[..., 3] - B[..., 1])
    union = area_a + area_b - inter
    out: FloatArray = np.where(union > 0, inter / union, 0.0)
    return out


def _match(
    tracks: list[Track], dets: list[Detection], min_iou: float
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Hungarian matching on 1 - IoU with class gating. Returns (pairs, unmatched_t, unmatched_d)."""
    if not tracks or not dets:
        return [], list(range(len(tracks))), list(range(len(dets)))
    ious = iou_matrix([t.kf.box for t in tracks], [d.box for d in dets])
    same = np.array([[t.class_name == d.class_name for d in dets] for t in tracks])
    cost = np.where(same, 1.0 - ious, 1e6)
    rows, cols = linear_sum_assignment(cost)
    pairs: list[tuple[int, int]] = []
    for r, c in zip(rows, cols, strict=True):
        if same[r, c] and ious[r, c] >= min_iou:
            pairs.append((int(r), int(c)))
    mt = {p[0] for p in pairs}
    md = {p[1] for p in pairs}
    return (
        pairs,
        [i for i in range(len(tracks)) if i not in mt],
        [j for j in range(len(dets)) if j not in md],
    )


class ByteTracker:
    """Per-camera tracker. Call `update(detections, t_seconds)` once per analysed frame."""

    def __init__(
        self,
        high_threshold: float = 0.5,
        low_threshold: float = 0.1,
        new_track_threshold: float = 0.55,
        first_match_iou: float = 0.2,
        second_match_iou: float = 0.3,
        lost_buffer_s: float = 3.0,
    ) -> None:
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.new_track_threshold = new_track_threshold
        self.first_match_iou = first_match_iou
        self.second_match_iou = second_match_iou
        self.lost_buffer_s = lost_buffer_s
        self._tracks: list[Track] = []
        self._next_id = 1
        self._last_t: float | None = None

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks)

    def update(self, detections: list[Detection], t: float) -> list[Detection]:
        dt = 0.2 if self._last_t is None else max(t - self._last_t, 1e-3)
        self._last_t = t
        for tr in self._tracks:
            tr.kf.predict(dt)

        high = [d for d in detections if d.confidence >= self.high_threshold]
        low = [d for d in detections if self.low_threshold <= d.confidence < self.high_threshold]

        out: list[Detection] = []

        # Stage 1: high-confidence detections against every live track.
        pairs, un_t, un_d = _match(self._tracks, high, self.first_match_iou)
        for ti, di in pairs:
            out.append(self._apply(self._tracks[ti], high[di], t))

        # Stage 2: low-confidence detections against tracks seen in the previous frame.
        recent = [self._tracks[i] for i in un_t if t - self._tracks[i].last_update_s <= dt * 1.5]
        pairs2, _, _ = _match(recent, low, self.second_match_iou)
        for ti, di in pairs2:
            out.append(self._apply(recent[ti], low[di], t))

        # New tracks from unmatched confident detections.
        for di in un_d:
            d = high[di]
            if d.confidence >= self.new_track_threshold:
                tr = Track(
                    track_id=self._next_id,
                    class_name=d.class_name,
                    kf=KalmanBox(d.box),
                    confidence=d.confidence,
                    last_update_s=t,
                )
                self._next_id += 1
                self._tracks.append(tr)
                out.append(d.model_copy(update={"track_id": tr.track_id}))

        # Forget tracks lost for too long.
        self._tracks = [tr for tr in self._tracks if t - tr.last_update_s <= self.lost_buffer_s]
        return out

    @staticmethod
    def _apply(tr: Track, d: Detection, t: float) -> Detection:
        tr.kf.update(d.box)
        tr.confidence = d.confidence
        tr.last_update_s = t
        tr.hits += 1
        return d.model_copy(update={"track_id": tr.track_id})
