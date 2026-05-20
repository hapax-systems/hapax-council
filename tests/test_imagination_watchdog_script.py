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
    source_dir: Path | None = None,
    fresh_paths: list[Path] | None = None,
    state_dir: Path | None = None,
    state_file: Path | None = None,
    cooldown_s: int | None = None,
    dry_run: bool = True,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Invoke the watchdog in dry-run mode; return (exit_code, stdout)."""
    env = os.environ.copy()
    env["HAPAX_IMAG_WATCHDOG_FILE"] = str(watch_file)
    env["HAPAX_IMAG_WATCHDOG_STALE_S"] = str(stale_s)
    env["HAPAX_IMAG_WATCHDOG_UNIT"] = unit
    env["HAPAX_IMAG_WATCHDOG_DRY_RUN"] = "1" if dry_run else "0"
    env["HAPAX_IMAG_WATCHDOG_FRESH_PATHS"] = (
        " ".join(str(path) for path in fresh_paths) if fresh_paths is not None else ""
    )
    env["HAPAX_IMAG_WATCHDOG_SOURCE_DIR"] = str(
        source_dir if source_dir is not None else watch_file.parent / "no-sources"
    )
    env["HAPAX_IMAG_WATCHDOG_STATE_DIR"] = str(
        state_dir if state_dir is not None else watch_file.parent / "watchdog-state"
    )
    if state_file is not None:
        env["HAPAX_IMAG_WATCHDOG_STATE_FILE"] = str(state_file)
    if cooldown_s is not None:
        env["HAPAX_IMAG_WATCHDOG_COOLDOWN_S"] = str(cooldown_s)
    if extra_env:
        env.update(extra_env)
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
    assert "would restart" in out
    assert "DRY RUN — skipping restart" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_stale_file_with_recent_restart_is_cooldown_suppressed(tmp_path: Path) -> None:
    """A stale file may alert, but it must not create a one-minute restart storm."""
    f = tmp_path / "current.json"
    state = tmp_path / "watchdog" / "last-restart"
    state.parent.mkdir()
    f.write_text("{}")
    backdated = time.time() - 700
    os.utime(f, (backdated, backdated))
    state.write_text(str(int(time.time() - 30)))

    code, out = _run_watchdog(watch_file=f, stale_s=600, state_file=state, cooldown_s=900)

    assert code == 0
    assert "primary stale" in out
    assert "restart suppressed by cooldown" in out
    assert "DRY RUN — skipping restart" not in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_missing_file_triggers_restart(tmp_path: Path) -> None:
    """When current.json is absent the loop is presumed dead — restart."""
    f = tmp_path / "does-not-exist.json"
    code, out = _run_watchdog(watch_file=f, stale_s=600)
    assert code == 0
    assert "primary missing" in out
    assert "would restart" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_missing_file_with_recent_restart_is_cooldown_suppressed(tmp_path: Path) -> None:
    """Missing file handling also obeys cooldown; absence cannot storm restarts."""
    f = tmp_path / "does-not-exist.json"
    state = tmp_path / "watchdog" / "last-restart"
    state.parent.mkdir()
    state.write_text(str(int(time.time() - 30)))

    code, out = _run_watchdog(watch_file=f, stale_s=600, state_file=state, cooldown_s=900)

    assert code == 0
    assert "primary missing" in out
    assert "restart suppressed by cooldown" in out
    assert "DRY RUN — skipping restart" not in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_zero_threshold_always_triggers(tmp_path: Path) -> None:
    """STALE_S=0 forces the restart branch regardless of mtime — useful
    for emergency restart loops or operator-driven test pulses."""
    f = tmp_path / "current.json"
    f.write_text("{}")
    code, out = _run_watchdog(watch_file=f, stale_s=0)
    assert code == 0
    assert "would restart" in out


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


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_stale_current_with_fresh_uniforms_does_not_restart(tmp_path: Path) -> None:
    """Fresh uniforms prove the visual chain is alive despite stale current.json."""
    current = tmp_path / "current.json"
    current.write_text("{}")
    old = time.time() - 700
    os.utime(current, (old, old))

    uniforms = tmp_path / "uniforms.json"
    uniforms.write_text("{}")

    code, out = _run_watchdog(watch_file=current, stale_s=600, fresh_paths=[uniforms])
    assert code == 0
    assert "primary stale" in out
    assert "composite liveness fresh" in out
    assert "not restarting" in out
    assert "DRY RUN" not in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_missing_current_with_fresh_source_frame_does_not_restart(tmp_path: Path) -> None:
    """A fresh source-protocol frame suppresses current.json-only restart churn."""
    source_dir = tmp_path / "sources" / "programme-banner"
    source_dir.mkdir(parents=True)
    (source_dir / "frame.rgba").write_bytes(b"\0" * 16)

    code, out = _run_watchdog(
        watch_file=tmp_path / "missing-current.json",
        stale_s=600,
        source_dir=tmp_path / "sources",
    )
    assert code == 0
    assert "primary missing" in out
    assert "frame.rgba fresh_count=1" in out
    assert "not restarting" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_stale_current_and_stale_composite_triggers_restart(tmp_path: Path) -> None:
    """When every liveness surface is stale, the watchdog still restarts."""
    current = tmp_path / "current.json"
    current.write_text("{}")
    uniforms = tmp_path / "uniforms.json"
    uniforms.write_text("{}")
    old = time.time() - 700
    os.utime(current, (old, old))
    os.utime(uniforms, (old, old))

    code, out = _run_watchdog(watch_file=current, stale_s=600, fresh_paths=[uniforms])
    assert code == 0
    assert "composite liveness stale" in out
    assert "DRY RUN — would restart" in out
    assert "DRY RUN — skipping restart" in out


@pytest.mark.skipif(not SCRIPT.exists(), reason="watchdog script not present")
def test_restart_cooldown_suppresses_repeat_restarts(tmp_path: Path) -> None:
    """The state file prevents a stale condition from restarting every minute."""
    current = tmp_path / "current.json"
    current.write_text("{}")
    old = time.time() - 700
    os.utime(current, (old, old))

    fake_systemctl = tmp_path / "systemctl"
    calls = tmp_path / "systemctl.calls"
    fake_systemctl.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {calls}\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    env = {
        "HAPAX_IMAG_WATCHDOG_SYSTEMCTL": str(fake_systemctl),
        "HAPAX_IMAG_WATCHDOG_RESTART_COOLDOWN_S": "1800",
    }
    code1, out1 = _run_watchdog(
        watch_file=current,
        stale_s=600,
        state_dir=tmp_path / "state",
        dry_run=False,
        extra_env=env,
    )
    code2, out2 = _run_watchdog(
        watch_file=current,
        stale_s=600,
        state_dir=tmp_path / "state",
        dry_run=False,
        extra_env=env,
    )

    assert code1 == 0
    assert code2 == 0
    assert "restarting hapax-imagination-loop.service" in out1
    assert "restart suppressed by cooldown" in out2
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "--user show hapax-imagination-loop.service -p ActiveState --value",
        "--user show hapax-imagination-loop.service -p SubState --value",
        "--user restart --no-block hapax-imagination-loop.service",
    ]
