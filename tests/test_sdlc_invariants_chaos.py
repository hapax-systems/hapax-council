"""Runtime evaluator + daemon-kill chaos tests for the SDLC never-stuck invariants.

Coordination reform §4.5 (CASE-FORMAL-GOVERNANCE-001). The TLA+ invariants ship as
RUNTIME trace checks the system evaluates continuously against the live ledger. A
violation is ledgered (advisory-with-ledger), and an INV-3/4/5 violation additionally
AUTO-MINTS the relevant escape — it NEVER freezes the system. INV-4 is the central
correction: the escape must survive a DEAD kernel, so the daemon-kill chaos test below
kills a real daemon process and asserts a hand-written signed grant still unblocks a
lane via the daemon-independent (pure file-read + signature) decision path.
"""

import os
import socket
import stat
import subprocess
import sys
import time
import uuid

from shared.governance.coord_capabilities import (
    mint_escape_grant,
    read_grant_file,
    write_grant_file,
)
from shared.sdlc_invariants import (
    AUTO_MINT_INVARIANTS,
    ESCAPE_GRANTOR,
    InvariantResult,
    Ladder,
    decide_with_escape,
    load_or_create_grant_key,
    mint_escape_for_violation,
    run_evaluator,
)

# A fixed 32-byte key — the monitor and the shim share one key path at runtime.
_KEY = b"chaos-test-key-deterministic-32b"
_NOW = 1_000_000.0


def _violation(invariant: str, name: str = "x") -> InvariantResult:
    return InvariantResult(invariant, name, holds=False, violations=("boom",), advisory="fix it")


# --- decide_with_escape: the daemon-down floor + grant carve-out --------------


class TestDecideWithEscape:
    def test_reversible_op_allowed_without_grant(self):
        d = decide_with_escape("Edit", file_path="shared/x.py", grant=None, key=_KEY, now=_NOW)
        assert d.allowed

    def test_irreversible_op_blocked_without_grant(self):
        d = decide_with_escape("Bash", command="gh pr merge 1", grant=None, key=_KEY, now=_NOW)
        assert d.blocked
        assert d.gate == "floor:merge"

    def test_valid_grant_unblocks_irreversible_op(self):
        grant = mint_escape_grant(
            grantor="operator", scope="*", reason="r", ttl_s=3600, key=_KEY, now=_NOW
        )
        d = decide_with_escape("Bash", command="gh pr merge 1", grant=grant, key=_KEY, now=_NOW)
        assert d.allowed
        assert d.gate == "escape:granted"

    def test_expired_grant_does_not_unblock(self):
        grant = mint_escape_grant(
            grantor="operator", scope="*", reason="r", ttl_s=10, key=_KEY, now=_NOW
        )
        d = decide_with_escape(
            "Bash", command="gh pr merge 1", grant=grant, key=_KEY, now=_NOW + 100
        )
        assert d.blocked

    def test_grant_signed_with_wrong_key_does_not_unblock(self):
        grant = mint_escape_grant(
            grantor="operator", scope="*", reason="r", ttl_s=3600, key=b"a-different-key", now=_NOW
        )
        d = decide_with_escape("Bash", command="gh pr merge 1", grant=grant, key=_KEY, now=_NOW)
        assert d.blocked

    def test_scoped_grant_only_covers_its_gate(self):
        # a grant scoped to floor:egress must NOT unblock a merge
        grant = mint_escape_grant(
            grantor="operator", scope="floor:egress", reason="r", ttl_s=3600, key=_KEY, now=_NOW
        )
        d = decide_with_escape("Bash", command="gh pr merge 1", grant=grant, key=_KEY, now=_NOW)
        assert d.blocked


# --- mint_escape_for_violation ------------------------------------------------


