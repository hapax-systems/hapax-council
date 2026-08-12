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

# A stand-in for `systemctl --user` driven by two fixture files. It deliberately
# ignores any unit-name pattern it is passed, so the script cannot lean on
# systemctl's own filtering — the scope guards must be in the script.
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
mode=""
for a in "$@"; do
    case "$a" in
        list-unit-files) mode=list ;;
        is-active) mode=isactive ;;
        daemon-reload|disable) mode=noop ;;
    esac
done

case "$mode" in
    list)
        cat "$FAKE_UNIT_FILES"
        ;;
    isactive)
        unit="${@: -1}"
        state="$(awk -v u="$unit" '$1==u{print $2}' "$FAKE_ACTIVE_STATES")"
        [ -n "$state" ] || state=inactive
        echo "$state"
        [ "$state" = active ] || exit 3
        ;;
esac
exit 0
"""


def _fake_systemctl(
    tmp_path: Path,
    unit_files: str,
    active_states: str,
) -> tuple[Path, dict[str, str]]:
    """Build a fake systemctl plus the env that points the script at it.

    ``unit_files`` mimics ``list-unit-files`` output (``NAME STATE PRESET``);
    ``active_states`` maps ``NAME STATE`` for ``is-active``.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "fake-systemctl"
    stub.write_text(FAKE_SYSTEMCTL, encoding="utf-8")
    stub.chmod(0o755)
    unit_files_path = tmp_path / "unit-files.txt"
    unit_files_path.write_text(unit_files, encoding="utf-8")
    active_path = tmp_path / "active-states.txt"
    active_path.write_text(active_states, encoding="utf-8")
    return stub, {
        "FAKE_UNIT_FILES": str(unit_files_path),
        "FAKE_ACTIVE_STATES": str(active_path),
    }


