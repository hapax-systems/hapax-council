#!/usr/bin/env python3
"""cc-task-artifact-disposition-check — artifact disposition gate for cc-close.

Reads the artifact ledger at ~/.cache/hapax/document-pipeline/artifact-ledger.yaml,
filters entries for the closing task, and checks whether each artifact has reached
a terminal disposition appropriate for its authority ceiling.

Exit codes:
- 0: closure permitted (all dispositions satisfied, warnings only, or fail-open)
- 2: closure BLOCKED (gate-ceiling artifact lacks terminal disposition)

Fail-open on infrastructure errors (missing/empty/malformed ledger).

Bypass: HAPAX_ARTIFACT_DISPOSITION_GATE_OFF=1

Part of the document pipeline (design §14, slice 1).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

LEDGER_PATH = Path.home() / ".cache" / "hapax" / "document-pipeline" / "artifact-ledger.yaml"

CLASS_TO_CEILING: dict[str, str] = {
    "specification": "gate",
    "design": "gate",
    "research": "gate",
    "audit": "gate",
    "evaluation": "advisory",
    "planning": "advisory",
    "lab-journal": "advisory",
    "agent-return": "receipt",
    "relay-receipt": "receipt",
    "source-excerpt": "receipt",
    "conversation-log": "receipt",
}

TERMINAL_STATES_BY_CEILING: dict[str, set[str]] = {
    "gate": {"promoted", "superseded"},
    "advisory": {"promoted", "receipt_only", "refused", "superseded"},
    "receipt": {"promoted", "receipt_only", "refused", "superseded", "expired"},
}

DEFAULT_RECOVERY_ACTIONS: dict[str, str] = {
    "specification": "promote to Obsidian 30-areas/hapax/",
    "design": "promote to Obsidian 30-areas/hapax/",
    "research": "promote to Obsidian 20-projects/hapax-research/",
    "audit": "promote to Obsidian 20-projects/hapax-research/audits/",
}


def read_ledger(ledger_path: Path) -> list[dict] | None:
    """Read and parse the artifact ledger. Returns None on any infrastructure error."""
    if not ledger_path.is_file():
        return None
    try:
        text = ledger_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        print(
            "warning: artifact ledger malformed (YAML parse error), failing open", file=sys.stderr
        )
        return None
    if not isinstance(data, list):
        print("warning: artifact ledger is not a list, failing open", file=sys.stderr)
        return None
    return data


def get_ceiling(entry: dict) -> str:
    """Derive authority ceiling from entry, falling back to class lookup."""
    ceiling = entry.get("authority_ceiling")
    if ceiling and ceiling in TERMINAL_STATES_BY_CEILING:
        return ceiling
    artifact_class = entry.get("class", "")
    return CLASS_TO_CEILING.get(artifact_class, "receipt")


def is_terminal(disposition: str, ceiling: str) -> bool:
    """Check whether a disposition is terminal for the given ceiling."""
    terminal = TERMINAL_STATES_BY_CEILING.get(ceiling, set())
    return disposition in terminal


def make_debt_record(
    entry: dict,
    reason: str,
    owner: str,
) -> dict:
    """Create a debt record for an undispositioned artifact."""
    now = datetime.now(UTC)
    expires = now + timedelta(hours=72)
    artifact_class = entry.get("class", "")
    recovery = DEFAULT_RECOVERY_ACTIONS.get(
        artifact_class, f"disposition {artifact_class} artifact"
    )
    return {
        "reason": reason,
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "owner": owner,
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "recovery_action": recovery,
        "resolved": False,
    }


def write_debt_to_ledger(ledger_path: Path, ledger: list[dict]) -> None:
    """Atomically write the ledger back with debt records."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(ledger, default_flow_style=False, sort_keys=False), encoding="utf-8")
    tmp.replace(ledger_path)


def write_debt_to_task_note(note_path: Path, debt_entries: list[dict]) -> None:
    """Append a ## Document pipeline debt section to the task note."""
    section = "\n## Document pipeline debt\n```yaml\n"
    section += yaml.dump(debt_entries, default_flow_style=False, sort_keys=False)
    section += "```\n"
    text = note_path.read_text(encoding="utf-8")
    if "## Document pipeline debt" not in text:
        text += section
    else:
        # Replace existing section
        import re

        text = re.sub(
            r"## Document pipeline debt\n```yaml\n.*?```\n",
            section.lstrip("\n"),
            text,
            flags=re.DOTALL,
        )
    note_path.write_text(text, encoding="utf-8")