class TestMintEscapeForViolation:
    def test_holds_mints_nothing(self, tmp_path):
        ok = InvariantResult("INV-3", "escape", holds=True, violations=(), advisory="")
        assert mint_escape_for_violation(ok, key=_KEY, grant_dir=tmp_path, now=_NOW) is None

    def test_inv1_violation_is_not_auto_mint(self, tmp_path):
        assert (
            mint_escape_for_violation(_violation("INV-1"), key=_KEY, grant_dir=tmp_path, now=_NOW)
            is None
        )

    def test_inv2_violation_is_not_auto_mint(self, tmp_path):
        assert (
            mint_escape_for_violation(_violation("INV-2"), key=_KEY, grant_dir=tmp_path, now=_NOW)
            is None
        )

    def test_no_key_mints_nothing(self, tmp_path):
        assert (
            mint_escape_for_violation(_violation("INV-3"), key=b"", grant_dir=tmp_path, now=_NOW)
            is None
        )

    def test_inv3_4_5_violation_mints_universal_grant(self, tmp_path):
        for inv in ("INV-3", "INV-4", "INV-5"):
            grant = mint_escape_for_violation(
                _violation(inv), key=_KEY, grant_dir=tmp_path, now=_NOW
            )
            assert grant is not None
            assert grant.scope == "*"
            assert grant.grantor == ESCAPE_GRANTOR
            assert inv in grant.reason
            # the grant was written to disk as <grant_id>.grant — the extension the
            # live shim globs, NOT the old <slug>-<id>.json — and round-trips
            grant_file = tmp_path / f"{grant.grant_id}.grant"
            assert grant_file.exists()
            assert read_grant_file(grant_file) == grant

    def test_minted_grant_actually_unblocks_a_lane(self, tmp_path):
        grant = mint_escape_for_violation(
            _violation("INV-4"), key=_KEY, grant_dir=tmp_path, now=_NOW
        )
        d = decide_with_escape("Bash", command="gh pr merge 1", grant=grant, key=_KEY, now=_NOW)
        assert d.allowed


# --- load_or_create_grant_key -------------------------------------------------


class TestLoadOrCreateGrantKey:
    def test_creates_key_0600_when_absent(self, tmp_path):
        path = tmp_path / "sub" / "coord.key"
        key = load_or_create_grant_key(path)
        assert len(key) == 32
        assert path.exists()
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    def test_reads_existing_key(self, tmp_path):
        path = tmp_path / "coord.key"
        path.write_bytes(b"existing-key-bytes")
        assert load_or_create_grant_key(path) == b"existing-key-bytes"

    def test_persisted_key_is_stable_across_calls(self, tmp_path):
        path = tmp_path / "coord.key"
        assert load_or_create_grant_key(path) == load_or_create_grant_key(path)


# --- run_evaluator: advisory-with-ledger, mints only INV-3/4/5 ----------------

_GOOD_LADDER = Ladder(
    stages=("S0", "S11", "BLOCKED"),
    transitions={"S0": frozenset({"S11"}), "S11": frozenset(), "BLOCKED": frozenset({"S0"})},
    terminal=frozenset({"S11"}),
    blocked=frozenset({"BLOCKED"}),
)
#: BLOCKED has no escape edge — violates INV-3 (and, since BLOCKED is non-terminal
#: with no successor, INV-1 too). Used to drive an auto-mint.
_NO_ESCAPE_LADDER = Ladder(
    stages=("S0", "S11", "BLOCKED"),
    transitions={"S0": frozenset({"S11"}), "S11": frozenset(), "BLOCKED": frozenset()},
    terminal=frozenset({"S11"}),
    blocked=frozenset({"BLOCKED"}),
)


class TestRunEvaluator:
    def test_clean_ladder_no_violations_no_mint(self, tmp_path):
        report = run_evaluator(
            (),
            now=_NOW,
            ladder=_GOOD_LADDER,
            findings_path=tmp_path / "findings.jsonl",
            grant_dir=tmp_path / "grants",
            key=_KEY,
            alert=False,
        )
        assert report.violations == ()
        assert report.minted == ()

    def test_inv2_stuck_task_ledgered_but_not_minted(self, tmp_path):
        # a task stuck at a non-terminal stage far in the past → INV-2 liveness violation
        trace = [{"task_id": "t1", "to_stage": "S6", "timestamp": 0.0}]
        findings = tmp_path / "findings.jsonl"
        report = run_evaluator(
            trace,
            now=_NOW,
            stale_after_s=10.0,
            ladder=_GOOD_LADDER,
            findings_path=findings,
            grant_dir=tmp_path / "grants",
            key=_KEY,
            alert=False,
        )
        assert "INV-2" in report.violations
        assert report.minted == ()  # INV-2 is not an auto-mint class
        assert findings.exists()  # the violation was ledgered

    def test_inv3_violation_auto_mints_escape(self, tmp_path):
        grant_dir = tmp_path / "grants"
        report = run_evaluator(
            (),
            now=_NOW,
            ladder=_NO_ESCAPE_LADDER,
            findings_path=tmp_path / "findings.jsonl",
            grant_dir=grant_dir,
            key=_KEY,
            alert=False,
        )
        assert "INV-3" in report.violations
        assert "INV-1" in report.violations  # the dead-end also breaks deadlock-freedom
        # exactly one grant minted — for INV-3 (the auto-mint class), never for INV-1
        assert len(report.minted) == 1
        assert "INV-3" in report.minted[0].reason
        assert (grant_dir / f"{report.minted[0].grant_id}.grant").exists()

    def test_no_key_ledgers_but_cannot_mint(self, tmp_path):
        report = run_evaluator(
            (),
            now=_NOW,
            ladder=_NO_ESCAPE_LADDER,
            findings_path=tmp_path / "findings.jsonl",
            grant_dir=tmp_path / "grants",
            key=b"",
            alert=False,
        )
        assert "INV-3" in report.violations
        assert report.minted == ()  # no key → no verifiable grant, ledger-only

    def test_never_raises_on_garbage_trace(self, tmp_path):
        report = run_evaluator(
            [{"nonsense": object()}],
            now=_NOW,
            ladder=_GOOD_LADDER,
            findings_path=tmp_path / "findings.jsonl",
            grant_dir=tmp_path / "grants",
            key=_KEY,
            alert=False,
        )
        assert isinstance(report.violations, tuple)


