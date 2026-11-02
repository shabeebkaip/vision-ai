Run the video regression suite and explain the result.

1. Run `uv run vision-eval run --out var/eval` (add `--baseline test-videos/baseline.json` if that file exists).
2. Show the scorecard table.
3. For every missed event or false alert, open the clip entry in `test-videos/manifest.yaml`, say which rule
   and time it concerns, and propose the most likely cause (threshold, zone geometry, tracker, schedule).
4. Do not change expected results in the manifest to make a test pass. Expected results describe what
   really happens in the footage; change the code or the rule config instead.
