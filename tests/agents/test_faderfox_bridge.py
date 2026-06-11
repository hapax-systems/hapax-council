"""Tests for the MX12 manual-trim bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents import faderfox_bridge


def test_live_mx12_fader_profile_uses_cc95_by_channel() -> None:
    faders, buttons = faderfox_bridge.load_map(faderfox_bridge.DEFAULT_CONFIG)

    assert len(faders) in {6, 8}
    assert len(buttons) == 3

    for channel in range(1, 7):
        assert (channel - 1, 95) in faders

    assert faders[(0, 95)]["label"] == "master"
    assert faders[(1, 95)]["label"] == "music"
    assert faders[(2, 95)]["label"] == "hapax-voice"
    assert faders[(3, 95)]["label"] == "operator-mic"
    assert faders[(4, 95)]["label"] == "youtube"
    assert faders[(5, 95)]["label"] == "voice-to-s4"
    if len(faders) == 8:
        assert faders[(6, 95)]["label"] == "monitor-stream"
        assert faders[(7, 95)]["label"] == "monitor-private"


def test_load_map_keys_are_zero_indexed(tmp_path: Path) -> None:
    config = tmp_path / "mx12.yaml"
    config.write_text(
        """
faders:
  - { label: music, channel: 2, cc: 95, target: "hapax-music-loudnorm" }
buttons:
  - { label: mute-music, channel: 2, cc: 49, target: "hapax-music-loudnorm" }
""",
        encoding="utf-8",
    )

    faders, buttons = faderfox_bridge.load_map(config)

    assert faders == {
        (1, 95): {"label": "music", "channel": 2, "cc": 95, "target": "hapax-music-loudnorm"}
    }
    assert buttons == {
        (1, 49): {"label": "mute-music", "channel": 2, "cc": 49, "target": "hapax-music-loudnorm"}
    }


def test_set_volume_clamps_negative_values() -> None:
    with patch("agents.faderfox_bridge._wpctl") as wpctl_mock:
        faderfox_bridge.set_volume("hapax-music-loudnorm", -0.5)

    wpctl_mock.assert_called_once_with(["set-volume", "0.000"], "hapax-music-loudnorm")


def test_set_mute_uses_wpctl_boolean_value() -> None:
    with patch("agents.faderfox_bridge._wpctl") as wpctl_mock:
        faderfox_bridge.set_mute("hapax-music-loudnorm", True)

    wpctl_mock.assert_called_once_with(["set-mute", "1"], "hapax-music-loudnorm")
