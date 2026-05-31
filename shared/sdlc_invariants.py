"""SDLC-ladder never-stuck invariants as RUNTIME trace checks (Phase 3c).

Coordination reform Phase 3c (master design §4.5, NEW-1). The TLA+ model
(``docs/formal/sdlc-ladder.tla``) is model-checkable but **advisory-with-ledger
ONLY** — never a release/merge gate, because a self-blocking proof gate would
rebuild the freeze-blocks-thaw meta-catch-22 in the verification layer. These
Python functions are the TLA+ invariants' runtime companions: pure, advisory
checks over the canonical ladder + an authority-case-ledger trace. They NEVER
raise and NEVER block — a violation is ledgered and surfaced, never enforced.

INV-1 Deadlock-freedom   every non-terminal stage has ≥1 outgoing transition
INV-2 Liveness           every claimed task eventually reaches a terminal stage
INV-3 Escape             every BLOCK state has an escape transition out
INV-4 Authority-escapable  the escape never depends on the process it governs
INV-5 Cognition-writable a blocked lane can always write its cognition surfaces

INV-4/INV-5 build on Phase 3b ``policy_decide(kernel_up=False)`` + the cognition
carve-out: with the kernel DOWN, reversible work still proceeds (fail-open),
irreversible harm is still blocked (the embedded floor), and cognition is always
writable — so a lane is never stuck because the daemon is dead.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.policy_decide import ToolCall, policy_decide

#: Authority-case stage-transition ledger this monitor reads (the trace input).
DEFAULT_AUTHORITY_LEDGER = Path(os.path.expanduser("~/.cache/hapax/authority-case-ledger.jsonl"))
#: Advisory findings ledger this monitor writes (violations only).
DEFAULT_INVARIANT_LEDGER = Path(os.path.expanduser("~/.cache/hapax/sdlc-invariant-findings.jsonl"))


# --- The statechart as data (mirrors docs/formal/sdlc-ladder.tla) -------------


@dataclass(frozen=True)
class Ladder:
    """The SDLC statechart: stages + legal transitions + terminal/blocked sets."""

    stages: tuple[str, ...]
    transitions: Mapping[str, frozenset[str]]
    terminal: frozenset[str]
    blocked: frozenset[str]


#: The canonical S0..S11 ladder + the S3.5 disconfirmation branch + a BLOCKED
#: pseudo-state with operator escape edges. Forward by default; S3 may branch to
#: disconfirmation; S6/S7 may fall to BLOCKED; BLOCKED always escapes (INV-3);
#: S11 is the only terminal (INV-1 permits it to have no successor).
SDLC_LADDER = Ladder(
    stages=(
        "S0",
        "S1",
        "S2",
        "S3",
        "S3_5",
        "S4",
        "S5",
        "S6",
        "S7",
        "S8",
        "S9",
        "S10",
        "S11",
        "BLOCKED",
    ),
    transitions={
        "S0": frozenset({"S1"}),
        "S1": frozenset({"S2"}),
        "S2": frozenset({"S3"}),
        "S3": frozenset({"S4", "S3_5"}),
        "S3_5": frozenset({"S4", "S0"}),
        "S4": frozenset({"S5"}),
        "S5": frozenset({"S6"}),
        "S6": frozenset({"S7", "BLOCKED"}),
        "S7": frozenset({"S8", "BLOCKED"}),
        "S8": frozenset({"S9"}),
        "S9": frozenset({"S10"}),
        "S10": frozenset({"S11"}),
        "S11": frozenset(),  # terminal
        "BLOCKED": frozenset({"S6", "S0"}),  # operator escape — always non-empty
    },
    terminal=frozenset({"S11"}),
    blocked=frozenset({"BLOCKED"}),
)


@dataclass(frozen=True)
class InvariantResult:
    """One advisory invariant evaluation. ``holds`` False is ledgered, never blocks."""

    invariant: str
    name: str
    holds: bool
    violations: tuple[str, ...]
    advisory: str


# --- The five checks (pure, total — never raise) ------------------------------


def check_inv1_deadlock_freedom(ladder: Ladder = SDLC_LADDER) -> InvariantResult:
    """INV-1: every non-terminal stage has ≥1 outgoing transition (no dead-ends)."""
    violations: list[str] = []
    try:
        for stage in ladder.stages:
            if stage not in ladder.terminal and not ladder.transitions.get(stage):
                violations.append(f"non-terminal stage '{stage}' has no outgoing transition")
    except Exception as exc:  # noqa: BLE001 — advisory check must never raise.
        violations.append(f"check_error:{exc!r}")
    return InvariantResult(
        "INV-1",
        "deadlock-freedom",
        not violations,
        tuple(violations),
        "add a forward/escape transition for the stuck stage",
    )


def check_inv3_escape(ladder: Ladder = SDLC_LADDER) -> InvariantResult:
    """INV-3: every BLOCK state has an escape transition (an operator can leave it)."""
    violations: list[str] = []
    try:
        for stage in ladder.blocked:
            if not ladder.transitions.get(stage):
                violations.append(f"blocked state '{stage}' has no escape transition")
    except Exception as exc:  # noqa: BLE001
        violations.append(f"check_error:{exc!r}")
    return InvariantResult(
        "INV-3",
        "escape-invariant",
        not violations,
        tuple(violations),
        "every BLOCK state must have an operator escape edge",
    )


def check_inv2_liveness(
    trace: Iterable[Mapping[str, object]],
    *,
    now: float,
    stale_after_s: float = 86400.0,
    ladder: Ladder = SDLC_LADDER,
) -> InvariantResult:
    """INV-2: each task's latest stage is terminal, fresh-and-advancing, or flagged stuck.

    A runtime approximation of the temporal liveness property: a task violates if
    its latest observed stage is unknown, or non-terminal and stale beyond
    ``stale_after_s`` (no progress) — i.e. effectively stuck.
    """
    violations: list[str] = []
    try:
        latest: dict[str, tuple[str, float]] = {}
        for record in trace:
            task_id = str(record.get("task_id", "")).strip()
            if not task_id:
                continue
            try:
                ts = float(record.get("timestamp", 0.0) or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            if task_id not in latest or ts >= latest[task_id][1]:
                latest[task_id] = (str(record.get("to_stage", "")).strip(), ts)
        for task_id, (stage, ts) in latest.items():
            if stage not in ladder.stages:
                violations.append(f"{task_id}:unknown_stage:{stage or '<blank>'}")
            elif stage in ladder.terminal:
                continue
            elif (now - ts) > stale_after_s:
                violations.append(f"{task_id}:stuck:{stage}:{int(now - ts)}s")
    except Exception as exc:  # noqa: BLE001
        violations.append(f"check_error:{exc!r}")
    return InvariantResult(
        "INV-2",
        "liveness",
        not violations,
        tuple(violations),
        "re-dispatch or escape the stuck task; verify it can still advance",
    )


def check_inv4_authority_escapable() -> InvariantResult:
    """INV-4: escape never depends on the process it governs (kernel-down is directional).

    With the kernel DOWN, a reversible op must fail OPEN (not stuck) while an
    irreversible op must still fail CLOSED (the embedded floor). Built on Phase 3b
    ``policy_decide(kernel_up=False)``.
    """
    violations: list[str] = []
    try:
        reversible = policy_decide(
            ToolCall("Edit", file_path="shared/example.py"), None, None, kernel_up=False
        )
        if not reversible.allowed:
            violations.append("reversible op was blocked with the kernel down (would be stuck)")
        irreversible = policy_decide(
            ToolCall("Bash", command="gh pr merge 1"), None, None, kernel_up=False
        )
        if not irreversible.blocked:
            violations.append("irreversible op was not blocked with the kernel down")
    except Exception as exc:  # noqa: BLE001
        violations.append(f"check_error:{exc!r}")
    return InvariantResult(
        "INV-4",
        "authority-always-escapable",
        not violations,
        tuple(violations),
        "the daemon-independent floor must fail-open reversible / fail-closed irreversible",
    )


def check_inv5_cognition_writable() -> InvariantResult:
    """INV-5: a blocked lane can always write cognition surfaces, kernel up OR down."""
    violations: list[str] = []
    try:
        path = os.path.expanduser("~/.claude/projects/example/memory/note.md")
        for kernel_up in (True, False):
            decision = policy_decide(
                ToolCall("Write", file_path=path), None, None, kernel_up=kernel_up
            )
            if not decision.allowed:
                violations.append(f"cognition write blocked (kernel_up={kernel_up})")
    except Exception as exc:  # noqa: BLE001
        violations.append(f"check_error:{exc!r}")
    return InvariantResult(
        "INV-5",
        "cognition-always-writable",
        not violations,
        tuple(violations),
        "memory / vault / scratch surfaces must be ungated regardless of state",
    )


def check_all(
    trace: Iterable[Mapping[str, object]] = (),
    *,
    now: float = 0.0,
    stale_after_s: float = 86400.0,
    ladder: Ladder = SDLC_LADDER,
) -> list[InvariantResult]:
    """Evaluate INV-1..5. Pure + advisory; the result is reported, never enforced."""
    return [
        check_inv1_deadlock_freedom(ladder),
        check_inv2_liveness(trace, now=now, stale_after_s=stale_after_s, ladder=ladder),
        check_inv3_escape(ladder),
        check_inv4_authority_escapable(),
        check_inv5_cognition_writable(),
    ]


def record_invariant_findings(
    results: Iterable[InvariantResult], *, ledger_path: str | os.PathLike[str]
) -> None:
    """Append VIOLATIONS (only) to the advisory findings ledger. Never raises, never blocks."""
    try:
        rows = [r for r in results if not r.holds]
        if not rows:
            return
        path = Path(ledger_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for result in rows:
                handle.write(
                    json.dumps(
                        {
                            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "invariant": result.invariant,
                            "name": result.name,
                            "holds": result.holds,
                            "violations": list(result.violations),
                            "advisory": result.advisory,
                        }
                    )
                    + "\n"
                )
    except Exception:  # noqa: BLE001 — advisory ledger; a write failure must not block.
        pass


# --- Advisory CLI: monitor the live ledger ------------------------------------


def _load_ledger_trace(path: Path) -> list[dict[str, object]]:
    """Parse the authority-case-ledger into INV-2 trace records. Best-effort."""
    trace: list[dict[str, object]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return trace
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_raw = record.get("timestamp", "")
        ts = 0.0
        try:
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            ts = 0.0
        trace.append(
            {
                "task_id": str(record.get("case_id") or record.get("task_id") or ""),
                "to_stage": _stage_token(str(record.get("to_stage", ""))),
                "timestamp": ts,
            }
        )
    return trace


def _stage_token(raw: str) -> str:
    """Normalize 'S6_IMPLEMENTATION' / 'S3.5' to the ladder's stage token (S6 / S3_5)."""
    token = raw.strip().replace(".", "_")
    return token.split("_")[0] if (token[:1] == "S" and "_" in token and token != "S3_5") else token


def main(argv: list[str] | None = None) -> int:
    """Advisory invariant monitor over the live authority-case-ledger.

    ``python -m shared.sdlc_invariants [--ledger PATH] [--findings PATH]
    [--stale-after-s N]`` evaluates INV-1..5, records violations to the findings
    ledger, and prints each result. ADVISORY ONLY — always exits 0; never a gate.
    """
    parser = argparse.ArgumentParser(prog="sdlc_invariants")
    parser.add_argument("--ledger", default=str(DEFAULT_AUTHORITY_LEDGER))
    parser.add_argument("--findings", default=str(DEFAULT_INVARIANT_LEDGER))
    parser.add_argument("--stale-after-s", dest="stale_after_s", type=float, default=86400.0)
    args = parser.parse_args(argv)

    trace = _load_ledger_trace(Path(args.ledger))
    results = check_all(trace=trace, now=time.time(), stale_after_s=args.stale_after_s)
    record_invariant_findings(results, ledger_path=args.findings)
    for result in results:
        print(
            json.dumps(
                {
                    "invariant": result.invariant,
                    "holds": result.holds,
                    "violations": list(result.violations),
                }
            )
        )
    return 0  # advisory: never enforces


if __name__ == "__main__":
    raise SystemExit(main())
