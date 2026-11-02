from __future__ import annotations

from pathlib import Path

from vision_ml.eval.harness import RuleTypeScore, compare_baseline, run_manifest, score
from vision_ml.tools.synthetic import manifest_entries, write_scenarios
from vision_shared.manifest import ExpectedEvent, load_manifest

REPO = Path(__file__).resolve().parents[2]


def test_committed_manifest_is_valid() -> None:
    m = load_manifest(REPO / "test-videos" / "manifest.yaml")
    assert len(m.clips) >= 7


def test_committed_manifest_matches_generator() -> None:
    committed = load_manifest(REPO / "test-videos" / "manifest.yaml")
    generated = manifest_entries()
    synthetic = [c for c in committed.clips if "synthetic" in c.tags]
    assert [c.model_dump() for c in synthetic] == [c.model_dump() for c in generated.clips]


def test_synthetic_suite_passes(tmp_path: Path) -> None:
    write_scenarios(tmp_path / "synthetic")
    results = run_manifest(manifest_entries(), tmp_path)
    assert not any(r.error for r in results)
    assert all(not r.missed and not r.false_alerts for r in results), [
        (r.clip_id, r.missed, r.false_alerts) for r in results
    ]
    scores = score(results)
    assert len(scores) == 6
    assert all(s.recall == 1.0 and s.precision == 1.0 for s in scores.values())


def test_wrong_expectation_counts_as_miss_and_false_alert(tmp_path: Path) -> None:
    write_scenarios(tmp_path / "synthetic", only=["syn-queue-001"])
    m = manifest_entries()
    clip = next(c for c in m.clips if c.id == "syn-queue-001")
    clip.expected = [ExpectedEvent(rule="queue", start_s=200, end_s=230, tolerance_s=5)]
    [r] = run_manifest(m, tmp_path, only=["syn-queue-001"])
    assert r.missed == ["queue"]
    assert len(r.false_alerts) == 1


def test_regression_detection() -> None:
    now = {"x": RuleTypeScore("x", caught=8, missed=2, false=0, camera_hours=1.0)}
    base = {"scores": {"x": {"recall": 0.95, "false_per_hour": 0.0}}}
    assert compare_baseline(now, base) == ["x: recall 95% -> 80%"]
    ok = {"x": RuleTypeScore("x", caught=19, missed=1, false=0, camera_hours=1.0)}
    assert compare_baseline(ok, base) == []
