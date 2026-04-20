"""Tests for scripts/hapax-quiet-frame CLI (D-17)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from shared.governance.quiet_frame import QUIET_FRAME_PROGRAMME_ID
from shared.programme import ProgrammeStatus
from shared.programme_store import ProgrammePlanStore

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-quiet-frame"


class TestScriptPresent:
    def test_script_exists_and_executable(self) -> None:
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111


class TestHelp:
    def test_help_exits_zero(self) -> None:
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode == 0
        assert "activate" in r.stdout
        assert "deactivate" in r.stdout
        assert "status" in r.stdout

    def test_missing_subcommand_exits_two(self) -> None:
        r = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=10
        )
        assert r.returncode == 2


class TestSubprocessRoundTrip:
    """Full CLI round-trip via subprocess with --store-path override."""

    def test_activate_status_deactivate(self, tmp_path: Path) -> None:
        store_path = tmp_path / "programmes.jsonl"

        def _run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--store-path",
                    str(store_path),
                    *args,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

        r = _run("activate", "--duration", "120", "--reason", "test")
        assert r.returncode == 0, r.stderr
        assert "ACTIVE" in r.stdout

        # Verify via the store directly.
        store = ProgrammePlanStore(path=store_path)
        active = store.active_programme()
        assert active is not None
        assert active.programme_id == QUIET_FRAME_PROGRAMME_ID

        r = _run("status")
        assert r.returncode == 0
        assert "active_now" in r.stdout

        r = _run("deactivate")
        assert r.returncode == 0
        assert "COMPLETED" in r.stdout

        reloaded = ProgrammePlanStore(path=store_path).get(QUIET_FRAME_PROGRAMME_ID)
        assert reloaded is not None
        assert reloaded.status == ProgrammeStatus.COMPLETED

    def test_deactivate_when_not_active_exits_one(self, tmp_path: Path) -> None:
        store_path = tmp_path / "programmes.jsonl"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--store-path", str(store_path), "deactivate"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 1
        assert "not active" in r.stderr

    def test_status_on_empty_store(self, tmp_path: Path) -> None:
        store_path = tmp_path / "programmes.jsonl"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--store-path", str(store_path), "status"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0
        assert "never activated" in r.stdout

    def test_duration_default_15_min(self, tmp_path: Path) -> None:
        """Default activate uses QUIET_FRAME_DEFAULT_DURATION_S (15 min / 900s)."""
        from shared.governance.quiet_frame import QUIET_FRAME_DEFAULT_DURATION_S

        store_path = tmp_path / "programmes.jsonl"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--store-path", str(store_path), "activate"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0
        assert f"duration={QUIET_FRAME_DEFAULT_DURATION_S:.0f}s" in r.stdout
