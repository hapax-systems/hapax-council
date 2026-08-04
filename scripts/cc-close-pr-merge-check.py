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

# Standalone scripts do not inherit the repo root on sys.path; siblings (cc-pr-autoqueue) do the
# same. Without it `shared.cc_task_pr_link` is unimportable and the gate dies before it can gate,
# which is a fail-OPEN in a wrapper that only checks the exit code.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.cc_task_pr_link import (
    frontmatter,
    is_nullish,
    is_well_formed_repo,
    unquote,
)

DEFAULT_PR_REPO = "hapax-systems/hapax-council"


def _extract_frontmatter(text: str) -> dict[str, str]:
    """Frontmatter fields, using THE SAME extractor the watcher uses.

    This had its own parser: it opened on any `---` prefix and closed at any `\n---`, so the two
    gates disagreed about where a note's frontmatter ended -- and disagreement between these two
    gates about the same note is the failure the whole change removes. `shared.cc_task_pr_link`
    now owns the block boundary and the scalar normalization; only the field split is local.
    """
    fields: dict[str, str] = {}
    for line in frontmatter(text).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = unquote(v)
    return fields


def _nullish(value: str) -> bool:
    """Delegates to the one definition, so this gate and the watcher cannot disagree."""
    return is_nullish(value)


def _check_pr_merged(pr_num: str, repo: str = DEFAULT_PR_REPO) -> str | None:
    """Return PR state or None on error."""
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                pr_num,
                "--repo",
                repo,
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
        print(
            "usage: cc-close-pr-merge-check.py <note_path> [--pr N] [--repo OWNER/REPO]",
            file=sys.stderr,
        )
        return 0

    note_path = Path(sys.argv[1])
    cli_pr = None
    cli_repo = None
    if "--pr" in sys.argv:
        idx = sys.argv.index("--pr")
        if idx + 1 < len(sys.argv):
            cli_pr = sys.argv[idx + 1]
    if "--repo" in sys.argv:
        idx = sys.argv.index("--repo")
        if idx + 1 < len(sys.argv):
            cli_repo = sys.argv[idx + 1]

    text = note_path.read_text(encoding="utf-8")
    fields = _extract_frontmatter(text)

    pr_num = cli_pr or fields.get("pr", "").strip()
    pr_repo = cli_repo or fields.get("pr_repo", "").strip()
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

    # THE REPOSITORY IS ONLY REQUIRED ONCE A PR EXISTS, and this check used to run before the
    # no-PR path above. A task with `pr: null` was blocked for lacking a repository -- a field with
    # no meaning when there is no PR -- which wedged the legitimate branch/commit evidence flow.
    # Found in review. Order is part of a gate's correctness, not a detail of it.
    bypassed = os.environ.get("HAPAX_PR_MERGE_GATE_OFF") == "1"

    if _nullish(pr_repo) or not is_well_formed_repo(pr_repo):
        # NOT DEFAULTED, AND NOT GUESSED UNDER BYPASS EITHER.
        #
        # Resolving an absent pr_repo to the council repo closed a task meaning reins#6 against a
        # merged hapax-council#6 while the real PR was still open. Twice, 2026-08-04.
        #
        # A malformed value is refused for a related reason a reviewer found: "garbage" reaches gh,
        # the lookup fails, and the failure path below reads that as "could not verify, allowing".
        # A typo became an unverified closure. Shape is checkable without the network, so it is
        # checked before the network.
        why = "no 'pr_repo'" if _nullish(pr_repo) else "a malformed 'pr_repo' (want owner/name)"
        if bypassed:
            # The bypass DECLINES TO VERIFY. It does not pick a repository and check against that
            # -- guessing is the defect this gate exists to prevent, and a bypass that reintroduces
            # it silently is worse than no bypass, because the run still looks verified.
            print(
                f"cc-close-pr-merge-check: NOT VERIFIED — {why}, and HAPAX_PR_MERGE_GATE_OFF=1.\n"
                f"  No PR was checked. This closure carries no merge evidence.",
                file=sys.stderr,
            )
            return 0
        print(
            f"cc-close-pr-merge-check: BLOCKED — task declares 'pr: {pr_num}' with {why}.\n"
            f"  A bare number is not a link: PR #{pr_num} exists in more than one repository of "
            f"this estate, and guessing one would risk closing a task whose PR is still open.\n"
            f"  Add 'pr_repo: <owner>/<name>' to the task note, or pass --repo <owner>/<name>.\n"
            f"  Bypass (closes with NO merge evidence): HAPAX_PR_MERGE_GATE_OFF=1",
            file=sys.stderr,
        )
        return 2

    state = _check_pr_merged(pr_num, pr_repo)
    if state is None:
        # "COULD NOT VERIFY" IS NOT "VERIFIED". This allowed the closure, which is the same
        # absence-into-zero shape as the repository default -- and it is reachable from a typo,
        # since a malformed repo makes every lookup fail. The shape check above closes that route;
        # this closes the rest, and the bypass remains for a genuinely offline operator.
        if os.environ.get("HAPAX_PR_MERGE_GATE_OFF") == "1":
            print(
                f"cc-close-pr-merge-check: NOT VERIFIED — could not reach {pr_repo}#{pr_num}, and "
                f"HAPAX_PR_MERGE_GATE_OFF=1. This closure carries no merge evidence.",
                file=sys.stderr,
            )
            return 0
        print(
            f"cc-close-pr-merge-check: BLOCKED — could not verify {pr_repo}#{pr_num} "
            f"(gh unavailable, no network, or the repository does not exist).\n"
            f"  An unverifiable PR is not a merged one. Check the repository name, restore access, "
            f"or close with no merge evidence via HAPAX_PR_MERGE_GATE_OFF=1.",
            file=sys.stderr,
        )
        return 2

    if state == "MERGED":
        return 0

    print(
        f"cc-close-pr-merge-check: BLOCKED — PR {pr_repo}#{pr_num} is {state} (not MERGED).\n"
        f"  Merge the PR before closing the task, or use --status withdrawn.\n"
        f"  Bypass: HAPAX_PR_MERGE_GATE_OFF=1",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
