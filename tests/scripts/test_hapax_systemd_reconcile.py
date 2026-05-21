"""Tests for scripts/hapax-systemd-reconcile.sh (D-21).

Exercises the script's dry-run + --apply paths via subprocess against
a fabricated REPO layout. Avoids touching the real systemd state by
stubbing systemctl + rm behavior through environment indirection is
not trivial in a bash script — instead, we rely on the simpler strategy
of invoking the real script against an EMPTY fabricated repo path and
the REAL systemctl list, confirming that either (a) the real host has
no drift (exit 0) or (b) drift is reported (exit 1) and the output
lists the drifted unit names.

These tests are smoke / contract checks — they verify argparse,
usage, and no-drift reporting. Full --apply path is NOT exercised here
to avoid mutating live systemd state; operator runs --apply manually.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-systemd-reconcile.sh"


def _run_with_fake_systemd(
    tmp_path: Path,
    *args: str,
    user_dir: Path | None = None,
    repo_units: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_user_dir = user_dir or tmp_path / "systemd-user"
    fake_repo_units = repo_units or tmp_path / "repo-units"
    fake_user_dir.mkdir(parents=True, exist_ok=True)
    fake_repo_units.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HAPAX_SYSTEMD_USER_DIR"] = str(fake_user_dir)
    env["HAPAX_SYSTEMD_REPO_UNITS"] = str(fake_repo_units)
    env["HAPAX_SYSTEMCTL"] = "true"
    return subprocess.run(
        [str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestScriptPresent:
    def test_script_exists_and_executable(self) -> None:
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111, "script must be executable"


class TestHelp:
    def test_help_exits_zero(self) -> None:
        r = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True, timeout=10)
        assert r.returncode == 0
        assert "dry-run" in r.stdout
        assert "--apply" in r.stdout

    def test_unknown_arg_exits_two(self) -> None:
        r = subprocess.run([str(SCRIPT), "--bogus"], capture_output=True, text=True, timeout=10)
        assert r.returncode == 2
        assert "unknown" in r.stderr.lower()


class TestDryRun:
    def test_dry_run_against_live_state(self) -> None:
        """Exercise against real systemctl — passes regardless of host drift state.

        Exit 0 = no drift; exit 1 = drift detected. Either is valid.
        The test asserts the script runs cleanly and produces output.
        """
        r = subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=30)
        assert r.returncode in (0, 1), (
            f"unexpected exit {r.returncode}; stdout={r.stdout!r} stderr={r.stderr!r}"
        )
        # Some output must be produced.
        assert r.stdout.strip()
        if r.returncode == 1:
            # Drift detected — output must name at least one unit.
            assert "drift" in r.stdout.lower() or "Detected" in r.stdout

    def test_dry_run_through_symlink_resolves_repo_root(self, tmp_path: Path) -> None:
        """Regression: deployed invocation comes through ~/.local/bin symlink."""
        linked_script = tmp_path / "hapax-systemd-reconcile.sh"
        linked_script.symlink_to(SCRIPT)

        r = subprocess.run([str(linked_script)], capture_output=True, text=True, timeout=30)

        assert r.returncode in (0, 1), (
            f"unexpected exit {r.returncode}; stdout={r.stdout!r} stderr={r.stderr!r}"
        )
        assert "not found" not in r.stderr
        assert ".local/systemd/units" not in r.stderr

    def test_dry_run_reports_broken_hapax_symlink_missing_from_systemctl(
        self, tmp_path: Path
    ) -> None:
        user_dir = tmp_path / "systemd-user"
        repo_units = tmp_path / "repo-units"
        user_dir.mkdir()
        repo_units.mkdir()
        (user_dir / "hapax-gone.service").symlink_to(repo_units / "hapax-gone.service")

        r = _run_with_fake_systemd(tmp_path, user_dir=user_dir, repo_units=repo_units)

        assert r.returncode == 1
        assert "hapax-gone.service" in r.stdout
        assert "Detected 1 drifted unit" in r.stdout

    def test_dry_run_ignores_repo_backed_hapax_symlink(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "systemd-user"
        repo_units = tmp_path / "repo-units"
        user_dir.mkdir()
        repo_units.mkdir()
        target = repo_units / "hapax-backed.service"
        target.write_text("[Unit]\nDescription=backed\n", encoding="utf-8")
        (user_dir / "hapax-backed.service").symlink_to(target)

        r = _run_with_fake_systemd(tmp_path, user_dir=user_dir, repo_units=repo_units)

        assert r.returncode == 0
        assert "no drift" in r.stdout.lower()

    def test_apply_removes_broken_hapax_symlink_idempotently(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "systemd-user"
        repo_units = tmp_path / "repo-units"
        user_dir.mkdir()
        repo_units.mkdir()
        stale_link = user_dir / "hapax-gone.timer"
        stale_link.symlink_to(repo_units / "hapax-gone.timer")

        first = _run_with_fake_systemd(
            tmp_path, "--apply", user_dir=user_dir, repo_units=repo_units
        )
        second = _run_with_fake_systemd(
            tmp_path, "--apply", user_dir=user_dir, repo_units=repo_units
        )

        assert first.returncode == 0
        assert "reconciled 1 unit" in first.stdout
        assert not stale_link.is_symlink()
        assert second.returncode == 0


class TestScriptNotes:
    def test_script_mentions_apply_vs_dry_run_semantics(self) -> None:
        """Script docstring names the two invocation modes."""
        contents = SCRIPT.read_text()
        assert "--apply" in contents
        assert "dry-run" in contents

    def test_script_mentions_linked_definition(self) -> None:
        """Docstring names the drift criterion so operators understand the scope."""
        contents = SCRIPT.read_text()
        assert "linked" in contents.lower()


@pytest.mark.skipif(
    not (Path.home() / ".config" / "systemd" / "user").exists(),
    reason="no user systemd dir — nothing to reconcile",
)
class TestIdempotenceContract:
    def test_second_dry_run_matches_first(self) -> None:
        """Two dry-runs back-to-back produce the same exit code."""
        first = subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=30)
        second = subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=30)
        assert first.returncode == second.returncode
