"""Alert dispatch (CLD-08). Placeholder handlers for the jobs the API enqueues today.

The dispatcher proper (recipients, grouping, quiet hours, caps, escalation, delivery log) replaces
these in CLD-08; until then the jobs run and are acknowledged so the queue stays empty.
"""

from __future__ import annotations

from typing import Any

import structlog

from vision_cloud.worker import WorkerContext, handler

log = structlog.get_logger(__name__)


@handler("event.created")
@handler("event.cleared")
@handler("event.media_ready")
def not_dispatched_yet(ctx: WorkerContext, payload: dict[str, Any]) -> None:
    log.info("dispatch.skipped", reason="alert dispatcher arrives with CLD-08")
