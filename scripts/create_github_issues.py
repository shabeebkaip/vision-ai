#!/usr/bin/env python3
"""Create one GitHub issue per task in tasks/tasks.csv.

Usage:
    python3 scripts/create_github_issues.py              # dry run: prints what it would create
    python3 scripts/create_github_issues.py --apply      # creates labels and issues with the GitHub CLI
    python3 scripts/create_github_issues.py --apply --phase 0 1 2   # only some phases

Needs the GitHub CLI (`gh`) logged in with access to this repository.
Issues whose title already starts with "[TASK-ID]" are skipped, so the script can be re-run safely.
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "tasks" / "tasks.csv"

DEFINITION_OF_DONE = """### Definition of done
- [ ] Merged to `main` through a reviewed pull request
- [ ] Unit tests passing in CI; video regression suite passing if detection, tracking or rules are touched
- [ ] Runs inside its Docker container
- [ ] No library outside the approved list (licence check green)
- [ ] No hard-coded secrets, IPs or customer names
- [ ] User-facing text in English and Arabic
- [ ] Docs updated if behaviour, setup or an API changed
- [ ] Shown in the weekly demo"""

OWNER_LABELS = {
    "PO": "owner: PO",
    "LD": "owner: LD",
    "CV": "owner: CV",
    "BE": "owner: BE",
    "FE": "owner: FE",
    "DO": "owner: DO",
    "QA": "owner: QA",
    "FLD": "owner: FLD",
}
COLOURS = {
    "phase": "1d76db",
    "priority: Must": "b60205",
    "priority: Should": "fbca04",
    "priority: Could": "c5def5",
    "owner": "5319e7",
}


def gh(*args, capture=True):
    return subprocess.run(["gh", *args], check=True, text=True, capture_output=capture).stdout


def labels_for(row):
    labels = [f"phase {int(row['phase']):02d}", f"priority: {row['priority']}"]
    for code in [c.strip() for c in row["owner"].replace("+", ",").split(",")]:
        code = code.split(" ")[0]
        if code in OWNER_LABELS:
            labels.append(OWNER_LABELS[code])
    return labels


def body_for(row):
    parts = [f"**Phase {row['phase']} — {row['phase_name']}**", ""]
    if row["details"]:
        parts += [f"**Details:** {row['details']}", ""]
    parts += [
        "| Owner | Estimate (developer-days) | Priority | Depends on |",
        "| --- | --- | --- | --- |",
        f"| {row['owner'] or '-'} | {row['days'] or row['size'] or '-'} | {row['priority']} | {row['depends_on'] or '-'} |",
        "",
        f"**Done when:** {row['done_when'] or 'see plan'}",
        "",
        DEFINITION_OF_DONE,
        "",
        "Source: [docs/development-task-plan.md](../blob/main/docs/development-task-plan.md)",
    ]
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually create labels and issues")
    ap.add_argument("--phase", nargs="*", type=int, help="only these phase numbers")
    a = ap.parse_args()

    rows = list(csv.DictReader(CSV.open()))
    if a.phase is not None:
        rows = [r for r in rows if int(r["phase"]) in a.phase]

    if not a.apply:
        for r in rows:
            print(f"[{r['id']}] {r['title'][:90]}  ->  {', '.join(labels_for(r))}")
        print(f"\n{len(rows)} issues would be created. Re-run with --apply to create them.")
        return

    existing = json.loads(
        gh("issue", "list", "--state", "all", "--limit", "1000", "--json", "title")
    )
    done = {i["title"].split("]")[0] + "]" for i in existing if i["title"].startswith("[")}

    wanted = sorted({lb for r in rows for lb in labels_for(r)})
    have = {
        item["name"] for item in json.loads(gh("label", "list", "--limit", "500", "--json", "name"))
    }
    for label in wanted:
        if label not in have:
            colour = next((c for k, c in COLOURS.items() if label.startswith(k)), "ededed")
            gh("label", "create", label, "--color", colour)

    for r in rows:
        if f"[{r['id']}]" in done:
            print(f"skip   [{r['id']}] already exists")
            continue
        title = f"[{r['id']}] {r['title']}"
        if len(title) > 240:
            title = title[:237] + "..."
        args = ["issue", "create", "--title", title, "--body", body_for(r)]
        for lb in labels_for(r):
            args += ["--label", lb]
        url = gh(*args).strip()
        print(f"create [{r['id']}] {url}")


if __name__ == "__main__":
    sys.exit(main())
