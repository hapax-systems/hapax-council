#!/usr/bin/env python3
"""cc-task-closure-check — pure-logic acceptance-criteria gate.

Reads a cc-task .md file and returns:
- exit 0 when the file has zero unchecked checkboxes in the
  ``## Acceptance criteria`` section (closure permitted).
- exit 0 when the file has no ``## Acceptance criteria`` section
  (substantive cc-tasks like supersession docs may have none).
- exit 2 when at least one ``- [ ]`` checkbox is unchecked, with a
  human-readable message on stderr enumerating the unchecked items.

Used by:
- ``hooks/scripts/cc-task-closure-gate.sh`` — Bash PreToolUse hook
  catching manual ``mv`` / ``git mv`` invocations
- ``scripts/cc-close`` — patched to call this checker before
  performing the python rename (which is invisible to the Bash hook)

Operator dispatch 2026-05-03T00:25Z. Audit found 3 cc-task closure
errors in 24h: #2243 (0/7 ACs), #2252 (AC#5 deviation), #2259 (3/8
deferred). Pattern: closure = "I worked on it" instead of "criteria
met". This gate forces the disciplined version.

Bypass: ``HAPAX_CC_TASK_CLOSURE_GATE_OFF=1`` env var in the calling
shell disables the gate (incident response only). The gate honors the
env var directly so both the Bash hook and the cc-close caller share
one bypass mechanism.

Failure mode: fail-OPEN on infrastructure errors (file unreadable,
malformed). The cost asymmetry favors permissivity for tool-failure
cases — a broken gate must not brick closures.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

#: Match the `## Acceptance criteria` heading. Tolerates trailing whitespace.
_ACCEPTANCE_HEADING = re.compile(r"^##\s+Acceptance\s+criteria\s*$", re.IGNORECASE | re.MULTILINE)

#: Match unchecked checkbox lines: ``- [ ]`` (with literal space). The
#: leading hyphen + ``[ ]`` + space is the GitHub-flavored markdown
#: convention used across the vault. Checked / N/A checkboxes
#: (``- [x]``, ``- [X]``, ``- [-]``) are intentionally NOT matched —
#: only blockers are interesting to the gate.
_UNCHECKED_CHECKBOX = re.compile(r"^\s*-\s+\[\s\]\s+(.*)$", re.MULTILINE)

#: Headings that terminate the AC section if encountered. Stops at
#: the next ``## ...`` heading to avoid scanning post-AC sections
#: like ``## Closure evidence`` or ``## WSJF`` for unchecked items.
_NEXT_HEADING = re.compile(r"^##\s+", re.MULTILINE)


def acceptance_criteria_section(text: str) -> str | None:
    """Return the substring of ``text`` between the ``## Acceptance criteria``
    heading and the next ``## ...`` heading (or EOF). Returns ``None``
    when no AC heading is present (substantive supersession docs etc).
    """
    m = _ACCEPTANCE_HEADING.search(text)
    if m is None:
        return None
    start = m.end()
    next_heading = _NEXT_HEADING.search(text, pos=start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end]


def unchecked_items(ac_section: str) -> list[str]:
    """Return descriptions of every unchecked AC checkbox line."""
    return [m.group(1).strip() for m in _UNCHECKED_CHECKBOX.finditer(ac_section)]


def gate(path: Path) -> tuple[int, str]:
    """Return ``(exit_code, message)``.

    ``exit_code == 0`` means closure is permitted (all ACs satisfied
    or no AC section at all). ``exit_code == 2`` means closure is
    BLOCKED with a human-readable explanation in ``message``.
    """
    if os.environ.get("HAPAX_CC_TASK_CLOSURE_GATE_OFF") == "1":
        return 0, "gate disabled by HAPAX_CC_TASK_CLOSURE_GATE_OFF=1"

    if not path.is_file():
        return 0, f"fail-OPEN: source path missing or not a file ({path})"

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return 0, f"fail-OPEN: source unreadable ({exc})"

    section = acceptance_criteria_section(text)
    if section is None:
        return 0, "no Acceptance criteria section — closure permitted"

    unchecked = unchecked_items(section)
    if not unchecked:
        return 0, "all Acceptance criteria checkboxes satisfied"

    lines = [
        f"cc-task closure BLOCKED: {len(unchecked)} unchecked Acceptance criteria in {path.name}:",
        "",
    ]
    for desc in unchecked:
        # Truncate very long item descriptions for terminal readability.
        truncated = desc if len(desc) <= 120 else desc[:117].rstrip() + "..."
        lines.append(f"  - [ ] {truncated}")
    lines.extend(
        [
            "",
            "Either complete the unfinished work, OR mark each unfinished AC as",
            "satisfied with a `[x] N/A — superseded by ...` or `[x] deferred to <follow-up>`",
            "annotation explaining why the original AC no longer applies. The gate",
            "exists so closure tracks 'criteria met', not 'I worked on it'.",
            "",
            "Bypass for incident response: HAPAX_CC_TASK_CLOSURE_GATE_OFF=1",
        ]
    )
    return 2, "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: cc-task-closure-check.py <path-to-cc-task.md>", file=sys.stderr)
        return 64
    path = Path(argv[1])
    code, msg = gate(path)
    if code != 0:
        print(msg, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
