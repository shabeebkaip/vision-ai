#!/usr/bin/env python3
"""Licence guard (task REP-07).

Fails if any installed Python package is banned by name, or carries a copyleft / non-commercial
licence. Run inside the project environment:  uv run python scripts/licence_check.py

Our own workspace packages (vision-*) are skipped. Packages whose metadata does not state a licence
are reported as warnings so a human checks them once and adds them to KNOWN_OK.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import Distribution, distributions

BANNED_NAMES = {
    "ultralytics",  # AGPL-3.0; commercial use needs a paid Enterprise licence
    "ultralytics-thop",
    "boxmot",  # AGPL-3.0
    "deep-sort",
    "deep-sort-realtime",  # GPL-3.0 lineage
    "yolo-world",  # GPL-3.0
    "super-gradients",  # YOLO-NAS weights are non-commercial
    "rfdetr-plus",  # PML-1.0 (RF-DETR Atto/Femto/Pico/XL/2XL), needs a paid Roboflow licence
    "deimv2",
}

ALLOWED = re.compile(
    r"\b(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|MPL|Mozilla Public License|"
    r"Unlicense|CC0|Zlib|HPND|Historical Permission|0BSD|Public Domain|LGPL)\b",
    re.IGNORECASE,
)
FORBIDDEN = re.compile(
    r"\b(AGPL|Affero|GPL-?[23]|GNU General Public|SSPL|Business Source|BSL-1|"
    r"Non-?Commercial|CC-BY-NC|PML)\b",
    re.IGNORECASE,
)
# Checked by hand: metadata is missing or ambiguous but the licence is permissive.
KNOWN_OK: dict[str, str] = {
    # Full licence text in metadata mentions bundled GPL-compatible notices; scipy itself is BSD-3.
    "scipy": "BSD-3-Clause",
}


def licence_text(dist: Distribution) -> str:
    meta = dist.metadata
    parts = [meta.get("License-Expression") or "", meta.get("License") or ""]
    parts += [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    return " | ".join(p for p in parts if p)


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for dist in distributions():
        name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
        if not name or name in seen or name.startswith("vision-") or name == "codeox-vision":
            continue
        seen.add(name)
        if name in BANNED_NAMES:
            failures.append(f"{name}: banned package")
            continue
        if name in KNOWN_OK:
            continue
        text = licence_text(dist)
        # Strip "LGPL" before checking for GPL so LGPL (dynamic linking) is not flagged as GPL.
        if FORBIDDEN.search(re.sub(r"LGPL[-\w.]*|Lesser General Public", "", text, flags=re.I)):
            failures.append(f"{name}: {text[:120]}")
        elif not ALLOWED.search(text):
            warnings.append(f"{name}: licence not recognised ({text[:80] or 'no metadata'})")
    for w in sorted(warnings):
        print(f"WARN  {w}")
    for f in sorted(failures):
        print(f"FAIL  {f}")
    print(f"checked {len(seen)} packages: {len(failures)} failure(s), {len(warnings)} warning(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
