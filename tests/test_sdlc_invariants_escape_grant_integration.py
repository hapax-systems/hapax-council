"""Cross-boundary integration: the real ``escape-grant.sh`` shim and the Python
grant substrate agree on SESSION-BOUND escape grants
(escape-grants-bind-to-the-minting-session-20261011): the minting session (and
optional narrowing paths) rides in the SIGNED payload; unbound grants — legacy
files — are refused with the next action "re-mint with your session". Drives
both the Python minter and the bash shim through the same canonical resolvers
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
    load_or_create_key,
    mint_escape_grant,
    write_grant_file,
)
from shared.sdlc_invariants import (
    ESCAPE_AUTO_MINT_SESSION,
    Ladder,
    run_evaluator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "hooks" / "scripts" / "escape-grant.sh"

NEXT_ACTION = "re-mint with your session"

#: The session env chain mirrored from agent-role.sh hapax_session_id().
_SESSION_ENV_VARS = (
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)

#: A ladder whose BLOCKED state has no escape edge → a genuine INV-3 violation
#: that ``run_evaluator`` auto-mints for.
_NO_ESCAPE_LADDER = Ladder(
    stages=("S0", "S11", "BLOCKED"),
    transitions={"S0": frozenset({"S11"}), "S11": frozenset(), "BLOCKED": frozenset()},
    terminal=frozenset({"S11"}),
    blocked=frozenset({"BLOCKED"}),
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
class TestSessionBoundShimRoundTrip:
    def test_minting_session_is_released(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane")
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, f"real shim refused the minting session's grant:\n{out}"

    def test_other_session_is_not_released(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane")
        env["HAPAX_SESSION_ID"] = "beta-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert not allowed, f"a grant minted by alpha-lane released beta-lane:\n{out}"

    def test_legacy_unbound_grant_refused_with_next_action(self, coord_env):
        _, env = coord_env
        _mint_grant()  # no session → the legacy grant shape
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert not allowed, "an unbound (legacy) grant must not be honored:\n" + out
        assert NEXT_ACTION in out, f"the refusal must surface the next action:\n{out}"

    def test_path_narrowed_grant_releases_only_its_paths(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane", paths=("/srv/release/a.py",))
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env, path="/srv/release/a.py")
        assert allowed, f"a path-narrowed grant must release its named path:\n{out}"
        allowed_other, out_other = _shim_allows("cc-task-gate", env, path="/srv/other/b.py")
        assert not allowed_other, f"a path-narrowed grant released an unnamed path:\n{out_other}"

    def test_honored_ledger_line_carries_the_session(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane")
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, out
        honored = [r for r in _honored(env) if r.get("kind") == "escape_grant_honored"]
        assert honored, "the honored release must be ledgered"
        assert honored[0].get("session") == "alpha-lane", honored

    def test_run_evaluator_inv3_auto_mint_binds_to_the_evaluator_identity(self, coord_env):
        # The INV-3/4/5 auto-mint binds to a session source (explicit session →
        # env chain → ESCAPE_AUTO_MINT_SESSION); with the chain scrubbed it binds
        # to the deterministic evaluator identity, so it never mints unbound —
        # and it still releases no arbitrary lane.
        coord, env = coord_env

        # Control: with no grant minted yet, the REAL shim MUST deny.
        allowed_before, out = _shim_allows("floor:merge", env)
        assert not allowed_before, f"shim allowed with an empty grant dir:\n{out}"

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
        assert inv3[0].session == ESCAPE_AUTO_MINT_SESSION, (
            f"auto-mint bound to {inv3[0].session!r}, expected the evaluator identity"
        )

        # Canonical contract still holds: <coord>/grants/<grant_id>.grant on disk.
        minted = default_grant_dir() / f"{inv3[0].grant_id}.grant"
        found = sorted(p.name for p in default_grant_dir().glob("*"))
        assert minted.exists(), f"auto-mint did not write {minted} ({found})"

        # THE cross-boundary assertion: the evaluator-bound auto-mint is REFUSED
        # for a different lane, with the next action surfaced.
        env["HAPAX_SESSION_ID"] = "some-lane"
        allowed, out = _shim_allows("floor:merge", env)
        assert not allowed, f"real shim released another lane's auto-minted grant:\n{out}"
        assert NEXT_ACTION in out, f"the refusal must surface the next action:\n{out}"
