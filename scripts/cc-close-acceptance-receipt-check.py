#!/usr/bin/env python3
"""cc-close-acceptance-receipt-check — review-floor closure receipt gate.

Routing Phase 0.2 (REQ-20260609): ``frontier_review_required`` is only honest
if acceptance is enforced. Reads a cc-task .md file and returns:

- exit 0 when the task does not declare the review floor (top-level or
  ``route_metadata.quality_floor``) — non-review-floor flows are untouched.
- exit 0 when a valid signed acceptance receipt exists beside the note as
  ``<task_id>.acceptance.yaml`` carrying acceptor, verdict ``accepted``,
  timestamp, and an artifact ref.
- exit 2 when the receipt is missing, malformed, field-incomplete, or its
  verdict is not ``accepted`` — with the precise blockers and next actions
  on stderr.

Used by ``scripts/cc-close`` in the ``done`` path, before the note moves to
closed/. Verdicts other than ``accepted`` block: a rejected review is not a
closeable outcome.

Bypass: ``HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1`` (incident response only),
honored here so every caller shares one mechanism.

Failure mode: fail-OPEN on infrastructure errors reading the NOTE (missing /
unreadable file — a broken gate must not brick closures), but fail-CLOSED on
receipt problems (an absent or invalid receipt is exactly what this gate
exists to catch).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.sdlc_lifecycle import (  # noqa: E402
    ACCEPTANCE_RECEIPT_REQUIRED_FIELDS,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    frontmatter_from_text,
    requires_acceptance_receipt,
)


def gate(path: Path) -> tuple[int, str]:
    """Return ``(exit_code, message)``; 0 permits closure, 2 blocks it."""

    if os.environ.get("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF") == "1":
        return 0, "acceptance-receipt gate disabled by HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1"

    if not path.is_file():
        return 0, f"fail-OPEN: source path missing or not a file ({path})"

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return 0, f"fail-OPEN: source unreadable ({exc})"

    frontmatter = frontmatter_from_text(text)
    if not requires_acceptance_receipt(frontmatter):
        return 0, "not a review-floor task — acceptance-receipt gate does not apply"

    blockers = acceptance_receipt_blockers(frontmatter, path)
    if not blockers:
        return 0, "valid acceptance receipt present"

    task_id = str(frontmatter.get("task_id") or path.stem)
    receipt = acceptance_receipt_path(path, task_id)
    lines = [
        f"cc-close BLOCKED: review-floor task '{task_id}' lacks a valid acceptance receipt:",
        "",
        *(f"  - {blocker}" for blocker in blockers),
        "",
        "frontier_review_required work closes only after a signed review. Have the",
        "acceptor (frontier reviewer or operator) record the verdict at:",
        f"  {receipt}",
        "with the minimal schema (all fields required):",
        f"  {', '.join(ACCEPTANCE_RECEIPT_REQUIRED_FIELDS)}",
        "e.g.:",
        "  acceptor: operator",
        "  verdict: accepted",
        "  timestamp: 2026-06-10T17:00:00Z",
        "  artifact: <PR URL / review note / evidence path>",
        "",
        "A verdict other than 'accepted' keeps the task open — address the review",
        "feedback instead of closing.",
        "",
        "Bypass for incident response: HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1",
    ]
    return 2, "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: cc-close-acceptance-receipt-check.py <path-to-cc-task.md>", file=sys.stderr)
        return 64
    code, msg = gate(Path(argv[1]))
    if code != 0:
        print(msg, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
