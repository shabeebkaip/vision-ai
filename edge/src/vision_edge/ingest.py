"""Frame sources (task EDG-02): video files, RTSP cameras and replayed detections.

Every source yields `Frame` objects at (roughly) the requested analysis rate with timezone-aware
UTC timestamps. File and replay sources use *video time* (start time + offset) so results are
reproducible; the RTSP source uses wall-clock time.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import structlog

from vision_edge.frames import Frame, Image
from vision_shared.schemas import Detection

log = structlog.get_logger(__name__)

DEFAULT_START = datetime(2026, 1, 4, 6, 0, tzinfo=timezone.utc)  # Sunday 09:00 in Riyadh


def _sample_step(source_fps: float, target_fps: float) -> int:
    if source_fps <= 0:
        return 1
    return max(1, round(source_fps / target_fps))


class FileSource:
    """Reads a video file and yields every n-th frame to approximate `fps`."""

    def __init__(
        self,
        path: str | Path,
        camera_id: str,
        fps: float = 5.0,
        start_time: datetime = DEFAULT_START,
        max_seconds: float | None = None,
    ) -> None:
        self.path = str(path)
        self.camera_id = camera_id
        self.fps = fps
        self.start_time = start_time
        self.max_seconds = max_seconds

    def __iter__(self) -> Iterator[Frame]:
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise FileNotFoundError(f"cannot open video {self.path}")
        source_fps = cap.get(cv2.CAP_PROP_FPS) or self.fps
        step = _sample_step(source_fps, self.fps)
        index = 0
        emitted = 0
        try:
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                if index % step == 0:
                    t = index / source_fps
                    if self.max_seconds is not None and t > self.max_seconds:
                        break
                    h, w = image.shape[:2]
                    yield Frame(
                        camera_id=self.camera_id,
                        index=emitted,
                        ts=self.start_time + timedelta(seconds=t),
                        width=w,
                        height=h,
                        image=image,
                        video_time_s=t,
                    )
                    emitted += 1
                index += 1
        finally:
            cap.release()


class ReplaySource:
    """Replays cached detections from a JSONL file (one line per analysed frame).

    Line format: {"t": 12.4, "w": 1280, "h": 720,
                  "detections": [{"class_name": "person", "confidence": 0.91, "box": [x1, y1, x2, y2]}]}

    Used by the evaluation harness and tests so the pipeline can run without a model or video.
    """

    def __init__(
        self,
        path: str | Path,
        camera_id: str,
        start_time: datetime = DEFAULT_START,
        max_seconds: float | None = None,
        video: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        self.camera_id = camera_id
        self.start_time = start_time
        self.max_seconds = max_seconds
        self.video = str(video) if video else None

    def __iter__(self) -> Iterator[Frame]:
        cap = cv2.VideoCapture(self.video) if self.video else None
        video_fps = (cap.get(cv2.CAP_PROP_FPS) or 5.0) if cap is not None else 5.0
        video_t = -1.0
        image: Image | None = None
        try:
            yield from self._rows(cap, video_fps, video_t, image)
        finally:
            if cap is not None:
                cap.release()

    def _rows(
        self,
        cap: cv2.VideoCapture | None,
        video_fps: float,
        video_t: float,
        image: Image | None,
    ) -> Iterator[Frame]:
        with self.path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                t = float(row["t"])
                if self.max_seconds is not None and t > self.max_seconds:
                    break
                dets = [Detection.model_validate(d) for d in row.get("detections", [])]
                if cap is not None:
                    # Advance the paired video to the frame at time t.
                    while video_t + 1e-6 < t:
                        ok, img = cap.read()
                        if not ok:
                            break
                        image = img
                        video_t = (cap.get(cv2.CAP_PROP_POS_FRAMES) - 1) / video_fps
                yield Frame(
                    camera_id=self.camera_id,
                    index=i,
                    ts=self.start_time + timedelta(seconds=t),
                    width=int(row.get("w", 1280)),
                    height=int(row.get("h", 720)),
                    image=image,
                    detections=dets,
                    video_time_s=t,
                )


@dataclass
class CameraHealth:
    camera_id: str
    online: bool = False
    measured_fps: float = 0.0
    width: int = 0
    height: int = 0
    last_frame_at: datetime | None = None
    reconnects: int = 0
    last_error: str = ""
    _frame_times: list[float] = field(default_factory=list, repr=False)

    def mark_frame(self, now_mono: float) -> None:
        self._frame_times.append(now_mono)
        cutoff = now_mono - 10.0
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.pop(0)
        if len(self._frame_times) > 1:
            span = self._frame_times[-1] - self._frame_times[0]
            self.measured_fps = (len(self._frame_times) - 1) / span if span > 0 else 0.0


class RtspSource:
    """Live camera source with automatic reconnect and stall detection.

    A background thread keeps only the newest decoded frame, so a slow detector never builds up
    latency; the iterator samples that frame at the target rate.
    """

    def __init__(
        self,
        url: str,
        camera_id: str,
        fps: float = 5.0,
        stall_timeout_s: float = 10.0,
        max_backoff_s: float = 60.0,
    ) -> None:
        self.url = url
        self.camera_id = camera_id
        self.fps = fps
        self.stall_timeout_s = stall_timeout_s
        self.max_backoff_s = max_backoff_s
        self.health = CameraHealth(camera_id=camera_id)
        self._latest: Image | None = None
        self._latest_mono = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- reader thread -------------------------------------------------------------------
    def _open(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _reader(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                self.health.online = False
                self.health.last_error = "cannot open stream"
                log.warning("camera.open_failed", camera_id=self.camera_id, retry_in_s=backoff)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self.max_backoff_s)
                self.health.reconnects += 1
                continue
            backoff = 1.0
            self.health.online = True
            last_ok = time.monotonic()
            while not self._stop.is_set():
                ok, image = cap.read()
                now = time.monotonic()
                if ok and image is not None:
                    last_ok = now
                    with self._lock:
                        self._latest = image
                        self._latest_mono = now
                    self.health.mark_frame(now)
                    self.health.height, self.health.width = image.shape[:2]
                    self.health.last_frame_at = datetime.now(timezone.utc)
                elif now - last_ok > self.stall_timeout_s:
                    self.health.online = False
                    self.health.last_error = f"no frame for {self.stall_timeout_s:.0f}s"
                    log.warning("camera.stalled", camera_id=self.camera_id)
                    break
            cap.release()
            self.health.reconnects += 1

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._reader, name=f"rtsp-{self.camera_id}", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- iterator ------------------------------------------------------------------------
    def __iter__(self) -> Iterator[Frame]:
        self.start()
        interval = 1.0 / self.fps
        index = 0
        started = time.monotonic()
        last_seen = 0.0
        try:
            while not self._stop.is_set():
                tick = time.monotonic()
                with self._lock:
                    image, stamp = self._latest, self._latest_mono
                if image is not None and stamp > last_seen:
                    last_seen = stamp
                    h, w = image.shape[:2]
                    yield Frame(
                        camera_id=self.camera_id,
                        index=index,
                        ts=datetime.now(timezone.utc),
                        width=w,
                        height=h,
                        image=image,
                        video_time_s=tick - started,
                    )
                    index += 1
                time.sleep(max(0.0, interval - (time.monotonic() - tick)))
        finally:
            self.stop()


def open_source(
    source: str,
    camera_id: str,
    fps: float,
    max_seconds: float | None = None,
    start_time: datetime = DEFAULT_START,
    video: str | None = None,
) -> FileSource | ReplaySource | RtspSource:
    """Pick a source from a camera's `source` string. A `.jsonl` source replays cached detections,
    optionally over a paired `video` so snapshots and clips can be produced."""
    if source.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return RtspSource(source, camera_id, fps=fps)
    if source.endswith(".jsonl"):
        return ReplaySource(
            source, camera_id, start_time=start_time, max_seconds=max_seconds, video=video
        )
    return FileSource(source, camera_id, fps=fps, start_time=start_time, max_seconds=max_seconds)
