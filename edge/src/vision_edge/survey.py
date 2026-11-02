"""Camera suitability check (task DET-07).

Run during a site survey on a 1–2 minute sample of a camera: it measures what the detector will
actually see and says which use cases the camera can support.

    vision-edge survey "rtsp://USER:PASS@NVR:554/Streaming/Channels/102" --seconds 120
    vision-edge survey sample.mp4 --detector rfdetr-nano --json survey.json
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from enum import Enum

import cv2
import numpy as np

from vision_edge.frames import Frame, Image
from vision_shared.schemas import Detection


class Level(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class Check:
    name: str
    level: Level
    value: str
    advice: str = ""


# Minimum person height in pixels at the analysed resolution, per use case.
USE_CASE_MIN_PERSON_PX: dict[str, int] = {
    "people counting, zones, queues, after-hours": 40,
    "dwell and loitering": 40,
    "entrance counting (line crossing)": 50,
    "PPE: helmet and vest": 100,
    "kitchen hygiene: hairnet and gloves": 140,
}


@dataclass
class SurveyReport:
    source: str
    frames: int
    seconds: float
    width: int
    height: int
    measured_fps: float
    brightness: float
    sharpness: float
    person_heights_px: list[float] = field(default_factory=list)
    max_people_in_frame: int = 0
    checks: list[Check] = field(default_factory=list)
    supported: list[str] = field(default_factory=list)
    not_supported: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> Level:
        levels = {c.level for c in self.checks}
        if Level.FAIL in levels:
            return Level.FAIL
        return Level.WARN if Level.WARN in levels else Level.OK

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        d["checks"] = [{**asdict(c), "level": c.level.value} for c in self.checks]
        d["person_heights_px"] = [round(h, 1) for h in self.person_heights_px]
        return d


def brightness_of(image: Image) -> float:
    """Mean luma 0..255."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(np.mean(grey))


def sharpness_of(image: Image) -> float:
    """Variance of the Laplacian on a 640-px-wide copy; low values mean blur or a smeared IR image."""
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if grey.shape[1] > 640:
        scale = 640 / grey.shape[1]
        grey = cv2.resize(grey, (640, int(grey.shape[0] * scale)))
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def person_heights(detections: list[Detection]) -> list[float]:
    return [d.box[3] - d.box[1] for d in detections if d.class_name == "person"]


