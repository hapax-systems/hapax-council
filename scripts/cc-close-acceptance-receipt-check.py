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

KNOWN TENSION, recorded rather than silently carried (raised in review of
PR #4669). Widening the gate to arm on independent-review declarations grew the
blast radius of that fail-OPEN: an unreadable note on a review-demanding row now
closes unreviewed where previously only review-floor rows were exposed. It also
sits awkwardly beside this module's own rule that a present-but-unreadable
DECLARATION must never read as absent — the same principle would make an
existing-but-unreadable NOTE fail closed, distinguishing it from a genuinely
missing one.

It was deliberately NOT changed here. The behaviour is pre-existing, outside this
row's scope, and the availability tradeoff is real: this estate runs its task
SSOT on an NFS mount that has flapped, and failing closed on a transient read
error would wedge every closure during a blip. Changing a gate's availability
semantics under an unrelated row, during known mount instability, is how
incidents are made. The narrowing (fail-open only for MISSING, fail-closed for
unreadable) wants its own row and its own witness.

STATUS OF THAT DEFERRAL: tracked as
``cc-close-gate-unreadable-note-fail-open-20260914`` (filed 2026-09-14T06:45Z).

Recorded honestly because the bookkeeping was the part that went wrong: earlier
revisions of this docstring called the deferral "tracked" while no row existed,
and two reviewers had to raise it three times before one was filed. A request is
not a disposition, and a comment is not a tracked obligation.
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
    FRONTMATTER_UNREADABLE_STATES,
    RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
    RECEIPT_TRIGGER_MALFORMED_CONTAINER,
    RECEIPT_TRIGGER_MALFORMED_REVIEW,
    RECEIPT_TRIGGER_REVIEW_FLOOR,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    acceptance_receipt_triggers,
    frontmatter_state_from_text,
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

    frontmatter, parse_state = frontmatter_state_from_text(text)
    if parse_state in FRONTMATTER_UNREADABLE_STATES:
        # The file READ fine; its content does not parse. That is content, not
        # infrastructure, so it is fail-CLOSED — distinct from the unreadable-file
        # exception above, and carrying none of its availability risk: this is
        # deterministic in the note's own bytes, not in the mount.
        #
        # Without this, a YAML error collapses the frontmatter to {} and the gate
        # reports "no receipt-arming declaration" — a parse failure reported as an
        # absent requirement, which is the outermost instance of the rule every
        # inner container already follows.
        return 2, "\n".join(
            [
                f"cc-close BLOCKED: task note frontmatter could not be parsed ({parse_state}).",
                "",
                f"  - frontmatter_unreadable:{parse_state}",
                "",
                "A note whose frontmatter does not parse cannot be shown to require no review,",
                "so it is refused rather than admitted. This is NOT the missing/unreadable-file",
                "exception: the file was read successfully and its YAML is malformed.",
                "",
                "Repair the frontmatter, then re-run. Common causes:",
                "  invalid_opening_fence — the first line starts with dashes but is not a",
                "                          document marker (a marker is three dashes at column",
                "                          0 followed by end-of-line or whitespace)",
                "  unterminated          — the opening marker has no closing marker line",
                "  parse_error           — invalid YAML (an unclosed '[' or '{' is usual)",
                "  not_a_mapping         — the document is a sequence or scalar, not fields",
                "",
                f"  File: {path}",
                "",
                "Bypass for incident response: HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1",
            ]
        )

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
    if RECEIPT_TRIGGER_MALFORMED_CONTAINER in triggers:
        demands.append(
            "review_requirement (or the route_metadata holding it) is present but is not a"
            " mapping — a list or scalar where a block is required. The flag inside it may be"
            " perfectly valid; the enclosing shape is the failure, so do not change the"
            " true/false value. Make review_requirement a mapping of fields, and route_metadata"
            " a mapping, then re-run. An unreadable container arms the gate rather than"
            " disabling it, because whatever it declares cannot be seen."
        )
    lines = [
        f"cc-close BLOCKED: task '{task_id}' lacks a valid acceptance receipt.",
        f"Armed by: {', '.join(triggers)}",
        "",
        *(f"  - {blocker}" for blocker in blockers),
        "",
        *demands,
        "",
        "Have the acceptor (frontier reviewer or operator) record the verdict at:",
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