def gate(
    note_path: Path,
    task_id: str,
    debt_reason: str | None = None,
    ledger_path: Path = LEDGER_PATH,
    role: str = "",
) -> int:
    """Run the disposition gate. Returns exit code (0 or 2)."""
    if os.environ.get("HAPAX_ARTIFACT_DISPOSITION_GATE_OFF") == "1":
        print(
            "artifact disposition gate disabled by HAPAX_ARTIFACT_DISPOSITION_GATE_OFF=1",
            file=sys.stderr,
        )
        return 0

    ledger = read_ledger(ledger_path)
    if ledger is None:
        return 0

    task_entries = [e for e in ledger if e.get("task_id") == task_id]
    if not task_entries:
        return 0

    blocked: list[dict] = []
    warned: list[dict] = []
    receipt_debt: list[dict] = []

    for entry in task_entries:
        ceiling = get_ceiling(entry)
        disposition = entry.get("disposition", "produced")

        if is_terminal(disposition, ceiling):
            continue

        if ceiling == "gate":
            blocked.append(entry)
        elif ceiling == "advisory":
            warned.append(entry)
        elif ceiling == "receipt":
            receipt_debt.append(entry)

    # Auto-record debt for receipt-ceiling artifacts (always silent)
    if receipt_debt:
        owner = role or os.environ.get("HAPAX_AGENT_ROLE", "session")
        for entry in receipt_debt:
            entry["debt"] = make_debt_record(
                entry, "auto-recorded at close (receipt ceiling)", owner
            )
        write_debt_to_ledger(ledger_path, ledger)

    # Emit warnings for advisory-ceiling artifacts
    for entry in warned:
        aid = entry.get("artifact_id", "unknown")
        cls = entry.get("class", "unknown")
        disp = entry.get("disposition", "unknown")
        print(
            f"warning: advisory artifact '{aid}' (class={cls}) has non-terminal disposition '{disp}'",
            file=sys.stderr,
        )

    # Handle debt bypass
    if debt_reason and (blocked or warned):
        owner = role or os.environ.get("HAPAX_AGENT_ROLE", "session")
        debt_note_entries = []
        for entry in blocked + warned:
            debt = make_debt_record(entry, debt_reason, owner)
            entry["debt"] = debt
            debt_note_entries.append(
                {
                    "artifact": entry.get("artifact_id", "unknown"),
                    "class": entry.get("class", "unknown"),
                    "reason": debt_reason,
                    "created_at": debt["created_at"],
                    "owner": owner,
                    "expires_at": debt["expires_at"],
                    "recovery_action": debt["recovery_action"],
                    "resolved": False,
                }
            )
        write_debt_to_ledger(ledger_path, ledger)
        write_debt_to_task_note(note_path, debt_note_entries)
        return 0

    # Advisory-ceiling debt recording when --debt provided but nothing blocked
    if debt_reason and not blocked and not warned and receipt_debt:
        # Receipt debt already recorded above
        return 0

    # Gate-ceiling blocking
    if blocked:
        lines = [
            f"cc-close BLOCKED: {len(blocked)} gate-ceiling artifact(s) lack terminal disposition:",
            "",
        ]
        for entry in blocked:
            aid = entry.get("artifact_id", "unknown")
            cls = entry.get("class", "unknown")
            disp = entry.get("disposition", "unknown")
            lines.append(f"  - {aid} (class={cls}, disposition={disp})")
        lines.extend(
            [
                "",
                "Each gate-ceiling artifact must reach 'promoted' or 'superseded' before",
                "task closure. Use 'document-pipeline-triage' to update dispositions, or",
                "pass '--debt \"reason\"' to cc-close for emergency bypass with debt tracking.",
                "",
                "Full bypass: HAPAX_ARTIFACT_DISPOSITION_GATE_OFF=1",
            ]
        )
        print("\n".join(lines), file=sys.stderr)

        # Emit readiness predicate (informational, not persisted)
        unsatisfied = [e.get("artifact_id", "unknown") for e in blocked]
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        predicate = {
            "predicates": {
                "readiness": {
                    "operation": "task_close",
                    "value": "not_ready",
                    "unsatisfied": unsatisfied,
                    "source": {
                        "producer": "cc-close-gate",
                        "evaluated_at": now,
                        "stale_after": "60s",
                    },
                    "authority": "gate",
                }
            }
        }
        print(yaml.dump(predicate, default_flow_style=False, sort_keys=False), file=sys.stderr)
        return 2

    # All satisfied — emit ready predicate
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    predicate = {
        "predicates": {
            "readiness": {
                "operation": "task_close",
                "value": "ready",
                "unsatisfied": [],
                "source": {
                    "producer": "cc-close-gate",
                    "evaluated_at": now,
                    "stale_after": "60s",
                },
                "authority": "gate",
            }
        }
    }
    print(yaml.dump(predicate, default_flow_style=False, sort_keys=False), file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: cc-task-artifact-disposition-check.py <note_path> <task_id> [--debt REASON]",
            file=sys.stderr,
        )
        return 64

    note_path = Path(argv[1])
    task_id = argv[2]
    debt_reason = None
    if len(argv) >= 5 and argv[3] == "--debt":
        debt_reason = argv[4]

    role = os.environ.get(
        "HAPAX_AGENT_NAME",
        os.environ.get("HAPAX_AGENT_ROLE", os.environ.get("CLAUDE_ROLE", "")),
    )

    return gate(note_path, task_id, debt_reason=debt_reason, role=role)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
