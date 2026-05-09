"""audio-stage-check-continuous-emitter — timer unit static checks.

cc-task `audio-stage-check-continuous-emitter`. Ensures the new
`.timer` unit pairs cleanly with the existing `.service` and follows
the systemd-timer schema. Pure static parse — no live systemctl.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
TIMER = UNITS_DIR / "hapax-audio-stage-check.timer"
SERVICE = UNITS_DIR / "hapax-audio-stage-check.service"


def _read_unit(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    # systemd allows duplicate keys (e.g., ExecStart=) but ConfigParser
    # raises by default; force strict=False handles it.
    cp.read(path)
    return cp


def test_timer_file_exists() -> None:
    assert TIMER.exists(), f"Timer file missing at {TIMER}"


def test_target_service_exists() -> None:
    """Pin: timer's `Unit=` target must point at an existing service."""
    assert SERVICE.exists(), f"Target service {SERVICE} missing — timer would never fire."


def test_timer_has_required_sections() -> None:
    cp = _read_unit(TIMER)
    assert "Unit" in cp, "[Unit] section required"
    assert "Timer" in cp, "[Timer] section required"
    assert "Install" in cp, "[Install] section required"


def test_timer_targets_correct_service() -> None:
    cp = _read_unit(TIMER)
    assert cp["Timer"].get("Unit") == "hapax-audio-stage-check.service", (
        "Timer must trigger hapax-audio-stage-check.service"
    )


def test_timer_has_periodic_cadence() -> None:
    """Pin: OnUnitActiveSec or OnUnitInactiveSec required for periodic fire."""
    cp = _read_unit(TIMER)
    has_periodic = (
        cp["Timer"].get("OnUnitActiveSec") is not None
        or cp["Timer"].get("OnUnitInactiveSec") is not None
        or cp["Timer"].get("OnCalendar") is not None
    )
    assert has_periodic, (
        "Timer requires OnUnitActiveSec/OnUnitInactiveSec/OnCalendar for periodic firing"
    )


def test_timer_has_boot_delay() -> None:
    """Pin: OnBootSec ensures pipewire settles before first fire."""
    cp = _read_unit(TIMER)
    boot_delay = cp["Timer"].get("OnBootSec")
    assert boot_delay is not None, "OnBootSec required so the first fire delays past pipewire start"


def test_timer_persistent_across_reboots() -> None:
    """Pin: Persistent=true so missed runs catch up after long downtime."""
    cp = _read_unit(TIMER)
    persistent = cp["Timer"].get("Persistent", "").lower()
    assert persistent in ("true", "yes", "on", "1"), f"Persistent=true expected; got {persistent!r}"


def test_timer_install_target() -> None:
    """Pin: WantedBy=timers.target so timer is enabled in default chain."""
    cp = _read_unit(TIMER)
    wanted = cp["Install"].get("WantedBy", "")
    assert "timers.target" in wanted, f"WantedBy=timers.target expected; got {wanted!r}"


def test_service_unchanged_pairs_with_timer() -> None:
    """Regression pin: the existing .service file (boot-time oneshot)
    is the timer's target. Verify the service still has Type=oneshot
    and ExecStart points at the hapax-audio-stage-check script."""
    cp = _read_unit(SERVICE)
    assert cp["Service"].get("Type") == "oneshot", (
        "Service must remain oneshot — the timer drives invocation cadence"
    )
    exec_start = cp["Service"].get("ExecStart", "")
    assert "hapax-audio-stage-check" in exec_start, (
        f"Service ExecStart must reference hapax-audio-stage-check; got {exec_start!r}"
    )
    assert "--execute" in exec_start, "Service ExecStart must pass --execute (vs dry-run default)"


def test_randomized_delay_present() -> None:
    """Pin: RandomizedDelaySec smooths fire across multiple timers if
    ever co-deployed; absence is fine but the existing setting is a
    documented choice."""
    cp = _read_unit(TIMER)
    # Allow absence (None) OR a numeric value with unit suffix.
    delay = cp["Timer"].get("RandomizedDelaySec")
    if delay is not None:
        # Should be a small value like "5s" — not unbounded.
        assert delay.endswith(("s", "ms")) or delay.isdigit(), (
            f"RandomizedDelaySec format unexpected: {delay!r}"
        )
