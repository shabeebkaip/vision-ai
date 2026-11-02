"""User-facing strings in English and Arabic (every key must exist in both files)."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

LANGUAGES = ("en", "ar")


@cache
def strings(lang: str) -> dict[str, str]:
    data: dict[str, str] = json.loads(files(__name__).joinpath(f"{lang}.json").read_text("utf-8"))
    return data


def t(lang: str, key: str, **kwargs: Any) -> str:
    table = strings(lang if lang in LANGUAGES else "en")
    return table.get(key, strings("en")[key]).format(**kwargs)
