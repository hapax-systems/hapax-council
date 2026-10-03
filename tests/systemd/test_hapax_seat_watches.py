"""Source-only user units; installing or enabling belongs to S7."""

from pathlib import Path

UNITS = Path(__file__).resolve().parents[2] / "systemd/units"


def test_watch_template_is_user_timer_and_no_runtime_install() -> None:
    service = (UNITS / "hapax-seat-watch@.service").read_text()
    timer = (UNITS / "hapax-seat-watch@.timer").read_text()
    assert "scripts/hapax-seat-watch %i" in service
    assert "NoNewPrivileges=true" in service
    assert "OnUnitInactiveSec=" in timer
    assert "Unit=hapax-seat-watch@%i.service" in timer
    assert "WantedBy=timers.target" in timer
