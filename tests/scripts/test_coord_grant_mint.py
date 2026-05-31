"""Tests for scripts/coord-grant-mint (reform Phase 4, NEW-2).

The operator's daemon-independent grant minter: writes a signed, scoped,
time-boxed EscapeGrant file that the irreversible-harm shims read directly off
disk (no RPC). This is the sanctioned replacement for the deprecated, silent,
unconditional HAPAX_*_OFF off-switch.
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


def _run(args: list[str], *, grant_dir: Path, key: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HAPAX_COORD_GRANT_DIR"] = str(grant_dir)
    env["HAPAX_COORD_GRANT_KEY"] = str(key)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestCoordGrantMint:
    def test_mints_grant_into_grant_dir(self, tmp_path: Path) -> None:
        grant_dir = tmp_path / "grants"
        key = tmp_path / "grant-key"
        r = _run(
            ["--scope", "cc-task-gate", "--reason", "stale-worktree deadlock", "--ttl", "120"],
            grant_dir=grant_dir,
            key=key,
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        grants = list(grant_dir.glob("*.grant"))
        assert len(grants) == 1, f"expected one grant file, got {grants}"
        # The printed path is the grant file.
        assert r.stdout.strip() == str(grants[0])

    def test_autocreates_signing_key_mode_0600(self, tmp_path: Path) -> None:
        grant_dir = tmp_path / "grants"
        key = tmp_path / "grant-key"
        assert not key.exists()
        r = _run(["--scope", "cc-task-gate"], grant_dir=grant_dir, key=key)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert key.exists(), "signing key must be auto-created on first mint"
        assert oct(key.stat().st_mode & 0o777) == "0o600", "key must not be world-readable"

    def test_minted_grant_verifies_for_its_scope_only(self, tmp_path: Path) -> None:
        grant_dir = tmp_path / "grants"
        key = tmp_path / "grant-key"
        _run(["--scope", "cc-task-gate", "--ttl", "300"], grant_dir=grant_dir, key=key)
        grant = read_grant_file(next(grant_dir.glob("*.grant")))
        key_bytes = key.read_bytes()
        now = time.time()
        assert verify_escape_grant(grant, key=key_bytes, now=now, gate="cc-task-gate")
        assert not verify_escape_grant(grant, key=key_bytes, now=now, gate="pr-release-gate")

    def test_reuses_existing_key(self, tmp_path: Path) -> None:
        grant_dir = tmp_path / "grants"
        key = tmp_path / "grant-key"
        existing = b"pre-existing-operator-key-0123456789ab"
        key.write_bytes(existing)
        _run(["--scope", "*", "--reason", "kernel down"], grant_dir=grant_dir, key=key)
        assert key.read_bytes() == existing, (
            "must reuse the operator's existing key, not regenerate"
        )