def evaluate(
    source: str,
    frames: int,
    seconds: float,
    width: int,
    height: int,
    brightness: list[float],
    sharpness: list[float],
    heights: list[float],
    max_people: int,
    target_fps: float,
) -> SurveyReport:
    fps = frames / seconds if seconds > 0 else 0.0
    rep = SurveyReport(
        source=source,
        frames=frames,
        seconds=round(seconds, 1),
        width=width,
        height=height,
        measured_fps=round(fps, 1),
        brightness=round(statistics.median(brightness), 1) if brightness else 0.0,
        sharpness=round(statistics.median(sharpness), 1) if sharpness else 0.0,
        person_heights_px=heights,
        max_people_in_frame=max_people,
    )
    c = rep.checks

    if frames == 0:
        c.append(
            Check(
                "stream",
                Level.FAIL,
                "no frames",
                "Check URL, credentials, RTSP port and that the sub-stream is enabled.",
            )
        )
        return rep

    if width < 640:
        c.append(
            Check(
                "resolution",
                Level.FAIL,
                f"{width}x{height}",
                "Set the sub-stream to 1280x720 (or at least 704x576) in the NVR.",
            )
        )
    elif width < 1280:
        c.append(
            Check(
                "resolution",
                Level.WARN,
                f"{width}x{height}",
                "Works for counting; 1280x720 gives more range.",
            )
        )
    else:
        c.append(Check("resolution", Level.OK, f"{width}x{height}"))

    if fps < target_fps * 0.6:
        c.append(
            Check(
                "frame rate",
                Level.FAIL,
                f"{fps:.1f} fps",
                f"Need about {target_fps:g} fps: raise the sub-stream frame rate or check network load.",
            )
        )
    elif fps < target_fps * 0.9:
        c.append(
            Check(
                "frame rate",
                Level.WARN,
                f"{fps:.1f} fps",
                "Slightly below target; fast events may be missed.",
            )
        )
    else:
        c.append(Check("frame rate", Level.OK, f"{fps:.1f} fps"))

    if rep.brightness < 35:
        c.append(
            Check(
                "light",
                Level.FAIL,
                f"brightness {rep.brightness:.0f}/255",
                "Too dark: check IR, add light, or exclude night hours for this camera.",
            )
        )
    elif rep.brightness < 60:
        c.append(
            Check(
                "light",
                Level.WARN,
                f"brightness {rep.brightness:.0f}/255",
                "Dim; expect lower accuracy, test at night too.",
            )
        )
    elif rep.brightness > 220:
        c.append(
            Check(
                "light",
                Level.WARN,
                f"brightness {rep.brightness:.0f}/255",
                "Over-exposed: sun or glare; enable WDR or re-aim.",
            )
        )
    else:
        c.append(Check("light", Level.OK, f"brightness {rep.brightness:.0f}/255"))

    if rep.sharpness < 30:
        c.append(
            Check(
                "sharpness",
                Level.WARN,
                f"{rep.sharpness:.0f}",
                "Blurry: clean the lens, refocus, or raise the sub-stream bitrate.",
            )
        )
    else:
        c.append(Check("sharpness", Level.OK, f"{rep.sharpness:.0f}"))

    if not heights:
        c.append(
            Check(
                "people",
                Level.WARN,
                "none seen",
                "Nobody appeared during the sample; repeat during busy hours before deciding.",
            )
        )
        rep.not_supported = list(USE_CASE_MIN_PERSON_PX)
        return rep

    typical = statistics.median(heights)
    small = sorted(heights)[max(0, int(len(heights) * 0.1) - 1)]
    level = Level.OK if typical >= 60 else Level.WARN if typical >= 40 else Level.FAIL
    c.append(
        Check(
            "person size",
            level,
            f"median {typical:.0f} px, smallest 10% {small:.0f} px",
            ""
            if level is Level.OK
            else "People are small in the image: zoom, move the camera closer, or use a higher-resolution stream.",
        )
    )
    for use_case, need in USE_CASE_MIN_PERSON_PX.items():
        (rep.supported if typical >= need else rep.not_supported).append(use_case)
    return rep


def survey_frames(
    frames: list[Frame],
    detections: list[list[Detection]],
    source: str,
    seconds: float,
    target_fps: float,
) -> SurveyReport:
    images = [f.image for f in frames if f.image is not None]
    heights = [h for dets in detections for h in person_heights(dets)]
    max_people = max(
        (sum(1 for d in dets if d.class_name == "person") for dets in detections), default=0
    )
    w = frames[0].width if frames else 0
    h = frames[0].height if frames else 0
    # Brightness and sharpness on at most 60 evenly spaced frames to stay fast.
    step = max(1, len(images) // 60)
    sample = images[::step]
    return evaluate(
        source,
        len(frames),
        seconds,
        w,
        h,
        [brightness_of(i) for i in sample],
        [sharpness_of(i) for i in sample],
        heights,
        max_people,
        target_fps,
    )


def format_report(rep: SurveyReport) -> str:
    icon = {Level.OK: "OK  ", Level.WARN: "WARN", Level.FAIL: "FAIL"}
    lines = [f"Camera survey: {rep.source}", f"Verdict: {rep.verdict.value.upper()}", ""]
    for chk in rep.checks:
        lines.append(f"  {icon[chk.level]}  {chk.name:<12} {chk.value}")
        if chk.advice:
            lines.append(f"        -> {chk.advice}")
    lines.append("")
    lines.append(f"Max people in one frame: {rep.max_people_in_frame}")
    if rep.supported:
        lines.append("Supports: " + "; ".join(rep.supported))
    if rep.not_supported:
        lines.append("Not suitable for: " + "; ".join(rep.not_supported))
    return "\n".join(lines)
