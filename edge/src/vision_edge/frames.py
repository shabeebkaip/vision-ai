from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from numpy.typing import NDArray

from vision_shared.schemas import Detection

Image = NDArray[Any]
"""A BGR image as returned by OpenCV (height x width x 3, uint8)."""


@dataclass
class Frame:
    """One analysed frame. `image` is BGR (OpenCV order) or None when replaying cached detections."""

    camera_id: str
    index: int
    ts: datetime
    width: int
    height: int
    image: Image | None = None
    detections: list[Detection] | None = None
    """Pre-computed detections (replay sources). Live sources leave this as None."""
    video_time_s: float = 0.0
    """Seconds since the source's first frame."""
