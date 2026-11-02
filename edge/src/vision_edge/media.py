"""Snapshots and event clips (task EDG-11, first version).

The clip buffer keeps the last `pre_s` seconds of analysed frames as JPEG bytes per camera (small
in memory, no re-encoding while idle). When an event fires it keeps collecting for `post_s`
seconds, then writes an H.264 MP4 with FFmpeg (falls back to OpenCV's mp4v if FFmpeg is missing).
Production will move to go2rtc segment recording at full frame rate; this version proves the flow.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from vision_edge.frames import Frame, Image
from vision_edge.scene import scale_polygon
from vision_shared.schemas import CameraConfig, Detection, Event

COLOURS = {
    "zone": (0, 200, 255),
    "line": (255, 160, 0),
    "box": (60, 220, 60),
    "box_rule": (40, 40, 240),
}


def draw_snapshot(
    image: Image,
    camera: CameraConfig,
    detections: list[Detection],
    highlight_zone: str | None = None,
    caption: str = "",
) -> Image:
    """Boxes, zones and lines over a copy of the frame. No faces are blurred or identified here;
    snapshots stay inside the customer's account."""
    out: Image = image.copy()
    h, w = out.shape[:2]
    for z in camera.zones:
        pts = np.array(scale_polygon(z, w, h), dtype=np.int32)
        thick = 3 if z.id == highlight_zone else 1
        cv2.polylines(out, [pts], True, COLOURS["zone"], thick, cv2.LINE_AA)
        cv2.putText(
            out, z.name or z.id, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOURS["zone"], 2
        )
    for ln in camera.lines:
        a = (int(ln.start[0] * w), int(ln.start[1] * h))
        b = (int(ln.end[0] * w), int(ln.end[1] * h))
        cv2.arrowedLine(out, a, b, COLOURS["line"], 2, cv2.LINE_AA, tipLength=0.03)
    for d in detections:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        cv2.rectangle(out, (x1, y1), (x2, y2), COLOURS["box"], 2)
        label = d.class_name if d.track_id is None else f"{d.class_name} #{d.track_id}"
        cv2.putText(
            out, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOURS["box"], 1
        )
    if caption:
        cv2.rectangle(out, (0, h - 28), (w, h), (0, 0, 0), -1)
        cv2.putText(
            out, caption[:110], (8, h - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1
        )
    return out


def encode_jpeg(image: Image, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return bytes(buf.tobytes())


@dataclass
class _PendingClip:
    event: Event
    until: datetime
    frames: list[tuple[datetime, bytes]] = field(default_factory=list)


class ClipRecorder:
    def __init__(
        self,
        out_dir: str | Path,
        fps: float,
        pre_s: float = 5.0,
        post_s: float = 5.0,
        max_width: int = 1280,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.fps = fps
        self.pre_s = pre_s
        self.post_s = post_s
        self.max_width = max_width
        self._buffer: deque[tuple[datetime, bytes]] = deque()
        self._pending: list[_PendingClip] = []

    def push(self, frame: Frame) -> list[tuple[Event, Path]]:
        """Add a frame; returns clips that finished on this frame."""
        if frame.image is None:
            return []
        img = frame.image
        if img.shape[1] > self.max_width:
            scale = self.max_width / img.shape[1]
            img = cv2.resize(img, (self.max_width, int(img.shape[0] * scale)))
        jpg = encode_jpeg(img, 75)
        self._buffer.append((frame.ts, jpg))
        while self._buffer and (frame.ts - self._buffer[0][0]).total_seconds() > self.pre_s:
            self._buffer.popleft()
        done: list[tuple[Event, Path]] = []
        still: list[_PendingClip] = []
        for p in self._pending:
            p.frames.append((frame.ts, jpg))
            if frame.ts >= p.until:
                done.append((p.event, self._write(p)))
            else:
                still.append(p)
        self._pending = still
        return done

    def start(self, event: Event) -> None:
        from datetime import timedelta

        self._pending.append(
            _PendingClip(
                event, event.triggered_at + timedelta(seconds=self.post_s), list(self._buffer)
            )
        )

    def flush(self) -> list[tuple[Event, Path]]:
        done = [(p.event, self._write(p)) for p in self._pending if p.frames]
        self._pending = []
        return done

    def _write(self, clip: _PendingClip) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{clip.event.id}.mp4"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg, "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", f"{self.fps:g}",
                "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart", str(path),
            ]  # fmt: skip
            proc = subprocess.run(
                cmd, input=b"".join(j for _, j in clip.frames), capture_output=True
            )
            if proc.returncode == 0:
                return path
        first = cv2.imdecode(np.frombuffer(clip.frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        if first is None:
            raise RuntimeError("could not decode buffered clip frame")
        h, w = first.shape[:2]
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), self.fps, (w, h))
        for _, j in clip.frames:
            img = cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                writer.write(img)
        writer.release()
        return path
