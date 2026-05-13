import configparser
from pathlib import Path

from agents.aesthetic_generator.generator import (
    PALETTE,
    generate_github_banner,
    generate_mastodon_header,
)


def test_github_banner_colors():
    svg = generate_github_banner()
    assert PALETTE["bg"] in svg
    assert PALETTE["fg"] in svg


def test_mastodon_header_colors():
    svg = generate_mastodon_header(stimmung_mood="cautious")
    assert PALETTE["bg"] in svg
    assert PALETTE["accent"] in svg


def test_hapax_aesthetic_sync_service_unit() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    unit_path = repo_root / "systemd" / "units" / "hapax-aesthetic-sync.service"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read(unit_path)

    assert "Unit" in config
    assert "Service" in config
    assert config["Service"]["Type"] == "oneshot"
    assert "agents.aesthetic_generator.generator" in config["Service"]["ExecStart"]


def test_hapax_aesthetic_sync_timer_unit() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    unit_path = repo_root / "systemd" / "units" / "hapax-aesthetic-sync.timer"
    assert unit_path.exists()

    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read(unit_path)

    assert "Unit" in config
    assert "Timer" in config
    assert "OnCalendar" in config["Timer"]
