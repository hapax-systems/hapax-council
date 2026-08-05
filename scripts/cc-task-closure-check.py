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

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.sdlc_gate_event_drain import (  # noqa: E402
    OUTCOME_GATE_ON_CLOSE_ENV,
    outcome_gate_on_close_enabled,
)
from shared.sdlc_lifecycle import (  # noqa: E402
    acceptance_criteria_state,
    frontmatter_from_text,
)
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS  # noqa: E402

# World-to-record first caller (Edge A §4 / Edge C): OFF by default.
# When HAPAX_OUTCOME_GATE_ON_CLOSE=1, a permitted close with a complete
# requirement_vector emits a witnessed learning GateEvent via
# emit_outcome_gate_event. Incomplete vector → no learning event; modal
# incomplete_technical is ledgered. Append failure → close refused.
# Flag reader SSOT: shared.sdlc_gate_event_drain.outcome_gate_on_close_enabled
_OUTCOME_GATE_ENV = OUTCOME_GATE_ON_CLOSE_ENV
_CLOSE_MODAL_LEDGER = (
    Path.home() / ".cache" / "hapax" / "sdlc-routing" / "close-modal-outcomes.jsonl"
)


def acceptance_criteria_section(text: str) -> str | None:
    """Compatibility wrapper for callers importing this script directly."""
    from shared.sdlc_lifecycle import acceptance_criteria_section as _section

    return _section(text)


def unchecked_items(ac_section: str) -> list[str]:
    """Return descriptions of every unchecked AC checkbox line."""
    state = acceptance_criteria_state(f"## Acceptance criteria\n{ac_section}")
    return list(state.unchecked_items)


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

    ac_state = acceptance_criteria_state(text)
    if not ac_state.section_present:
        return 0, "no Acceptance criteria section — closure permitted"

    unchecked = list(ac_state.unchecked_items)
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


def shadow_observe(path: Path) -> None:
    """Acceptance-oracle SHADOW probe — opt-in, advisory-only, never affects closure.

    OFF by default: only runs when ``HAPAX_ACCEPTANCE_ORACLE_SHADOW=1``, so the
    closure gate's behavior is byte-identical without the env var. When on, it spawns
    ``scripts/hapax-acceptance-oracle`` *detached* to ledger a verdict for this
    permitted closure (the divergence-detection point: the checkbox gate said OK — does
    the oracle agree?). The oracle is itself load-gated and fail-OPEN, so this can never
    block, slow, or crash a closure. Phase P0 of the acceptance-oracle pilot; see
    ``docs/superpowers/specs/2026-06-02-acceptance-oracle-design.md``.
    """
    if os.environ.get("HAPAX_ACCEPTANCE_ORACLE_SHADOW") != "1":
        return
    oracle = REPO_ROOT / "scripts" / "hapax-acceptance-oracle"
    if not oracle.is_file():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(oracle), "--note", str(path), "--json"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass  # advisory-only: a failed spawn must never affect closure


def _resolve_close_route(task_fields: dict[str, Any]) -> str:
    """Best-effort route id for the learning event (not a live dispatch decision)."""
    for key in ("route_id", "resolved_route", "platform"):
        value = task_fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    route_md = task_fields.get("route_metadata")
    if isinstance(route_md, dict):
        constraints = route_md.get("route_constraints")
        if isinstance(constraints, dict):
            for list_key in ("preferred_platforms", "allowed_platforms"):
                platforms = constraints.get(list_key)
                if isinstance(platforms, list) and platforms:
                    first = platforms[0]
                    if isinstance(first, str) and first.strip():
                        return first.strip()
    assigned = task_fields.get("assigned_to")
    if isinstance(assigned, str) and assigned.strip() and assigned != "unassigned":
        return assigned.strip()
    return "unknown"


def _requirement_vector_complete(vector: object) -> bool:
    if not isinstance(vector, dict):
        return False
    if set(vector) != set(REQUIREMENT_VECTOR_DIMENSIONS):
        return False
    for score in vector.values():
        if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 5):
            return False
    return True


