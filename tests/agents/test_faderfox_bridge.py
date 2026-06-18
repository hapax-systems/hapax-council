"""Tests for the MX12 manual-trim bridge."""

from __future__ import annotations

import subprocess
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


def test_get_volume_parses_wpctl_output() -> None:
    proc = subprocess.CompletedProcess(
        args=["wpctl", "get-volume", "99"], returncode=0, stdout="Volume: 0.420\n"
    )

    with patch("agents.faderfox_bridge._wpctl", return_value=proc):
        assert faderfox_bridge.get_volume("hapax-music-loudnorm") == 0.42


def test_resync_faders_seeds_pickup_target_without_volume_write() -> None:
    faders = {
        (0, 95): {
            "label": "music",
            "target": "hapax-music-loudnorm",
            "scale": 1.0,
        }
    }

    with (
        patch("agents.faderfox_bridge.get_volume", return_value=0.50),
        patch("agents.faderfox_bridge.set_volume") as set_volume_mock,
    ):
        faderfox_bridge.resync_faders(faders)

    assert faders[(0, 95)]["_pickup_target"] == 64
    assert faders[(0, 95)]["_pickup_last_value"] is None
    set_volume_mock.assert_not_called()


def test_resync_faders_honors_scaled_targets() -> None:
    faders = {
        (0, 95): {
            "label": "voice",
            "target": "hapax-voice-loudnorm",
            "scale": 2.0,
        }
    }

    with patch("agents.faderfox_bridge.get_volume", return_value=0.50):
        faderfox_bridge.resync_faders(faders)

    assert faders[(0, 95)]["_pickup_target"] == 32


def test_resynced_fader_ignores_stale_move_until_pickup_crossing() -> None:
    fader = {
        "label": "music",
        "target": "hapax-music-loudnorm",
        "scale": 1.0,
        "_pickup_target": 64,
        "_pickup_last_value": None,
    }

    with patch("agents.faderfox_bridge.set_volume") as set_volume_mock:
        assert not faderfox_bridge._handle_fader(fader, 10)
        set_volume_mock.assert_not_called()
        assert fader["_pickup_last_value"] == 10

        assert faderfox_bridge._handle_fader(fader, 80)

    set_volume_mock.assert_called_once_with("hapax-music-loudnorm", 80 / 127.0)
    assert "_pickup_target" not in fader
    assert "_pickup_last_value" not in fader


def test_resynced_fader_applies_when_near_pickup_target() -> None:
    fader = {
        "label": "music",
        "target": "hapax-music-loudnorm",
        "scale": 1.0,
        "_pickup_target": 64,
        "_pickup_last_value": None,
    }

    with patch("agents.faderfox_bridge.set_volume") as set_volume_mock:
        assert faderfox_bridge._handle_fader(fader, 63)

    set_volume_mock.assert_called_once_with("hapax-music-loudnorm", 63 / 127.0)


def test_resync_faders_fails_soft_when_target_volume_unavailable() -> None:
    faders = {
        (0, 95): {
            "label": "music",
            "target": "hapax-music-loudnorm",
            "scale": 1.0,
        }
    }

    with patch("agents.faderfox_bridge.get_volume", return_value=None):
        faderfox_bridge.resync_faders(faders)

    assert "_pickup_target" not in faders[(0, 95)]
    with patch("agents.faderfox_bridge.set_volume") as set_volume_mock:
        assert faderfox_bridge._handle_fader(faders[(0, 95)], 20)

    set_volume_mock.assert_called_once_with("hapax-music-loudnorm", 20 / 127.0)
