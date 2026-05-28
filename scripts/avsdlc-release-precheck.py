#!/usr/bin/env python3
"""avsdlc-release-precheck.py — keystroke-time release-evidence precheck.

Mirrors the release blockers that ``scripts/cc-pr-autoqueue.py``
(``_task_blockers``) applies minutes later at the autoqueue timer, so the
same verdict is visible immediately when a session runs ``gh pr create`` /
``gh pr merge``. It reuses ``shared.release_gate.evaluate_avsdlc_release_gate``
verbatim — there is no second implementation of the AVSDLC logic here.

Usage::

    avsdlc-release-precheck.py <task-note-path> [--merge]

Exit codes (consumed by ``hooks/scripts/pr-release-gate.sh``):
    0 — clean, no release blockers
    1 — real release blockers (printed to stderr, one per line)
    3 — infrastructure/usage error (note missing, unparseable, import
        failure); the caller degrades this to a non-blocking advisory.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The script lives at <repo>/scripts/, so the repo root is its parent's
# parent. Put it on sys.path so ``shared`` imports resolve when invoked
# directly; the heavy deps (pydantic, pyyaml) come from the project venv
# via ``uv run``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_NULLISH = {"", "null", "none", "~", "[]", "{}"}


def _is_nullish(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return not value
    return str(value).strip().lower() in _NULLISH


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def main(argv: list[str]) -> int:
    try:
        positional = [a for a in argv if not a.startswith("--")]
        flags = {a for a in argv if a.startswith("--")}
        if not positional:
            print("avsdlc-release-precheck: usage: <task-note> [--merge]", file=sys.stderr)
            return 3
        note_path = Path(positional[0])
        is_merge = "--merge" in flags
        if not note_path.is_file():
            print(f"avsdlc-release-precheck: task note not found: {note_path}", file=sys.stderr)
            return 3

        # Lazy imports so a broken venv degrades to exit 3 (advisory) rather
        # than crashing with an opaque traceback at module load.
        from shared.frontmatter import parse_frontmatter
        from shared.release_gate import evaluate_avsdlc_release_gate

        frontmatter, _ = parse_frontmatter(note_path)
        if not frontmatter:
            print(
                f"avsdlc-release-precheck: no parseable frontmatter in {note_path}",
                file=sys.stderr,
            )
            return 3

        blockers: list[str] = []

        # Mirror cc-pr-autoqueue `_task_blockers` core authority fields.
        if _is_nullish(frontmatter.get("authority_case")) and _is_nullish(
            frontmatter.get("case_id")
        ):
            blockers.append("task_missing_authority_case")
        if _is_nullish(frontmatter.get("parent_spec")):
            blockers.append("task_missing_parent_spec")
        if str(frontmatter.get("route_metadata_schema", "")).strip() != "1":
            blockers.append("task_missing_route_metadata_schema_1")

        # AVSDLC evidence gate — canonical function, reused verbatim.
        avsdlc = evaluate_avsdlc_release_gate(frontmatter)
        blockers.extend(f"avsdlc_release_gate:{b}" for b in avsdlc.blockers)

        # A merge IS a release. Require explicit release authorization.
        if is_merge and not _is_true(frontmatter.get("release_authorized")):
            blockers.append("release_not_authorized")

        if blockers:
            print(
                f"avsdlc-release-precheck: {len(blockers)} release blocker(s):",
                file=sys.stderr,
            )
            for blocker in blockers:
                print(f"  - {blocker}", file=sys.stderr)
            return 1
        return 0
    except Exception as exc:  # infra: import/runtime — caller degrades to advisory
        print(f"avsdlc-release-precheck: precheck error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
