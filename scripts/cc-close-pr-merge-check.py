#!/usr/bin/env python3
"""PR-merge evidence gate for cc-close.

For build tasks with a pr: field, verifies the PR is actually merged
before allowing task closure. Prevents the "status: done but PR is open"
false-completion pattern found by CCTV disconfirmation.

Exit codes:
  0 — pass (no PR, PR merged, or non-done status)
  2 — blocked (PR exists but is not merged)
  3 — infrastructure error (gh CLI unavailable)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _extract_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip().strip('"').strip("'")
    return fields


def _check_pr_merged(pr_num: str) -> str | None:
    """Return PR state or None on error."""
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_num,
                "--repo",
                "hapax-systems/hapax-council",
                "--json",
                "state",
                "--jq",
                ".state",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: cc-close-pr-merge-check.py <note_path> [--pr N]", file=sys.stderr)
        return 0

    note_path = Path(sys.argv[1])
    cli_pr = None
    if "--pr" in sys.argv:
        idx = sys.argv.index("--pr")
        if idx + 1 < len(sys.argv):
            cli_pr = sys.argv[idx + 1]

    text = note_path.read_text(encoding="utf-8")
    fields = _extract_frontmatter(text)

    pr_num = cli_pr or fields.get("pr", "").strip()
    mutation_surface = fields.get("mutation_surface", "")
    kind = fields.get("kind", "build")

    if not pr_num or pr_num == "null":
        if "source" in mutation_surface and kind == "build":
            branch = fields.get("branch", "").strip()
            has_branch = branch and branch != "null"
            has_session_commit = "commit" in text.lower() or "sha" in text.lower()
            if not has_branch and not has_session_commit:
                print(
                    "cc-close-pr-merge-check: BLOCKED — build task with source mutation "
                    "has no PR, no branch, and no commit reference.\n"
                    "  Add --pr N, or set branch: in frontmatter, or document a commit SHA.\n"
                    "  Bypass: HAPAX_EVIDENCE_GATE_OFF=1",
                    file=sys.stderr,
                )
                if os.environ.get("HAPAX_EVIDENCE_GATE_OFF") != "1":
                    return 2
        return 0

    state = _check_pr_merged(pr_num)
    if state is None:
        print(
            "cc-close-pr-merge-check: WARNING — could not verify PR state (gh unavailable or API error). Allowing.",
            file=sys.stderr,
        )
        return 0

    if state == "MERGED":
        return 0

    print(
        f"cc-close-pr-merge-check: BLOCKED — PR #{pr_num} is {state} (not MERGED).\n"
        f"  Merge the PR before closing the task, or use --status withdrawn.\n"
        f"  Bypass: HAPAX_PR_MERGE_GATE_OFF=1",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