def _append_close_modal_ledger(record: dict[str, Any]) -> None:
    _CLOSE_MODAL_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with _CLOSE_MODAL_LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(line)


def maybe_emit_outcome_on_close(path: Path, text: str) -> tuple[int, str]:
    """World-to-record first caller. Default off; fail-closed when enabled and emit fails.

    Returns ``(0, msg)`` when close may proceed, or ``(3, msg)`` when the outcome
    gate refuses close (enabled + append/build failure). Never emits learning
    events when the requirement_vector is incomplete — ledgers modal instead.
    """
    if not outcome_gate_on_close_enabled():
        return 0, f"{_OUTCOME_GATE_ENV} off — no outcome gate emit"

    task_fields = frontmatter_from_text(text)
    if not task_fields:
        _append_close_modal_ledger(
            {
                "schema": "hapax.close_modal_outcome.v1",
                "note": str(path),
                "modal_class": "incomplete_technical",
                "reason": "empty_or_unparseable_frontmatter",
                "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        return 0, "outcome gate: incomplete_technical (no frontmatter) — no learning emit"

    # Prefer explicit requirement_vector; else derive via DemandVector when route_metadata valid.
    demand_vector = None
    try:
        from shared.gate_event_producer import build_requirement_vector
        from shared.route_metadata_schema import build_demand_vector

        try:
            demand_vector = build_demand_vector(task_fields, note_path=path)
        except (ValueError, TypeError, KeyError):
            demand_vector = None
        vector = build_requirement_vector(task_fields, demand_vector)
    except Exception as exc:  # noqa: BLE001 — fail closed on unexpected producer errors
        return 3, (
            f"cc-task closure BLOCKED by outcome gate: failed to build requirement_vector "
            f"({exc!r}). Fix frontmatter/route_metadata or set {_OUTCOME_GATE_ENV}=0."
        )

    if not _requirement_vector_complete(vector):
        _append_close_modal_ledger(
            {
                "schema": "hapax.close_modal_outcome.v1",
                "note": str(path),
                "task_id": task_fields.get("task_id"),
                "modal_class": "incomplete_technical",
                "reason": "incomplete_requirement_vector",
                "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        return (
            0,
            "outcome gate: incomplete_technical (incomplete requirement_vector) — no learning emit",
        )

    # Ensure task_fields carry the complete vector for the producer join.
    fields_for_event = dict(task_fields)
    fields_for_event["requirement_vector"] = vector
    route = _resolve_close_route(fields_for_event)

    try:
        from shared.gate_outcome_producer import emit_outcome_gate_event

        emit_outcome_gate_event(
            fields_for_event,
            route=route,
            gate_result="accept",
            gate_type="deterministic",
            demand_vector=demand_vector,
            provenance="witnessed",
        )
    except Exception as exc:  # noqa: BLE001 — append/build failure must refuse close
        return 3, (
            f"cc-task closure BLOCKED by outcome gate: emit_outcome_gate_event failed "
            f"({exc!r}). Repair gate log path or set {_OUTCOME_GATE_ENV}=0 for incident bypass."
        )

    _append_close_modal_ledger(
        {
            "schema": "hapax.close_modal_outcome.v1",
            "note": str(path),
            "task_id": task_fields.get("task_id"),
            "modal_class": "permitted",
            "reason": "witnessed_accept_emitted",
            "route": route,
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    return 0, f"outcome gate: witnessed accept emitted for route={route}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: cc-task-closure-check.py <path-to-cc-task.md>", file=sys.stderr)
        return 64
    path = Path(argv[1])
    code, msg = gate(path)
    if code != 0:
        print(msg, file=sys.stderr)
        return code

    # Closure permitted by the checkbox gate — world-to-record (flag default off),
    # then acceptance-oracle shadow (opt-in, never alters return when flag off).
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    outcome_code, outcome_msg = maybe_emit_outcome_on_close(path, text)
    if outcome_code != 0:
        print(outcome_msg, file=sys.stderr)
        return outcome_code

    shadow_observe(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
