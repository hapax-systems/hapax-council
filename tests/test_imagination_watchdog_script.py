"""Tests for scripts/hapax-imagination-watchdog.sh.

The watchdog is a thin bash script, so the tests drive it through env
variables + `HAPAX_IMAG_WATCHDOG_DRY_RUN=1` to assert the decision logic
without actually restarting any systemd unit.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hapax-imagination-watchdog.sh"


def _run_watchdog(
    *,
    watch_file: Path,
    stale_s: int,
    unit: str = "hapax-imagination-loop.service",
) -> tuple[int, str]:
    """Invoke the watchdog in dry-run mode; return (exit_code, stdout)."""
    env = os.environ.copy()
    env["HAPAX_IMAG_WATCHDOG_FILE"] = str(watch_file)
    env["HAPAX_IMAG_WATCHDOG_STALE_S"] = str(stale_s)
    env["HAPAX_IMAG_WATCHDOG_UNIT"] = unit
    env["HAPAX_IMAG_WATCHDOG_DRY_RUN"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_fresh_file_no_restart(tmp_path: Path) -> None:
    """A file written 'just now' is below the staleness threshold."""
    f = tmp_path / "current.json"
    f.write_text("{}")
    code, out = _run_watchdog(watch_file=f, stale_s=600)
    assert code == 0
    assert "restarting" not in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_stale_file_triggers_restart(tmp_path: Path) -> None:
    """A file older than the threshold triggers the restart branch."""
    f = tmp_path / "current.json"
    f.write_text("{}")
    # Backdate mtime by 700s — past the default 600s threshold.
    backdated = time.time() - 700
    os.utime(f, (backdated, backdated))
    code, out = _run_watchdog(watch_file=f, stale_s=600)
    assert code == 0
    assert "restarting" in out
    assert "DRY RUN — skipping restart" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_missing_file_triggers_restart(tmp_path: Path) -> None:
    """When current.json is absent the loop is presumed dead — restart."""
    f = tmp_path / "does-not-exist.json"
    code, out = _run_watchdog(watch_file=f, stale_s=600)
    assert code == 0
    assert "watch file missing" in out
    assert "restarting" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_zero_threshold_always_triggers(tmp_path: Path) -> None:
    """STALE_S=0 forces the restart branch regardless of mtime — useful
    for emergency restart loops or operator-driven test pulses."""
    f = tmp_path / "current.json"
    f.write_text("{}")
    code, out = _run_watchdog(watch_file=f, stale_s=0)
    assert code == 0
    assert "restarting" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_warning_at_half_threshold(tmp_path: Path) -> None:
    """Files past 50 % of the threshold log a 'approaching stale' warning
    so journal grep can spot trends before the restart fires."""
    f = tmp_path / "current.json"
    f.write_text("{}")
    # Backdate to 60 % of threshold.
    backdated = time.time() - 360  # 360s of 600s threshold
    os.utime(f, (backdated, backdated))
    code, out = _run_watchdog(watch_file=f, stale_s=600)
    assert code == 0
    assert "approaching stale" in out
    assert "restarting" not in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_quiet_steady_state(tmp_path: Path) -> None:
    """A fresh file well below the warning band emits no log lines —
    quiet steady-state is mandatory so the timer doesn't spam journal."""
    f = tmp_path / "current.json"
    f.write_text("{}")
    code, out = _run_watchdog(watch_file=f, stale_s=600)
    assert code == 0
    assert out.strip() == ""
