"""Cross-boundary integration: the real ``escape-grant.sh`` shim and the Python
grant substrate agree on SESSION-RECORDED escape grants
(escape-grants-bind-to-the-minting-session-20261011, slice 1 of the split): the
minting session (and optional narrowing paths) rides in the SIGNED payload and
the shim's ``escape_grant_honored`` ledger line carries the session. Binding
ENFORCEMENT (refusing unbound / cross-session grants) is a later slice; here the
verifier still accepts every mechanically valid grant. Drives both the Python
minter and the bash shim through the same canonical resolvers
(``HAPAX_COORD_DIR`` redirected to a tmp tree); never touches the operator's
real ``~/.cache``.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from shared.coord_event_log import default_grant_dir, default_grant_key
from shared.governance.coord_capabilities import (
    EscapeGrant,
    _sign,
    load_or_create_key,
    mint_escape_grant,
    write_grant_file,
)
from shared.sdlc_invariants import (
    InvariantResult,
    Ladder,
    mint_escape_for_violation,
    run_evaluator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "hooks" / "scripts" / "escape-grant.sh"

#: A ladder whose BLOCKED state has no escape edge → a genuine INV-3 violation
#: that ``run_evaluator`` auto-mints for (mirrors the chaos test's no-escape
#: ladder, but here the minted grant must survive the REAL shim, not an
#: in-process key).
_NO_ESCAPE_LADDER = Ladder(
    stages=("S0", "S11", "BLOCKED"),
    transitions={"S0": frozenset({"S11"}), "S11": frozenset(), "BLOCKED": frozenset()},
    terminal=frozenset({"S11"}),
    blocked=frozenset({"BLOCKED"}),
)

#: The session env chain mirrored from agent-role.sh hapax_session_id().
_SESSION_ENV_VARS = (
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)


def _shim_allows(gate: str, env: dict[str, str], path: str | None = None) -> tuple[bool, str]:
    """Invoke the REAL ``escape-grant.sh`` exactly as an irreversible-harm shim
    does: set ``SCRIPT_DIR``, ``source`` the shim, then call ``escape_grant_allows``
    from inside an ``if`` (the shim's documented ``set -e``-safe contract)."""
    call = f"escape_grant_allows {gate}"
    if path is not None:
        call += f" {shlex.quote(path)}"
    script = (
        "set -uo pipefail; "
        f"export SCRIPT_DIR={SHIM.parent!s}; "
        f"source {SHIM!s}; "
        f"if {call}; then echo __ALLOW__; else echo __DENY__; fi"
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    return ("__ALLOW__" in proc.stdout), (proc.stdout + proc.stderr)


@pytest.fixture
def coord_env(tmp_path, monkeypatch):
    """Redirect the canonical coord tree (BOTH minter and shim) to a hermetic tmp
    dir, clear per-surface overrides AND the session env chain so each test binds
    sessions explicitly."""
    coord = tmp_path / "coord"
    for var in (
        "HAPAX_COORD_GRANT_DIR",
        "HAPAX_COORD_GRANT_KEY",
        "HAPAX_ESCAPE_GRANT_DIR",  # the OLD divergent dir override
        "HAPAX_COORD_GRANT_KEY_FILE",  # the OLD divergent key override
        *_SESSION_ENV_VARS,
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HAPAX_COORD_DIR", str(coord))
    # keep the shim's "grant honored" ledger out of the operator's real cache
    monkeypatch.setenv("HAPAX_METHODOLOGY_LEDGER", str(tmp_path / "methodology.jsonl"))
    # Post-#5130 the shim resolves its module binding through the activation
    # worktree and treats a host's live activation as authoritative; pin it to
    # the repo under test so a live release without this branch's grant
    # semantics can't shadow the code under test (same pin as the codex
    # headless / claude reviewer hook tests).
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_WORKTREE", str(REPO_ROOT))
    env = dict(os.environ)
    return coord, env


def _mint_grant(
    *,
    session: str = "",
    scope: str = "cc-task-gate",
    paths: tuple[str, ...] = (),
    ttl_s: float = 3600.0,
):
    """Mint + write a grant through the canonical resolvers (session='' = legacy/unbound)."""
    key = load_or_create_key(default_grant_key())
    grant = mint_escape_grant(
        grantor="operator",
        scope=scope,
        reason="test session-bound escape",
        ttl_s=ttl_s,
        key=key,
        now=time.time(),
        session=session,
        paths=paths,
    )
    write_grant_file(grant, default_grant_dir() / f"{grant.grant_id}.grant")
    return grant


def _honored(env: dict[str, str]) -> list[dict]:
    ledger = Path(env["HAPAX_METHODOLOGY_LEDGER"])
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


@pytest.mark.skipif(not SHIM.exists(), reason="escape-grant.sh shim absent")
@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="bash + python3 required for the real shim round-trip",
)
class TestAutoMintShimRoundTrip:
    def test_run_evaluator_inv3_mint_is_accepted_by_real_shim(self, coord_env):
        coord, env = coord_env

        # Control: with no grant minted yet, the REAL shim MUST deny — proves this
        # test is capable of failing (not trivially green).
        allowed_before, out = _shim_allows("floor:merge", env)
        assert not allowed_before, f"shim allowed with an empty grant dir:\n{out}"

        grant_dir = default_grant_dir()
        key = load_or_create_key(default_grant_key())

        report = run_evaluator(
            (),
            now=time.time(),
            ladder=_NO_ESCAPE_LADDER,
            findings_path=coord / "findings.jsonl",
            key=key,
            alert=False,
        )
        assert "INV-3" in report.violations
        inv3 = [g for g in report.minted if "INV-3" in g.reason]
        assert inv3, f"INV-3 did not auto-mint; minted reasons={[g.reason for g in report.minted]}"

        # Canonical contract: <coord>/grants/<grant_id>.grant (NOT <slug>-<id>.json).
        minted = grant_dir / f"{inv3[0].grant_id}.grant"
        found = sorted(p.name for p in grant_dir.glob("*")) if grant_dir.exists() else "NO DIR"
        assert minted.exists(), (
            f"auto-mint did not write {minted} — dir/extension divergence ({found})"
        )

        # THE cross-boundary assertion: the REAL shim's glob + HMAC verify accepts it.
        allowed, out = _shim_allows("floor:merge", env)
        assert allowed, f"real escape-grant.sh REJECTED the auto-minted grant:\n{out}"

    def test_mint_escape_for_violation_is_accepted_by_real_shim(self, coord_env):
        coord, env = coord_env
        key = load_or_create_key(default_grant_key())

        grant = mint_escape_for_violation(
            InvariantResult("INV-4", "authority", holds=False, violations=("boom",), advisory="x"),
            key=key,
            now=time.time(),
        )
        assert grant is not None
        minted = default_grant_dir() / f"{grant.grant_id}.grant"
        assert minted.exists(), f"auto-mint did not write {minted}"

        # universal "*" scope covers any gate the shim asks about
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, f"real escape-grant.sh REJECTED the auto-minted grant:\n{out}"


@pytest.mark.skipif(not SHIM.exists(), reason="escape-grant.sh shim absent")
@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="bash + python3 required for the real shim round-trip",
)
class TestSessionBoundShimRoundTrip:
    def test_minting_session_is_released(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane")
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, f"real shim refused the minting session's grant:\n{out}"

    def test_honored_ledger_line_carries_the_session(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane")
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, out
        honored = [r for r in _honored(env) if r.get("kind") == "escape_grant_honored"]
        assert honored, "the honored release must be ledgered"
        assert honored[0].get("session") == "alpha-lane", honored

    def test_honored_ledger_line_encodes_hostile_values(self, coord_env):
        """The honored line stays ONE valid JSON record with exact decoded
        values even when every interpolated field is hostile (S1 encoding
        repair): session/role arrive via env and function stubs, gate via the
        caller, grant_id (and so the grant_file name) via a directly signed
        grant — any of them may carry quotes, backslashes or newlines, and the
        ledger's parsers json-decode each physical line."""
        _, env = coord_env
        hostile = 'q"ote\\back\nslash'
        now = time.time()
        key = load_or_create_key(default_grant_key())
        fields = {
            "grant_id": hostile,
            "grantor": "operator",
            "scope": "*",
            "reason": "hostile-encoding pin",
            "issued_at": now,
            "expires_at": now + 3600.0,
        }
        payload = {"kind": "escape", **fields, "session": hostile, "paths": [], "role": hostile}
        grant = EscapeGrant(signature=_sign(payload, key), session=hostile, role=hostile, **fields)
        write_grant_file(grant, default_grant_dir() / f"{grant.grant_id}.grant")
        env["HAPAX_SESSION_ID"] = hostile
        env["HAPAX_TEST_HOSTILE_ROLE"] = hostile
        script = (
            "set -uo pipefail; "
            f"export SCRIPT_DIR={SHIM.parent!s}; "
            "hapax_effective_role() { printf '%s\\n' \"$HAPAX_TEST_HOSTILE_ROLE\"; }; "
            f"source {SHIM!s}; "
            f"if escape_grant_allows {shlex.quote(hostile)}; then echo __ALLOW__; else echo __DENY__; fi"
        )
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, env=env, cwd=str(REPO_ROOT)
        )
        assert "__ALLOW__" in proc.stdout, proc.stdout + proc.stderr
        ledger = Path(env["HAPAX_METHODOLOGY_LEDGER"])
        lines = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1, f"expected one ledger record, got {lines!r}"
        try:
            record = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            pytest.fail(f"ledger line is not one valid JSON record: {exc}: {lines[0]!r}")
        assert record["kind"] == "escape_grant_honored", record
        assert record["gate"] == hostile, record
        assert record["session"] == hostile, record
        assert record["role"] == hostile, record
        assert record["grant_id"] == hostile, record
        assert record["grant_file"].endswith(f"{hostile}.grant"), record
