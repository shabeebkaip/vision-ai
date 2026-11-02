"""Applies site config changes to a running camera pipeline (EDG-13).

The agent writes `site.json` atomically; `ConfigWatcher` runs after each frame, checks the file's
modification time every couple of seconds, and on change calls `CameraPipeline.reconfigure`.
A config that does not parse is logged and ignored (the pipeline keeps the last good one).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import structlog

from vision_edge.frames import Frame
from vision_edge.pipeline import CameraPipeline
from vision_shared.io import load_site

log = structlog.get_logger(__name__)


class RestartRequired(Exception):
    """The camera's stream settings changed; the process exits and its supervisor restarts it."""


class ConfigWatcher:
    def __init__(
        self,
        path: Path,
        *,
        check_every_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        on_applied: Callable[[int], None] | None = None,
    ) -> None:
        self.path = path
        self.check_every_s = check_every_s
        self.clock = clock
        self.on_applied = on_applied
        self._next_check = 0.0
        self._mtime = self._stat()

    def _stat(self) -> int | None:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def __call__(self, pipeline: CameraPipeline, frame: Frame) -> None:
        now = self.clock()
        if now < self._next_check:
            return
        self._next_check = now + self.check_every_s
        mtime = self._stat()
        if mtime is None or mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            site = load_site(self.path)
        except Exception as exc:  # malformed file: keep running on the last good config
            log.error("config.invalid", path=str(self.path), error=str(exc)[:300])
            return
        if site.version == pipeline.site.version and site == pipeline.site:
            return
        if not pipeline.reconfigure(site, now=frame.ts):
            raise RestartRequired(f"camera {pipeline.camera.id}: stream settings changed")
        if self.on_applied:
            self.on_applied(site.version)
