"""Static activation checks for mail-monitor fallback units."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"
SERVICE = UNITS_DIR / "hapax-mail-monitor-fallback.service"
TIMER = UNITS_DIR / "hapax-mail-monitor-fallback.timer"


def test_mail_monitor_fallback_units_are_install_visible() -> None:
    assert SERVICE.exists(), "fallback service must live under systemd/units"
    assert TIMER.exists(), "fallback timer must live under systemd/units"
    assert not (SYSTEMD_ROOT / SERVICE.name).exists(), "service shadows systemd/units"
    assert not (SYSTEMD_ROOT / TIMER.name).exists(), "timer shadows systemd/units"


def test_mail_monitor_fallback_service_runs_one_shot_module() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    # Runs from the source-activation deploy tree (main-tracking), not the
    # operator's canonical interactive worktree — see
    # docs/research/2026-06-07-canonical-rooted-unit-audit.md.
    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in service
    assert "EnvironmentFile=-/run/user/1000/hapax-secrets.env" in service
    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "-m agents.mail_monitor.fallback"
    ) in service
    assert "Restart=always" not in service


def test_mail_monitor_fallback_timer_runs_every_15_minutes() -> None:
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=*:0/15" in timer
    assert "Persistent=true" in timer
    assert "Unit=hapax-mail-monitor-fallback.service" in timer


def test_mail_monitor_fallback_timer_is_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "enable hapax-mail-monitor-fallback.timer" in preset_lines