def _run_with_fake_systemd(
    tmp_path: Path,
    *args: str,
    user_dir: Path | None = None,
    repo_units: Path | None = None,
    systemctl: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_user_dir = user_dir or tmp_path / "systemd-user"
    fake_repo_units = repo_units or tmp_path / "repo-units"
    fake_user_dir.mkdir(parents=True, exist_ok=True)
    fake_repo_units.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HAPAX_SYSTEMD_USER_DIR"] = str(fake_user_dir)
    env["HAPAX_SYSTEMD_REPO_UNITS"] = str(fake_repo_units)
    env["HAPAX_SYSTEMCTL"] = str(systemctl) if systemctl else "true"
    env.update(extra_env or {})
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


MIXED_UNIT_FILES = """UNIT FILE                      STATE    PRESET
hapax-lane-reaper.timer        enabled  enabled
hapax-cc-pr-autoqueue.timer    enabled  enabled
hapax-lane-idle-watchdog.timer disabled enabled
hapax-daimonion.service        enabled  enabled
dbus-broker.timer              enabled  enabled

5 unit files listed.
"""

MIXED_ACTIVE_STATES = """hapax-lane-reaper.timer inactive
hapax-cc-pr-autoqueue.timer active
hapax-lane-idle-watchdog.timer inactive
hapax-daimonion.service inactive
dbus-broker.timer inactive
"""


class TestDeadTimerDetection:
    """`enabled` is not `running` — an enabled+inactive timer never fires.

    A monotonic timer (OnBootSec+OnUnitActiveSec) that misses an activation has
    no next elapse point and stays dead until something starts it. The estate
    had no assertion anywhere that an enabled unit is also active, which is how
    hapax-pr-review-dispatch.timer sat dead for four weeks while its consumers
    polled for output nothing was producing.
    """

    def _run(
        self, tmp_path: Path, *args: str, unit_files: str, active_states: str
    ) -> subprocess.CompletedProcess[str]:
        stub, env = _fake_systemctl(tmp_path, unit_files, active_states)
        return _run_with_fake_systemd(tmp_path, *args, systemctl=stub, extra_env=env)

    def test_enabled_but_inactive_timer_is_reported_by_name(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, unit_files=MIXED_UNIT_FILES, active_states=MIXED_ACTIVE_STATES)

        assert r.returncode == 1, f"stdout={r.stdout!r} stderr={r.stderr!r}"
        assert "hapax-lane-reaper.timer" in r.stdout
        assert "1 enabled timer" in r.stdout

    def test_enabled_and_active_timer_is_not_reported(self, tmp_path: Path) -> None:
        r = self._run(tmp_path, unit_files=MIXED_UNIT_FILES, active_states=MIXED_ACTIVE_STATES)

        assert "hapax-cc-pr-autoqueue.timer" not in r.stdout

    def test_disabled_and_inactive_timer_is_not_reported(self, tmp_path: Path) -> None:
        """Only enabled+inactive is a fault; disabled+inactive is the intent."""
        r = self._run(tmp_path, unit_files=MIXED_UNIT_FILES, active_states=MIXED_ACTIVE_STATES)

        assert "hapax-lane-idle-watchdog.timer" not in r.stdout

    def test_enabled_inactive_service_is_not_reported(self, tmp_path: Path) -> None:
        """Oneshot services are inactive between runs — only timers are asserted."""
        r = self._run(tmp_path, unit_files=MIXED_UNIT_FILES, active_states=MIXED_ACTIVE_STATES)

        assert "hapax-daimonion.service" not in r.stdout

    def test_non_hapax_timer_is_not_reported(self, tmp_path: Path) -> None:
        """Scope is the Hapax estate; foreign units are not this script's business."""
        r = self._run(tmp_path, unit_files=MIXED_UNIT_FILES, active_states=MIXED_ACTIVE_STATES)

        assert "dbus-broker.timer" not in r.stdout

    def test_verdict_flips_with_liveness(self, tmp_path: Path) -> None:
        """Mutation check: the same unit set, only liveness differs, opposite verdicts."""
        dead = self._run(
            tmp_path / "dead",
            unit_files="hapax-lane-reaper.timer enabled enabled\n",
            active_states="hapax-lane-reaper.timer inactive\n",
        )
        alive = self._run(
            tmp_path / "alive",
            unit_files="hapax-lane-reaper.timer enabled enabled\n",
            active_states="hapax-lane-reaper.timer active\n",
        )

        assert dead.returncode == 1
        assert "hapax-lane-reaper.timer" in dead.stdout
        assert alive.returncode == 0
        assert "hapax-lane-reaper.timer" not in alive.stdout

    def test_enabled_runtime_counts_as_enabled(self, tmp_path: Path) -> None:
        r = self._run(
            tmp_path,
            unit_files="hapax-transient.timer enabled-runtime enabled\n",
            active_states="hapax-transient.timer inactive\n",
        )

        assert r.returncode == 1
        assert "hapax-transient.timer" in r.stdout

    def test_failed_timer_is_reported_with_its_state(self, tmp_path: Path) -> None:
        r = self._run(
            tmp_path,
            unit_files="hapax-broken.timer enabled enabled\n",
            active_states="hapax-broken.timer failed\n",
        )

        assert r.returncode == 1
        assert "hapax-broken.timer" in r.stdout
        assert "failed" in r.stdout

    def test_static_timer_is_not_reported(self, tmp_path: Path) -> None:
        """A static unit has no [Install] section — it is not `enabled` to begin with."""
        r = self._run(
            tmp_path,
            unit_files="hapax-static.timer static -\n",
            active_states="hapax-static.timer inactive\n",
        )

        assert r.returncode == 0
        assert "hapax-static.timer" not in r.stdout

    def test_dead_timer_reported_alongside_drift(self, tmp_path: Path) -> None:
        """Both faults surface in one run — neither check masks the other."""
        user_dir = tmp_path / "systemd-user"
        repo_units = tmp_path / "repo-units"
        user_dir.mkdir()
        repo_units.mkdir()
        (user_dir / "hapax-gone.service").symlink_to(repo_units / "hapax-gone.service")
        stub, env = _fake_systemctl(
            tmp_path,
            "hapax-lane-reaper.timer enabled enabled\n",
            "hapax-lane-reaper.timer inactive\n",
        )

        r = _run_with_fake_systemd(
            tmp_path,
            user_dir=user_dir,
            repo_units=repo_units,
            systemctl=stub,
            extra_env=env,
        )

        assert r.returncode == 1
        assert "hapax-gone.service" in r.stdout
        assert "hapax-lane-reaper.timer" in r.stdout

    def test_dead_timer_survives_apply(self, tmp_path: Path) -> None:
        """--apply repairs drift; it deliberately does not start timers, so the
        report — and the non-zero exit — must survive it."""
        r = self._run(
            tmp_path,
            "--apply",
            unit_files="hapax-lane-reaper.timer enabled enabled\n",
            active_states="hapax-lane-reaper.timer inactive\n",
        )

        assert r.returncode == 1
        assert "hapax-lane-reaper.timer" in r.stdout

    def test_quiet_still_names_dead_timers(self, tmp_path: Path) -> None:
        """--quiet suppresses chatter, not findings."""
        r = self._run(
            tmp_path,
            "--quiet",
            unit_files="hapax-lane-reaper.timer enabled enabled\n",
            active_states="hapax-lane-reaper.timer inactive\n",
        )

        assert r.returncode == 1
        assert "hapax-lane-reaper.timer" in r.stdout

    def test_report_does_not_claim_repair(self, tmp_path: Path) -> None:
        """Starting a timer is a runtime act — the reconciler reports only."""
        r = self._run(
            tmp_path,
            unit_files="hapax-lane-reaper.timer enabled enabled\n",
            active_states="hapax-lane-reaper.timer inactive\n",
        )

        assert "runtime" in r.stdout.lower()
        assert "started hapax-lane-reaper.timer" not in r.stdout.lower()


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
