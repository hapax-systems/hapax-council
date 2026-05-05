"""Regression pins for the ReSpeaker XVF3800 array mic profile pin."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "pipewire"
    / "hapax-respeaker-xvf3800-array-mic.conf"
)


@pytest.fixture()
def raw_config() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip("hapax-respeaker-xvf3800-array-mic.conf missing from repo checkout")
    return CONFIG_PATH.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_uses_monitor_alsa_rules(raw_config: str) -> None:
    assert "monitor.alsa.rules" in raw_config


def test_matches_seeed_and_xmos_firmware_names(raw_config: str) -> None:
    assert "Seeed_Studio_ReSpeaker_XVF3800" in raw_config
    assert "XMOS_XVF3800_Voice_Processor" in raw_config
    assert "ReSpeaker*XVF3800" in raw_config


def test_pins_pro_audio_without_default_capture_promotion(raw_config: str) -> None:
    assert 'device.profile = "pro-audio"' in raw_config
    assert "api.alsa.use-acp = false" in raw_config
    assert 'node.nick = "hapax-array-mic"' in raw_config
    assert "set-default-source" not in raw_config


def test_priority_stays_below_broadcast_interfaces(raw_config: str) -> None:
    assert "priority.session = 850" in raw_config
    assert "priority.driver = 850" in raw_config


def test_braces_balanced(raw_config: str) -> None:
    stripped = _strip_comments(raw_config)
    cleaned = re.sub(r'"[^"]*"', '""', stripped)
    assert cleaned.count("{") == cleaned.count("}")
    assert cleaned.count("[") == cleaned.count("]")
