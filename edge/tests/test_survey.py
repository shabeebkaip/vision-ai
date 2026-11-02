from __future__ import annotations

import numpy as np

from vision_edge.survey import Level, brightness_of, evaluate, format_report, sharpness_of


def _report(**kw: object):  # type: ignore[no-untyped-def]
    base: dict[str, object] = dict(
        source="cam", frames=600, seconds=120.0, width=1280, height=720,
        brightness=[120.0], sharpness=[200.0], heights=[150.0] * 50, max_people=4, target_fps=5.0,
    )  # fmt: skip
    base.update(kw)
    return evaluate(**base)  # type: ignore[arg-type]


def test_good_camera_supports_everything() -> None:
    rep = _report()
    assert rep.verdict is Level.OK
    assert "PPE: helmet and vest" in rep.supported
    assert "kitchen hygiene: hairnet and gloves" in rep.supported


def test_small_people_limit_use_cases() -> None:
    rep = _report(heights=[45.0] * 50)
    assert rep.verdict is Level.WARN
    assert "people counting, zones, queues, after-hours" in rep.supported
    assert "PPE: helmet and vest" in rep.not_supported


def test_too_small_fails() -> None:
    assert _report(heights=[25.0] * 50).verdict is Level.FAIL


def test_low_resolution_and_fps_fail() -> None:
    assert _report(width=352, height=288).verdict is Level.FAIL
    assert _report(frames=200).verdict is Level.FAIL  # 1.7 fps against a 5 fps target


def test_dark_scene_fails_and_no_frames_fails() -> None:
    assert _report(brightness=[20.0]).verdict is Level.FAIL
    rep = _report(frames=0)
    assert rep.verdict is Level.FAIL
    assert "FAIL" in format_report(rep)


def test_image_measures() -> None:
    flat = np.full((720, 1280, 3), 128, np.uint8)
    noisy = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    assert abs(brightness_of(flat) - 128) < 1
    assert sharpness_of(flat) < 1 < sharpness_of(noisy)
