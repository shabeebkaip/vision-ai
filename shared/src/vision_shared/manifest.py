"""Test-clip manifest (task VID-02).

Each clip carries the camera geometry, the rules to run and the alerts it must (and must not)
produce. The harness in `vision_ml.eval` scores the pipeline against it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from vision_shared.schemas import Line, Rule, Zone


class ExpectedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str = Field(description="rule id within this clip")
    start_s: float = Field(ge=0, description="when the condition becomes true in the clip")
    end_s: float = Field(ge=0)
    tolerance_s: float = Field(default=15.0, ge=0)

    @model_validator(mode="after")
    def _order(self) -> ExpectedEvent:
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")
        return self


class ClipEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    file: str | None = Field(default=None, description="video path or s3:// key")
    detections: str | None = Field(
        default=None,
        description="cached detections JSONL (replay); lets the harness run without the model",
    )
    source: str = Field(
        description="where the footage came from, and its consent letter or licence"
    )
    scene: str = ""
    angle: str = ""
    lighting: str = "day"
    resolution: str = ""
    fps: float = Field(default=5.0, gt=0)
    start_time: datetime | None = Field(
        default=None, description="wall-clock time of the clip's first frame (for schedules)"
    )
    timezone: str = "Asia/Riyadh"
    duration_s: float | None = Field(default=None, gt=0)
    tags: list[str] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    expected: list[ExpectedEvent] = Field(default_factory=list)
    must_not_fire: list[str] = Field(
        default_factory=list, description="rule ids that must stay quiet"
    )
    notes: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> ClipEntry:
        if not self.file and not self.detections:
            raise ValueError(f"clip {self.id}: needs a video file or a detections file")
        rule_ids = {r.id for r in self.rules}
        for e in self.expected:
            if e.rule not in rule_ids:
                raise ValueError(f"clip {self.id}: expected event references unknown rule {e.rule}")
        for rid in self.must_not_fire:
            if rid not in rule_ids:
                raise ValueError(f"clip {self.id}: must_not_fire references unknown rule {rid}")
        geometry = {z.id for z in self.zones} | {ln.id for ln in self.lines}
        for r in self.rules:
            for ref in (r.zone_id, r.line_id):
                if ref and ref not in geometry:
                    raise ValueError(
                        f"clip {self.id}: rule {r.id} references unknown zone/line {ref}"
                    )
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    clips: list[ClipEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> Manifest:
        ids = [c.id for c in self.clips]
        if len(ids) != len(set(ids)):
            raise ValueError("clip ids must be unique")
        return self


def load_manifest(path: str | Path) -> Manifest:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Manifest.model_validate(data)
