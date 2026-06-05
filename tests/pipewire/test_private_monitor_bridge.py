"""Static pins for the mk5 Phones private monitor bridge."""

from __future__ import annotations

from pathlib import Path

CONF_REPO_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "pipewire"
    / "hapax-private-monitor-bridge.conf"
)
MK5_TARGET = "alsa_output.usb-MOTU_UltraLite-mk5_UL5LFEC2B0-00.pro-output-0"


def _active(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _node_block(active: str, node_name: str) -> str:
    lines = active.splitlines()
    for index, line in enumerate(lines):
        if f'node.name = "{node_name}"' not in line:
            continue
        block = [line]
        for following in lines[index + 1 :]:
            block.append(following)
            if following.strip() == "}":
                break
        return "\n".join(block)
    raise AssertionError(f"node block not found: {node_name}")


def _conf() -> str:
    return CONF_REPO_PATH.read_text(encoding="utf-8")


def test_bridge_conf_exists_and_documents_fail_closed_contract() -> None:
    text = _conf()

    assert "node.dont-fallback" in text
    assert "node.dont-reconnect" in text
    assert "absent hardware produces silence" in text


def test_private_sink_monitor_is_captured_and_played_to_mk5_phones_only() -> None:
    active = _active(_conf())
    capture = _node_block(active, "hapax-private-monitor-capture")
    playback = _node_block(active, "hapax-private-playback")

    assert "stream.capture.sink = true" in capture
    assert 'target.object = "hapax-private"' in capture
    assert f'target.object = "{MK5_TARGET}"' in playback
    assert "Akai_Professional_MPC_LIVE_III" not in playback
    assert "Torso_Electronics_S-4" not in playback
    assert "Blue_Microphones_Yeti" not in playback


def test_notification_private_sink_is_not_bridged_to_mk5() -> None:
    active = _active(_conf())

    assert "hapax-notification-private-monitor-capture" not in active
    assert "hapax-notification-private-playback" not in active
    assert 'target.object = "hapax-notification-private"' not in active


def test_playback_streams_are_fail_closed_when_mk5_is_absent() -> None:
    active = _active(_conf())
    playback = _node_block(active, "hapax-private-playback")
    assert "node.dont-fallback = true" in playback
    assert "node.autoconnect = false" in playback
    assert "node.dont-reconnect = true" in playback
    assert "node.dont-move = true" in playback
    assert "node.linger = true" in playback
    assert "state.restore = false" in playback


def test_bridge_does_not_reference_broadcast_or_default_paths() -> None:
    active = _active(_conf())
    forbidden = [
        "alsa_output.usb-ZOOM_Corporation_L-12",
        "hapax-livestream",
        "hapax-livestream-tap",
        "hapax-voice-fx-capture",
        "hapax-pc-loudnorm",
        "input.loopback.sink.role.multimedia",
    ]

    for target in forbidden:
        assert target not in active
