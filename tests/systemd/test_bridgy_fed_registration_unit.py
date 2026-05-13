"""Test the syntax and configuration of the Bridgy Fed registration systemd units."""

import configparser
from pathlib import Path


def test_hapax_bridgy_fed_registration_service_unit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    unit_path = repo_root / "systemd" / "units" / "hapax-bridgy-fed-registration.service"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Preserve case
    config.read(unit_path)

    assert "Unit" in config
    assert "Service" in config

    service = config["Service"]
    assert service["Type"] == "oneshot"

    # Ensure it's non-interactive and hits the correct endpoint
    exec_start = service["ExecStart"]
    assert "curl" in exec_start
    assert "https://fed.brid.gy/web/hapax.omg.lol" in exec_start


def test_hapax_bridgy_fed_registration_timer_unit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    unit_path = repo_root / "systemd" / "units" / "hapax-bridgy-fed-registration.timer"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Preserve case
    config.read(unit_path)

    assert "Unit" in config
    assert "Timer" in config

    timer = config["Timer"]
    assert "OnCalendar" in timer
