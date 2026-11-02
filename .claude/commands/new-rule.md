Add a new rule type: $ARGUMENTS

Follow "Adding a new rule type" in CLAUDE.md exactly:
1. Write a short plan first (fields, condition, clear behaviour, message text) and show it.
2. Add the `RuleType` value and any `Rule` fields with validation in `shared/src/vision_shared/schemas.py`.
3. Implement the evaluator in `edge/src/vision_edge/rules/`, register it in `EVALUATORS`.
4. Unit tests: fires after the minimum duration, not before, clears, respects cooldown and schedule.
5. Add a synthetic scenario in `ml/src/vision_ml/tools/synthetic.py` with positive and negative cases,
   regenerate the manifest with `uv run vision-eval synth --write-manifest test-videos/manifest.yaml`.
6. Run ruff, mypy, pytest and `uv run vision-eval run --strict`.
