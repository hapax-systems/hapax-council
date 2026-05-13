"""Test the syntax and configuration of the obsidian publish systemd units."""

import configparser
from pathlib import Path


def test_hapax_obsidian_publish_service_unit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    unit_path = repo_root / "systemd" / "units" / "hapax-obsidian-publish.service"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Preserve case
    config.read(unit_path)

    assert "Unit" in config
    assert "Service" in config

    service = config["Service"]
    assert service["Type"] == "oneshot"

    # Ensure it's non-interactive
    exec_start = service["ExecStart"]
    assert "ob publish" in exec_start
    assert "--yes" in exec_start, "The --yes flag is mandatory for headless operation."

    assert service["WorkingDirectory"] == "%h/Documents/Personal"


def test_hapax_obsidian_publish_timer_unit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    unit_path = repo_root / "systemd" / "units" / "hapax-obsidian-publish.timer"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str  # Preserve case
    config.read(unit_path)

    assert "Unit" in config
    assert "Timer" in config

    timer = config["Timer"]
    assert "OnCalendar" in timer
