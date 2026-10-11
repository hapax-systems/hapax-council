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
    load_or_create_key,
    mint_escape_grant,
    write_grant_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM = REPO_ROOT / "hooks" / "scripts" / "escape-grant.sh"

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

    def test_honored_ledger_line_carries_the_session(self, coord_env):
        _, env = coord_env
        _mint_grant(session="alpha-lane")
        env["HAPAX_SESSION_ID"] = "alpha-lane"
        allowed, out = _shim_allows("cc-task-gate", env)
        assert allowed, out
        honored = [r for r in _honored(env) if r.get("kind") == "escape_grant_honored"]
        assert honored, "the honored release must be ledgered"
        assert honored[0].get("session") == "alpha-lane", honored
