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

Bypass: ``HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1`` (legacy incident response only).
Canon-bound close ignores this raw bypass; governed override evidence belongs in
the shared terminal-close admission rather than an ambient environment variable.

Killswitch under canon-bound close (``HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT=1``,
see ``CANON_BOUND_CLOSE_ENV`` below): the raw env bypass above is inert, and the
governed override receipt it points at is **not implemented yet** — no command
produces one.

``shared/sdlc_close.py`` refuses a close carrying a debt reason with
``terminal_close_debt_override_requires_receipt``, and refuses a non-``done``
final status or a retroactive close with the sibling reasons
``terminal_close_operator_disposition_receipt_required`` and
``terminal_close_retroactive_receipt_required``. ``close_task`` takes no receipt
argument and reads no receipt file, so those three demands cannot currently be
satisfied by any caller.

**Those three refusals are gated on the same switch this gate reads** (the module
constant ``CANON_BOUND_CLOSE_ENV``), so the modes are:

- strict (``HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT=1``) — they fire, as designed,
  pending the receipt contract.
- legacy (unset) — they do not fire, and a close fails only on conditions an
  operator can actually satisfy.

That gating is load bearing and must not be removed. Held unconditionally — as
they were when first landed — a debt-bearing, withdrawn, superseded, or
retroactive task could not reach terminal closure by ANY route, because the
receipt they demand cannot be produced. That is a wedge, not a gate. It was found
by review (codex-1, 2026-08-06) and fixed rather than documented around.

So an operator hitting one of these reasons is in strict mode. The next action is
to resolve the debt and close as ``done``, or run the legacy path with
``HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT`` unset. Implementing the governed override
receipt — so strict mode has a real escape — is open work and a governance
decision.

Covered by ``tests/test_sdlc_closed_loop_e2e.py::test_close_under_debt_is_refused_and_names_no_available_override``
(pins that each refusal is mode-gated, not unconditional) and
``tests/shared/test_sdlc_close.py::test_debt_close_is_not_wedged_outside_canon_bound_mode``
(pins the escape). The strict refusals stay asserted under the mode that owns
them in ``tests/shared/test_sdlc_close.py`` and
``tests/scripts/test_cc_close_session_lease.py``.

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

CANON_BOUND_CLOSE_ENV = "HAPAX_CANON_BOUND_CLOSE_ENFORCEMENT"


def gate(path: Path) -> tuple[int, str]:
    """Return ``(exit_code, message)``; 0 permits closure, 2 blocks it."""

    canon_bound = os.environ.get(CANON_BOUND_CLOSE_ENV) == "1"
    if os.environ.get("HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF") == "1" and not canon_bound:
        return 0, "acceptance-receipt gate disabled by HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1"

    if not path.is_file() and canon_bound:
        return 2, f"canon-bound close fail-CLOSED: source path missing or not a file ({path})"
    if not path.is_file():
        return 0, f"fail-OPEN: source path missing or not a file ({path})"

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        if canon_bound:
            return 2, f"canon-bound close fail-CLOSED: source unreadable ({exc})"
        return 0, f"fail-OPEN: source unreadable ({exc})"

    frontmatter = frontmatter_from_text(text)
    if not requires_acceptance_receipt(frontmatter):
        return 0, "not a review-floor task — acceptance-receipt gate does not apply"

    blockers = list(acceptance_receipt_blockers(frontmatter, path))
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
        (
            "Canon-bound close requires governed override evidence; raw bypass is ignored."
            if canon_bound
            else "Bypass for incident response: HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF=1"
        ),
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
