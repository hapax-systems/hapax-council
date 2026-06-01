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
import secrets
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.governance.coord_capabilities import (
    EscapeGrant,
    mint_escape_grant,
    verify_escape_grant,
    write_grant_file,
)
from shared.policy_decide import ToolCall, policy_decide
from shared.policy_decision import Decision, FailMode, Verdict
from shared.policy_floor import evaluate_floor

#: Authority-case stage-transition ledger this monitor reads (the trace input).
DEFAULT_AUTHORITY_LEDGER = Path(os.path.expanduser("~/.cache/hapax/authority-case-ledger.jsonl"))
#: Advisory findings ledger this monitor writes (violations only).
DEFAULT_INVARIANT_LEDGER = Path(os.path.expanduser("~/.cache/hapax/sdlc-invariant-findings.jsonl"))
#: HMAC key the auto-mint signs escape grants with. The monitor is the first
#: runtime minter, so it CREATES this key (0600) if absent; the daemon-independent
#: shim (which honors grants kernel-down) reads the SAME path. Override via
#: ``--key-file`` / ``HAPAX_COORD_GRANT_KEY_FILE``.
DEFAULT_GRANT_KEY_FILE = Path(
    os.environ.get(
        "HAPAX_COORD_GRANT_KEY_FILE", os.path.expanduser("~/.config/hapax/coord-capability.key")
    )
)
#: Directory the auto-minted escape grant FILES land in. The shim reads grants
#: directly from disk here — no RPC, so a grant is honored with the kernel dead.
DEFAULT_ESCAPE_GRANT_DIR = Path(
    os.environ.get("HAPAX_ESCAPE_GRANT_DIR", os.path.expanduser("~/.cache/hapax/escape-grants"))
)
#: Only the escape-class invariants auto-mint a grant on violation (§4.5). INV-1/2
#: are statechart/liveness properties — they ledger an advisory alert, never mint.
AUTO_MINT_INVARIANTS = frozenset({"INV-3", "INV-4", "INV-5"})
#: TTL for an auto-minted escape: long enough for a stuck lane to act, short enough
#: that a stale escape expires rather than lingering as a standing bypass.
ESCAPE_GRANT_TTL_S = 3600.0
#: The auto-mint grantor identity stamped on every minted grant (legibility).
ESCAPE_GRANTOR = "sdlc-invariant-monitor"


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


# --- Daemon-independent escape: the auto-mint + the shim's grant carve-out -----
#
# §4.5: a violated invariant "emits a ledgered alert and (for INV-3/4/5) auto-mints
# the relevant escape — it never freezes the system to 'protect' it." The escape is
# the signed EscapeGrant from coord_capabilities: a FILE the L3 hook-shim reads
# directly when the kernel is down (frictionless-self-direction design, L3) —
# verification is a pure signature/expiry/scope check, never an RPC, so a grant
# unblocks a lane regardless of daemon liveness (INV-4).


def load_or_create_grant_key(path: str | os.PathLike[str] = DEFAULT_GRANT_KEY_FILE) -> bytes:
    """Load the coord-capability HMAC key, creating a fresh 32-byte key (mode 0600) if absent.

    The monitor is the first runtime minter, so it establishes the key the
    daemon-independent shim later reads from the SAME path. Returns ``b""`` only if
    the key can neither be read nor persisted — the caller then degrades to
    ledger-only (no verifiable grant can be signed). Never raises.
    """
    target = Path(path)
    try:
        return target.read_bytes()
    except OSError:
        pass
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key
    except OSError:
        return b""


def decide_with_escape(
    tool_name: str,
    *,
    command: str = "",
    file_path: str = "",
    grant: EscapeGrant | None = None,
    key: bytes,
    now: float,
) -> Decision:
    """The kernel-DOWN floor decision, with a valid escape grant overriding a block.

    This is the Python form of the L3 hook-shim's daemon-down contract: evaluate the
    embedded conservative floor and, if it BLOCKS, honor an escape grant iff it
    verifies (signature + expiry + scope — pure, no RPC, no daemon). So a signed
    grant unblocks a lane with the kernel dead, which is exactly INV-4
    (authority-always-escapable). Never raises.
    """
    try:
        decision = evaluate_floor(tool_name, command=command, file_path=file_path)
        if decision.allowed:
            return decision
        if verify_escape_grant(grant, key=key, now=now, gate=decision.gate):
            return Decision(
                verdict=Verdict.ALLOW,
                gate="escape:granted",
                reason=f"escape grant overrides {decision.gate} (daemon-independent)",
                fail_mode=FailMode.FAIL_OPEN_WITH_LEDGER,
            )
        return decision
    except Exception:  # noqa: BLE001 — degrade to the conservative floor block on any error.
        return evaluate_floor(tool_name, command=command, file_path=file_path)


def mint_escape_for_violation(
    result: InvariantResult,
    *,
    key: bytes,
    grant_dir: str | os.PathLike[str] = DEFAULT_ESCAPE_GRANT_DIR,
    now: float,
    ttl_s: float = ESCAPE_GRANT_TTL_S,
) -> EscapeGrant | None:
    """Auto-mint a signed universal ("*") escape grant for an INV-3/4/5 violation.

    INV-3/4/5 violations all mean the escape machinery itself may be compromised, so
    the never-freeze response is a broad daemon-independent escape (the triggering
    invariant is stamped in the grant ``reason`` for legibility). Returns the minted
    grant written to ``grant_dir``, or ``None`` when the invariant holds, is not an
    auto-mint class, or no signing key is available. Never raises — advisory.
    """
    if result.holds or result.invariant not in AUTO_MINT_INVARIANTS or not key:
        return None
    try:
        grant = mint_escape_grant(
            grantor=ESCAPE_GRANTOR,
            scope="*",
            reason=(
                f"auto-mint: {result.invariant} ({result.name}) violated — "
                "universal escape so no lane is frozen"
            ),
            ttl_s=ttl_s,
            key=key,
            now=now,
        )
        slug = result.invariant.lower().replace("-", "")
        write_grant_file(grant, Path(grant_dir) / f"{slug}-{grant.grant_id}.json")
        return grant
    except Exception:  # noqa: BLE001 — auto-mint is advisory; a mint/IO failure must not block.
        return None


