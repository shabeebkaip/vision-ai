Check dependency licences.

Run `uv run python scripts/licence_check.py`. For any FAIL, explain which package pulled it in
(`uv tree --invert --package <name>`) and propose a permissive alternative from docs/approved-libraries.md.
For any WARN, find the real licence from the package's repository and, if permissive, add it to
KNOWN_OK in the script with a comment.
