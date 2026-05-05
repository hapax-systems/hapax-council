"""Regression pin for dual-fx-routing Phase 1 — S-4 USB device profile pin.

Pins the conf shape so a future edit can't silently break the
pro-audio profile selection (which is what makes the S-4's full
10-channel inventory addressable for dual-FX routing).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-s4-usb-sink.conf"


@pytest.fixture()
def raw_config() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip("hapax-s4-usb-sink.conf missing from repo checkout")
    return CONFIG_PATH.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_uses_monitor_alsa_rules(raw_config: str) -> None:
    """The conf must be a wireplumber-style monitor.alsa.rules block."""
    assert "monitor.alsa.rules" in raw_config


def test_matches_torso_s4_device(raw_config: str) -> None:
    """The match pattern must target the S-4 device by name."""
    assert "Torso_Electronics_S-4" in raw_config
    # Wildcarded so future serial-number suffix or rev letter doesn't break.
    assert "alsa_card.usb-Torso_Electronics_S-4*" in raw_config


def test_pins_pro_audio_profile(raw_config: str) -> None:
    """Pro-audio profile is the load-bearing decision — without it
    the dual-FX router can't address tracks 1-4 independently."""
    assert 'device.profile = "pro-audio"' in raw_config


def test_disables_alsa_card_profile_layer(raw_config: str) -> None:
    """``api.alsa.use-acp = false`` is required so the ALSA UCM layer
    doesn't compete with the explicit profile pin."""
    assert "api.alsa.use-acp = false" in raw_config


def test_braces_balanced(raw_config: str) -> None:
    stripped = _strip_comments(raw_config)
    cleaned = re.sub(r'"[^"]*"', '""', stripped)
    assert cleaned.count("{") == cleaned.count("}")
    assert cleaned.count("[") == cleaned.count("]")
