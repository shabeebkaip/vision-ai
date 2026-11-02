#!/usr/bin/env python3
"""Export the shared pydantic schemas as one JSON Schema for the web dashboard (task WEB-01).

    uv run python scripts/export_json_schema.py            # writes web/src/api/schema.json
    uv run python scripts/export_json_schema.py --check    # exits 1 if the file is out of date

The dashboard generates `web/src/api/types.ts` from this file with json-schema-to-typescript
(`npm run gen:types` in `web/`). The schema describes the wire format the cloud sends, so every
field is marked required (pydantic always serialises defaults). Pydantic emits draft 2020-12
`prefixItems` for tuples such as `Point`; they are rewritten to the draft-07 tuple form that the
TypeScript generator understands, so a point becomes `[number, number]`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, models_json_schema
from pydantic_core import core_schema

from vision_shared.schemas import (
    SCHEMA_VERSION,
    CameraConfig,
    Detection,
    Event,
    Line,
    Rule,
    Schedule,
    SiteConfig,
    Zone,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "web" / "src" / "api" / "schema.json"
MODELS: list[type[BaseModel]] = [
    Zone,
    Line,
    Schedule,
    Rule,
    CameraConfig,
    SiteConfig,
    Detection,
    Event,
]


class WireSchema(GenerateJsonSchema):
    """Serialisation-mode schema in which every field is present on the wire."""

    def field_is_required(
        self,
        field: core_schema.ModelField | core_schema.DataclassField | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        if self.mode == "serialization":
            return True
        return super().field_is_required(field, total)


def _draft7(node: Any) -> Any:
    """Recursively turn `prefixItems` tuples into draft-07 `items: [...]` tuples and drop the
    per-field `title`s (they only make the TypeScript generator emit one alias type per field)."""
    if isinstance(node, dict):
        out: dict[str, Any] = {k: _draft7(v) for k, v in node.items() if k != "title"}
        if "prefixItems" in out:
            out["items"] = out.pop("prefixItems")
            out["additionalItems"] = False
        return out
    if isinstance(node, list):
        return [_draft7(v) for v in node]
    return node


def build_schema() -> dict[str, Any]:
    mode: JsonSchemaMode = "serialization"
    _, top = models_json_schema(
        [(m, mode) for m in MODELS],
        ref_template="#/definitions/{model}",
        schema_generator=WireSchema,
    )
    definitions: dict[str, Any] = {
        name: {**_draft7(schema), "title": name} for name, schema in top.get("$defs", {}).items()
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "VisionShared",
        "description": (
            f"Generated from vision_shared.schemas (schema_version {SCHEMA_VERSION}) by "
            "scripts/export_json_schema.py. Do not edit by hand."
        ),
        "type": "object",
        "additionalProperties": False,
        "properties": {
            name: {"$ref": f"#/definitions/{name}"} for name in sorted(definitions.keys())
        },
        "definitions": definitions,
    }


def render() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    out: Path = args.out
    text = render()
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != text:
            print(f"{out} is out of date: run scripts/export_json_schema.py", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
