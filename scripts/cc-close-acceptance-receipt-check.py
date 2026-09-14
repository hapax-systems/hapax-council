#!/usr/bin/env python3
"""cc-close-acceptance-receipt-check — closure receipt gate.

Routing Phase 0.2 (REQ-20260609): a declared review requirement is only honest
if acceptance is enforced. Reads a cc-task .md file and returns:

- exit 0 when the task carries **no receipt-arming declaration**. Two
  declarations arm the gate, either sufficient: ``quality_floor:
  frontier_review_required`` and ``review_requirement.
  independent_review_required`` (each read top-level and in the
  ``route_metadata`` mirror). A row is untouched only when neither applies —
  the floor alone is no longer the test, because a row may demand independent
  review under any floor and a ``verification_receipt`` row that did exactly
  that closed unreviewed (measured 2026-09-13T21:53Z).
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
    RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
    RECEIPT_TRIGGER_MALFORMED_REVIEW,
    RECEIPT_TRIGGER_REVIEW_FLOOR,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    acceptance_receipt_triggers,
    frontmatter_from_text,
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
    triggers = acceptance_receipt_triggers(frontmatter)
    if not triggers:
        return 0, "no receipt-arming declaration — acceptance-receipt gate does not apply"

    blockers = acceptance_receipt_blockers(frontmatter, path)
    if not blockers:
        return 0, "valid acceptance receipt present"

    task_id = str(frontmatter.get("task_id") or path.stem)
    receipt = acceptance_receipt_path(path, task_id)
    # Name what armed the gate, one sentence per trigger. A lane reading a
    # generic receipt error on a non-review floor cannot tell a misfire from its
    # own row's demand, and a row carrying both triggers needs both reasons.
    demands: list[str] = []
    if RECEIPT_TRIGGER_REVIEW_FLOOR in triggers:
        demands.append(
            "quality_floor is frontier_review_required, which closes only after a signed review."
        )
    if RECEIPT_TRIGGER_INDEPENDENT_REVIEW in triggers:
        demands.append(
            "This row declares review_requirement.independent_review_required, so it closes"
            " only after an independent review — whatever its quality_floor."
        )
    if RECEIPT_TRIGGER_MALFORMED_REVIEW in triggers:
        demands.append(
            "review_requirement.independent_review_required is present but not a recognized"
            " boolean, so its intent cannot be read. An unreadable review requirement arms the"
            " gate rather than disabling it. Fix the declaration (true/false) to resolve this."
        )
    lines = [
        f"cc-close BLOCKED: task '{task_id}' lacks a valid acceptance receipt.",
        f"Armed by: {', '.join(triggers)}",
        "",
        *(f"  - {blocker}" for blocker in blockers),
        "",
        *demands,
        "Have the",
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
