"""Tests for scripts/coord-grant-mint (reform Phase 4, NEW-2).

The operator's daemon-independent grant minter: writes a signed, scoped,
time-boxed EscapeGrant file that the irreversible-harm shims read directly off
disk (no RPC). This is the sanctioned replacement for the deprecated, silent,
unconditional HAPAX_*_OFF off-switch.

escape-grants-bind-to-the-minting-session-20261011: a minted grant records the
minting session (resolved from the session env chain, or --session) and role in
its signed payload, and refuses to mint when no session can be resolved — an
unbound grant releases every lane that hits the gate inside the TTL, which is
the defect this closes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "coord-grant-mint"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from shared.governance.coord_capabilities import (  # noqa: E402
    read_grant_file,
    verify_escape_grant,
)

#: The session/role env chain the script mirrors from agent-role.sh.
_SESSION_ENV_VARS = (
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_SESSION",
    "CODEX_THREAD_ID",
    "CODEX_THREAD_NAME",
)
_ROLE_ENV_VARS = ("HAPAX_AGENT_ROLE", "CODEX_ROLE", "CLAUDE_ROLE")


def _run(
    args: list[str],
    *,
    grant_dir: Path,
    key: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    for var in (*_SESSION_ENV_VARS, *_ROLE_ENV_VARS):
        env.pop(var, None)
    env["HAPAX_COORD_GRANT_DIR"] = str(grant_dir)
    env["HAPAX_COORD_GRANT_KEY"] = str(key)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _mint(tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None):
    """Run the minter with the canonical args plus per-test extras."""
    return _run(
        ["--scope", "cc-task-gate", *args],
        grant_dir=tmp_path / "grants",
        key=tmp_path / "grant-key",
        extra_env=extra_env,
    )


def _grant(tmp_path: Path):
    return read_grant_file(next((tmp_path / "grants").glob("*.grant")))


class TestCoordGrantMint:
    def test_mints_grant_into_grant_dir(self, tmp_path: Path) -> None:
        r = _mint(
            tmp_path,
            "--reason",
            "stale-worktree deadlock",
            "--ttl",
            "120",
            "--session",
            "test-lane",
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        grants = list((tmp_path / "grants").glob("*.grant"))
        assert len(grants) == 1, f"expected one grant file, got {grants}"
        # The printed path is the grant file.
        assert r.stdout.strip() == str(grants[0])

    def test_autocreates_signing_key_mode_0600(self, tmp_path: Path) -> None:
        key = tmp_path / "grant-key"
        assert not key.exists()
        r = _mint(tmp_path, "--session", "test-lane")
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert key.exists(), "signing key must be auto-created on first mint"
        assert oct(key.stat().st_mode & 0o777) == "0o600", "key must not be world-readable"

    def test_minted_grant_verifies_for_its_scope_only(self, tmp_path: Path) -> None:
        _mint(tmp_path, "--ttl", "300", "--session", "test-lane")
        grant = _grant(tmp_path)
        assert grant is not None and grant.session == "test-lane"
        key = (tmp_path / "grant-key").read_bytes()

        def verify(**kw: object) -> bool:
            return verify_escape_grant(grant, key=key, now=time.time(), **kw)

        assert verify(gate="cc-task-gate")
        assert not verify(gate="pr-release-gate")

    def test_reuses_existing_key(self, tmp_path: Path) -> None:
        key = tmp_path / "grant-key"
        existing = b"pre-existing-operator-key-0123456789ab"
        key.write_bytes(existing)
        r = _run(
            ["--scope", "*", "--reason", "kernel down", "--session", "test-lane"],
            grant_dir=tmp_path / "grants",
            key=tmp_path / "grant-key",
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert key.read_bytes() == existing, (
            "must reuse the operator's existing key, not regenerate"
        )


class TestCoordGrantMintSessionBinding:
    def test_refuses_to_mint_without_session(self, tmp_path: Path) -> None:
        r = _mint(tmp_path)
        assert r.returncode != 0, "minting without a resolvable session must fail narrow"
        assert "re-mint" not in r.stderr  # next action is about the SESSION, phrased below
        assert "session" in r.stderr.lower(), f"refusal must name the missing session: {r.stderr}"
        assert not list((tmp_path / "grants").glob("*.grant")), (
            "no grant file may be written on refusal"
        )

    def test_session_resolved_from_env(self, tmp_path: Path) -> None:
        r = _mint(tmp_path, extra_env={"HAPAX_SESSION_ID": "env-lane"})
        assert r.returncode == 0, f"stderr={r.stderr}"
        grant = _grant(tmp_path)
        assert grant is not None and grant.session == "env-lane"

    def test_explicit_session_overrides_env(self, tmp_path: Path) -> None:
        r = _mint(
            tmp_path,
            "--session",
            "flag-lane",
            extra_env={"HAPAX_SESSION_ID": "env-lane"},
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        grant = _grant(tmp_path)
        assert grant is not None and grant.session == "flag-lane"

    def test_role_resolved_from_env(self, tmp_path: Path) -> None:
        r = _mint(
            tmp_path,
            "--session",
            "test-lane",
            extra_env={"HAPAX_AGENT_ROLE": "glm-steward"},
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        grant = _grant(tmp_path)
        assert grant is not None and grant.role == "glm-steward"

    def test_path_flags_recorded(self, tmp_path: Path) -> None:
        r = _mint(tmp_path, "--session", "test-lane", "--path", "/srv/a.py", "--path", "/srv/b.py")
        assert r.returncode == 0, f"stderr={r.stderr}"
        grant = _grant(tmp_path)
        assert grant is not None and grant.paths == ("/srv/a.py", "/srv/b.py")
