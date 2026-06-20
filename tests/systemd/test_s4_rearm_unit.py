"""Static contract tests for the S-4 silent recurring re-arm units.

Pins the durability fix (arm-on-boot/restart): a recurring + restart-coupled
re-arm that re-asserts the S-4 gain ladder SILENTLY so broadcast voice survives
a daimonion/system restart. The load-bearing safety property — verified here at
the unit level — is that the recurring path runs with ``--witness-mode none``
and WITHOUT ``--pre-segment-check``, so it never plays a marker tone to the
broadcast bus (unlike the boot arm, which is broadcast-off at boot and may probe).
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE = UNITS_DIR / "hapax-s4-rearm.service"
TIMER = UNITS_DIR / "hapax-s4-rearm.timer"
DROPIN = UNITS_DIR / "hapax-daimonion.service.d" / "s4-rearm.conf"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _read_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # preserve systemd key casing
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_rearm_service_is_silent_no_tone_to_air() -> None:
    """THE SAFETY THESIS at the unit level: the recurring re-arm never tones."""
    exec_start = _read_unit(SERVICE).get("Service", "ExecStart")
    assert "--witness-mode none" in exec_start
    assert "--no-monitor-toggle" in exec_start
    assert "--pre-segment-check" not in exec_start
    assert "hapax-s4-wet-return-probe" not in exec_start


def test_rearm_service_structure() -> None:
    body = SERVICE.read_text(encoding="utf-8")
    svc = _read_unit(SERVICE)

    assert svc.get("Service", "Type") == "oneshot"
    assert svc.get("Unit", "OnFailure") == "notify-failure@%n.service"
    after = svc.get("Unit", "After")
    assert "systemd-udev-settle.service" in after  # cold-boot enumeration race
    assert "hapax-daimonion.service" in after  # restart-coupled ordering

    exec_start = svc.get("Service", "ExecStart")
    assert exec_start.startswith(
        "%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-s4-arm"
    )
    assert "uv run" not in exec_start
    # separate receipt so the recurring re-arm never clobbers the boot/manual one
    assert "--receipt-path /dev/shm/hapax-audio/s4-rearm-receipt.json" in exec_start
    assert "s4-boot-arm-receipt.json" not in exec_start
    assert "--authority-case CASE-VOICE-FOUNDATION-20260610" in exec_start
    assert (
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-compositor-runtime-source-check"
        in svc.get("Service", "ExecStartPre")
    )
    assert "Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in body
    assert "Environment=XDG_RUNTIME_DIR=%t" in body


def test_rearm_timer_is_recurring_and_restart_resilient() -> None:
    timer = _read_unit(TIMER)
    assert timer.get("Timer", "OnBootSec") == "60s"
    assert timer.get("Timer", "OnUnitActiveSec") == "120s"
    assert timer.get("Timer", "Persistent") == "true"
    assert timer.get("Install", "WantedBy") == "timers.target"


def test_daimonion_dropin_pulls_rearm_on_restart() -> None:
    dropin = _read_unit(DROPIN)
    assert dropin.get("Unit", "Wants") == "hapax-s4-rearm.service"
    # ordering lives on the rearm unit (After=hapax-daimonion); a reverse After=
    # here would invert it, so the drop-in must not declare one.
    assert not dropin.has_option("Unit", "After")


def test_rearm_timer_is_preset_enabled() -> None:
    enabled = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("enable ")
    }
    assert "enable hapax-s4-rearm.timer" in enabled
