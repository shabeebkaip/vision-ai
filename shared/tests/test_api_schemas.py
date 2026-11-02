from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from vision_shared.api import (
    AggregateRow,
    EventBatch,
    Heartbeat,
    HeartbeatResponse,
    UploadRequest,
)

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


def test_heartbeat_needs_aware_times() -> None:
    Heartbeat(sent_at=NOW, cameras=[{"camera_id": "c", "status": "online", "last_frame_at": NOW}])
    with pytest.raises(ValidationError):
        Heartbeat(sent_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        Heartbeat(
            sent_at=NOW,
            cameras=[{"camera_id": "c", "status": "online", "last_frame_at": datetime(2026, 1, 1)}],
        )


def test_requests_forbid_unknown_fields_responses_ignore_them() -> None:
    with pytest.raises(ValidationError):
        Heartbeat(sent_at=NOW, surprise=1)  # type: ignore[call-arg]
    resp = HeartbeatResponse.model_validate(
        {"server_time": NOW, "config_version": 3, "config_etag": "e", "added_later": True}
    )
    assert resp.config_version == 3


def test_aggregate_minute_must_be_whole_and_aware() -> None:
    AggregateRow(camera_id="c", minute=NOW, metric="occupancy", value=1.5)
    with pytest.raises(ValidationError):
        AggregateRow(camera_id="c", minute=NOW.replace(second=5), metric="occupancy", value=1)
    with pytest.raises(ValidationError):
        AggregateRow(camera_id="c", minute=NOW.replace(tzinfo=None), metric="occupancy", value=1)
    with pytest.raises(ValidationError):
        AggregateRow(camera_id="c", minute=NOW, metric="faces", value=1)


def test_batches_and_uploads_are_not_empty() -> None:
    with pytest.raises(ValidationError):
        EventBatch(events=[])
    with pytest.raises(ValidationError):
        UploadRequest(kinds=[])
    assert UploadRequest(kinds=["snapshot", "clip"]).kinds[1].value == "clip"
