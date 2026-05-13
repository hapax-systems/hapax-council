"""Test the syntax and configuration of the omg_web_builder systemd units."""

import configparser
from pathlib import Path


def test_hapax_omg_web_builder_service_unit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    unit_path = repo_root / "systemd" / "units" / "hapax-omg-web-builder.service"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Preserve case
    config.read(unit_path)

    assert "Unit" in config
    assert "Service" in config

    service = config["Service"]
    assert service["Type"] == "oneshot"
    assert service["WorkingDirectory"] == "%h/projects/hapax-council"

    # Ensure it hits the correct python module with the publish flag
    exec_start = service["ExecStart"]
    assert "agents.omg_web_builder.publisher" in exec_start
    assert "--publish" in exec_start


def test_hapax_omg_web_builder_timer_unit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    unit_path = repo_root / "systemd" / "units" / "hapax-omg-web-builder.timer"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Preserve case
    config.read(unit_path)

    assert "Unit" in config
    assert "Timer" in config

    timer = config["Timer"]
    assert "OnCalendar" in timer