@dataclass(frozen=True)
class EvaluationReport:
    """The outcome of one evaluator pass: the checks, any auto-minted escapes, alert state."""

    results: tuple[InvariantResult, ...]
    minted: tuple[EscapeGrant, ...]
    violations: tuple[str, ...]


def _alert_violations(results: Iterable[InvariantResult], minted: Iterable[EscapeGrant]) -> None:
    """Best-effort operator alert for violations. Advisory — never raises, never blocks."""
    try:
        from shared.notify import send_notification

        bad = [r for r in results if not r.holds]
        if not bad:
            return
        minted_n = len(list(minted))
        lines = [f"{r.invariant} {r.name}: {'; '.join(r.violations) or 'violated'}" for r in bad]
        send_notification(
            f"SDLC invariant violation ({len(bad)})",
            "\n".join(lines) + (f"\nauto-minted {minted_n} escape grant(s)" if minted_n else ""),
            priority="high",
            tags=["warning", "rotating_light"],
        )
    except Exception:  # noqa: BLE001 — the alert is advisory; a notify failure must not block.
        pass


def run_evaluator(
    trace: Iterable[Mapping[str, object]] = (),
    *,
    now: float,
    stale_after_s: float = 86400.0,
    ladder: Ladder = SDLC_LADDER,
    findings_path: str | os.PathLike[str] = DEFAULT_INVARIANT_LEDGER,
    grant_dir: str | os.PathLike[str] = DEFAULT_ESCAPE_GRANT_DIR,
    key: bytes = b"",
    alert: bool = True,
) -> EvaluationReport:
    """Run one advisory-with-ledger evaluator pass over INV-1..5 against live state.

    Evaluates the invariants, ledgers every violation, AUTO-MINTS the relevant escape
    for each INV-3/4/5 violation (never for INV-1/2), and emits a best-effort operator
    alert. Advisory-with-ledger ONLY: it NEVER blocks and NEVER raises — a violation is
    surfaced and (for the escape class) self-remediated, never used to freeze the system.
    """
    results = check_all(trace, now=now, stale_after_s=stale_after_s, ladder=ladder)
    record_invariant_findings(results, ledger_path=findings_path)
    minted: list[EscapeGrant] = []
    for result in results:
        grant = mint_escape_for_violation(result, key=key, grant_dir=grant_dir, now=now)
        if grant is not None:
            minted.append(grant)
    violations = tuple(r.invariant for r in results if not r.holds)
    if alert and violations:
        _alert_violations(results, minted)
    return EvaluationReport(tuple(results), tuple(minted), violations)


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
    """Advisory invariant evaluator over the live authority-case-ledger.

    ``python -m shared.sdlc_invariants [--ledger PATH] [--findings PATH]
    [--stale-after-s N] [--mint-escapes] [--grant-dir DIR] [--key-file PATH]
    [--no-alert]`` evaluates INV-1..5, records violations to the findings ledger, and
    prints each result. With ``--mint-escapes`` (the systemd-timer mode) it also
    AUTO-MINTS the relevant escape for each INV-3/4/5 violation and alerts the
    operator. ADVISORY-WITH-LEDGER ONLY — always exits 0; never a gate.
    """
    parser = argparse.ArgumentParser(prog="sdlc_invariants")
    parser.add_argument("--ledger", default=str(DEFAULT_AUTHORITY_LEDGER))
    parser.add_argument("--findings", default=str(DEFAULT_INVARIANT_LEDGER))
    parser.add_argument("--stale-after-s", dest="stale_after_s", type=float, default=86400.0)
    parser.add_argument(
        "--mint-escapes",
        dest="mint_escapes",
        action="store_true",
        help="auto-mint the relevant escape grant on each INV-3/4/5 violation (§4.5)",
    )
    parser.add_argument("--grant-dir", default=str(DEFAULT_ESCAPE_GRANT_DIR))
    parser.add_argument("--key-file", dest="key_file", default=str(DEFAULT_GRANT_KEY_FILE))
    parser.add_argument(
        "--no-alert", dest="alert", action="store_false", help="suppress the operator notification"
    )
    args = parser.parse_args(argv)

    trace = _load_ledger_trace(Path(args.ledger))
    key = load_or_create_grant_key(args.key_file) if args.mint_escapes else b""
    report = run_evaluator(
        trace=trace,
        now=time.time(),
        stale_after_s=args.stale_after_s,
        findings_path=args.findings,
        grant_dir=args.grant_dir,
        key=key,
        alert=args.alert and args.mint_escapes,
    )
    minted_by_inv: dict[str, str] = {}
    for grant in report.minted:
        for inv in AUTO_MINT_INVARIANTS:
            if f" {inv} " in grant.reason:
                minted_by_inv[inv] = grant.grant_id
                break
    for result in report.results:
        print(
            json.dumps(
                {
                    "invariant": result.invariant,
                    "holds": result.holds,
                    "violations": list(result.violations),
                    "minted_escape": minted_by_inv.get(result.invariant),
                }
            )
        )
    return 0  # advisory: never enforces


if __name__ == "__main__":
    raise SystemExit(main())
