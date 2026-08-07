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
see ``CANON_BOUND_CLOSE_ENV`` below): the raw env bypass above is inert. The
governed escape is a **close-override receipt**, and unlike the raw bypass it
composes *within* the gate rather than switching the gate off.

``shared/sdlc_close.py`` refuses a debt-bearing close with
``terminal_close_debt_override_requires_receipt``, and a non-``done`` final
status or retroactive close with
``terminal_close_operator_disposition_receipt_required`` and
``terminal_close_retroactive_receipt_required``. In strict mode each of those is
satisfied by minting, beside the task note::

    <vault>/active/<task_id>.close-override.yaml

      acceptor:  <who authorized it>
      verdict:   accepted
      timestamp: <ISO-8601>
      artifact:  <ref to the incident or decision>
      task_id:   <task_id>          # optional; if present it must match

Deliberately the same shape as ``<task_id>.acceptance.yaml`` — one receipt idiom,
one validator shape, no new instrument. Validated by
``shared.sdlc_lifecycle.close_override_receipt_blockers``: absent, unreadable,
malformed, field-incomplete, non-``accepted``, or naming a different task all
fail closed, and the refusal's ``detail`` names which. The ``task_id`` binding
exists so a valid receipt cannot be copied beside another note to authorize an
unrelated close.

It authorizes exactly one thing — proceeding past those three refusals for the
task it names. No release, publication, runtime, or provider authority follows
from it, and it is not consulted outside canon-bound close.

Outside strict mode the refusals do not fire at all, so a close there fails only
on conditions an operator can satisfy.

History worth keeping: these refusals originally fired unconditionally while no
receipt could be expressed, so an affected task was permanently nonterminal — a
wedge, not a gate. Found by review (codex-1, 2026-08-06) across four rounds and
fixed rather than documented around. **Do not remove either the mode gating or
the override path**; together they are what make this composable.

Covered by ``tests/shared/test_sdlc_close.py`` —
``::test_strict_mode_debt_close_accepts_a_governed_override_receipt``,
``::test_strict_mode_withdrawal_accepts_a_governed_override_receipt``,
``::test_strict_mode_rejects_an_invalid_close_override_receipt`` (verdict,
missing field, task mismatch), ``::test_debt_close_is_not_wedged_outside_canon_bound_mode`` —
and by ``tests/test_sdlc_closed_loop_e2e.py::test_close_under_debt_is_refused_and_names_no_available_override``.

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
