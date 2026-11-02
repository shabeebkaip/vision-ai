"""`vision-eval` command line.

vision-eval synth --write-manifest test-videos/manifest.yaml
vision-eval run                                   # score everything in test-videos/manifest.yaml
vision-eval run --tag synthetic --baseline test-videos/baseline.json
vision-eval run --detector rfdetr-nano            # re-detect from video instead of cached detections
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vision_edge.logs import configure_logging
from vision_ml.eval.harness import (
    compare_baseline,
    load_json,
    results_json,
    run_manifest,
    score,
    scorecard_markdown,
)
from vision_ml.tools.synthetic import write_manifest, write_scenarios
from vision_shared.manifest import load_manifest

DEFAULT_MANIFEST = Path("test-videos/manifest.yaml")


def _ensure_synthetic(manifest_path: Path) -> None:
    """Synthetic clips are generated on demand (deterministic), never committed."""
    manifest = load_manifest(manifest_path)
    base = manifest_path.parent
    missing = [
        c.id for c in manifest.clips
        if "synthetic" in c.tags and c.detections and not (base / c.detections).exists()
    ]  # fmt: skip
    if missing:
        write_scenarios(base / "synthetic", only=missing)


def cmd_synth(args: argparse.Namespace) -> int:
    if args.write_manifest:
        write_manifest(Path(args.write_manifest))
        print(f"wrote {args.write_manifest}")
    paths = write_scenarios(Path(args.out), video=args.video)
    print(
        f"wrote {len(paths)} synthetic scenario(s) to {args.out}"
        + (" with videos" if args.video else "")
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    _ensure_synthetic(manifest_path)
    manifest = load_manifest(manifest_path)
    results = run_manifest(
        manifest, manifest_path.parent, args.detector, args.model, args.only, args.tag
    )
    scores = score(results)
    regressions: list[str] = []
    if args.baseline and Path(args.baseline).exists():
        regressions = compare_baseline(scores, load_json(Path(args.baseline)))
    md = scorecard_markdown(results, scores, regressions)
    print(md)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.md").write_text(md, encoding="utf-8")
    payload = results_json(results, scores)
    (out / "results.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    if args.save_baseline:
        Path(args.save_baseline).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        print(f"baseline saved to {args.save_baseline}")
    errors = [r for r in results if r.error]
    if regressions:
        print("REGRESSION against baseline")
        return 1
    if args.strict and any(r.missed or r.false_alerts for r in results):
        print("STRICT: at least one clip missed an event or raised a false alert")
        return 1
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    p = argparse.ArgumentParser(
        prog="vision-eval", description="Score the pipeline against test clips"
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("synth", help="generate synthetic scenarios")
    s.add_argument("--out", default="test-videos/synthetic")
    s.add_argument("--video", action="store_true", help="also render MP4 videos")
    s.add_argument("--write-manifest", help="(re)write the synthetic section of a manifest file")

    r = sub.add_parser("run", help="run the harness")
    r.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    r.add_argument(
        "--detector", default="auto", help="auto (cached detections) | rfdetr-nano | onnx | ..."
    )
    r.add_argument("--model")
    r.add_argument("--only", nargs="*")
    r.add_argument("--tag", nargs="*")
    r.add_argument("--baseline", help="fail on regression against this results.json")
    r.add_argument("--save-baseline")
    r.add_argument("--out", default="var/eval")
    r.add_argument("--strict", action="store_true", help="fail on any miss or false alert")

    args = p.parse_args(argv)
    if args.command == "synth":
        return cmd_synth(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
