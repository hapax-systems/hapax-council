"""Static contract tests for the S-4 boot-arm systemd unit."""

from __future__ import annotations

import configparser
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-s4-arm"
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE = UNITS_DIR / "hapax-s4-arm.service"
TIMER = UNITS_DIR / "hapax-s4-arm.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _read_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # preserve systemd key casing
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_s4_arm_wrapper_delegates_to_shared_arm_main() -> None:
    body = SCRIPT.read_text(encoding="utf-8")

    assert os.access(SCRIPT, os.X_OK)
    assert body.startswith("#!/usr/bin/env python3")
    assert "from shared.s4_arm import main" in body
    assert "raise SystemExit(main())" in body


def test_s4_arm_service_invokes_pre_segment_witness_flow() -> None:
    body = SERVICE.read_text(encoding="utf-8")
    service = _read_unit(SERVICE)
    exec_start_pre = service.get("Service", "ExecStartPre")
    exec_start = service.get("Service", "ExecStart")

    assert service.get("Unit", "OnFailure") == "notify-failure@%n.service"
    assert (
        service.get("Unit", "Requires")
        == "pipewire.service pipewire-pulse.service wireplumber.service hapax-audio-reconciler.service"
    )
    assert not service.has_option("Unit", "Wants")
    assert service.get("Service", "Type") == "oneshot"
    assert (
        service.get("Service", "WorkingDirectory") == "%h/.cache/hapax/source-activation/worktree"
    )
    assert (
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-compositor-runtime-source-check"
        in exec_start_pre
    )
    assert "--require-file scripts/hapax-s4-arm" in exec_start_pre
    assert "--require-file shared/s4_arm.py" in exec_start_pre
    assert exec_start.startswith(
        "%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-s4-arm"
    )
    assert "uv run" not in exec_start
    assert "--pre-segment-check" in exec_start
    assert "--task-id s4-boot-reconcile-c3-20260618" in exec_start
    assert "--authority-case CASE-VOICE-FOUNDATION-20260610" in exec_start
    assert (
        "--parent-spec "
        "/home/hapax/Documents/Personal/30-areas/hapax/go-live-master-plan-2026-06-18.md"
        in exec_start
    )
    assert "--receipt-path /dev/shm/hapax-audio/s4-boot-arm-receipt.json" in exec_start
    assert service.get("Service", "TimeoutStartSec") == "180s"
    assert not service.has_section("Install")
    assert "WantedBy=default.target" not in body


def test_s4_arm_service_uses_source_activation_environment() -> None:
    body = SERVICE.read_text(encoding="utf-8")

    assert (
        "Environment=PATH=%h/.cache/hapax/source-activation/worktree/.venv/bin:"
        "%h/.local/bin:%h/.cargo/bin:/usr/local/bin:/usr/bin:/bin" in body
    )
    assert "Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in body
    assert "Environment=XDG_RUNTIME_DIR=%t" in body
    assert "Environment=XDG_RUNTIME_DIR=/run/user/1000" not in body
    assert "ExecStartPre=/usr/bin/install -d -m 0755 /dev/shm/hapax-audio" in body


def test_s4_arm_timer_is_user_manager_startup_scoped_not_recurring_marker_loop() -> None:
    body = TIMER.read_text(encoding="utf-8")
    active_lines = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith(("#", ";"))
    )
    timer = _read_unit(TIMER)

    assert "# Hapax-Timer-Enable-Only: true" in body
    assert timer.get("Timer", "Unit") == "hapax-s4-arm.service"
    assert timer.get("Timer", "OnStartupSec") == "2min"
    assert timer.get("Timer", "Persistent") == "false"
    assert timer.get("Install", "WantedBy") == "timers.target"
    assert not timer.has_option("Timer", "OnBootSec")
    assert not timer.has_option("Timer", "OnUnitActiveSec")
    assert not timer.has_option("Timer", "OnCalendar")
    assert "OnBootSec" not in active_lines
    assert "OnUnitActiveSec" not in active_lines
    assert "OnCalendar" not in active_lines


def test_s4_arm_timer_is_preset_enabled() -> None:
    enabled_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("enable ")
    }

    assert "enable hapax-s4-arm.timer" in enabled_lines