# --- THE daemon-kill chaos test (INV-4 acceptance) ----------------------------


def _abstract_name(token: str) -> str:
    """Linux abstract-namespace UDS name (leading NUL) — auto-vanishes when the daemon dies."""
    return "\0" + token


def _kernel_up(token: str) -> bool:
    """Probe daemon liveness by connecting to its abstract UDS. No daemon ⇒ ECONNREFUSED."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(_abstract_name(token))
        return True
    except OSError:
        return False
    finally:
        sock.close()


_DAEMON_SRC = """
import socket, sys, pathlib, time
token, ready = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.bind("\\0" + token)          # abstract namespace — no on-disk file to clean up
s.listen(8)
pathlib.Path(ready).write_text("ready")
while True:
    time.sleep(3600)
"""


class TestDaemonKillChaos:
    def test_handwritten_grant_unblocks_lane_with_daemon_dead(self, tmp_path):
        token = f"hapax-coord-chaos-{uuid.uuid4().hex[:12]}"
        ready = tmp_path / "ready"
        proc = subprocess.Popen([sys.executable, "-c", _DAEMON_SRC, token, str(ready)])
        try:
            # 1. the coord daemon comes up and is reachable
            deadline = time.time() + 5.0
            while time.time() < deadline and not ready.exists():
                time.sleep(0.02)
            assert ready.exists(), "fake coord daemon did not start"
            assert _kernel_up(token), "daemon should be reachable while alive"

            merge = {"tool_name": "Bash", "command": "gh pr merge 1 --merge"}

            # 2. KILL the daemon (the chaos event) and confirm the kernel is DOWN
            proc.kill()
            proc.wait(timeout=5)
            assert not _kernel_up(token), "kernel must read as DOWN after the daemon is killed"

            # 3. with the kernel dead and no grant, an irreversible op is blocked (fail-closed)
            blocked = decide_with_escape(**merge, grant=None, key=_KEY, now=_NOW)
            assert blocked.blocked
            assert blocked.gate == "floor:merge"

            # 4. the operator HAND-WRITES a signed escape grant to disk (no daemon involved)
            grant = mint_escape_grant(
                grantor="operator",
                scope="*",
                reason="chaos: hand-written escape with the kernel down",
                ttl_s=3600,
                key=_KEY,
                now=_NOW,
            )
            grant_file = tmp_path / "escape.grant"
            write_grant_file(grant, grant_file)

            # 5. the lane reads the grant directly from disk — the daemon is STILL dead —
            #    and is unblocked. Escape never depended on the process it governs (INV-4).
            assert not _kernel_up(token)
            loaded = read_grant_file(grant_file)
            allowed = decide_with_escape(**merge, grant=loaded, key=_KEY, now=_NOW)
            assert allowed.allowed, (
                "a valid signed grant must unblock the lane with the daemon dead"
            )
            assert allowed.gate == "escape:granted"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_auto_mint_invariants_are_the_escape_class():
    """Guard: only the escape-class invariants auto-mint (INV-1/2 are ledger-only)."""
    assert frozenset({"INV-3", "INV-4", "INV-5"}) == AUTO_MINT_INVARIANTS
