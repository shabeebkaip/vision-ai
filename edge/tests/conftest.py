from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

T0 = datetime(2026, 1, 4, 6, 0, tzinfo=timezone.utc)  # Sunday 09:00 Riyadh


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def t0() -> datetime:
    return T0
