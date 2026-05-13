"""Static pins for the off-L-12 private monitor bridge."""

from __future__ import annotations

from pathlib import Path

CONF_REPO_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "pipewire"
    / "hapax-private-monitor-bridge.conf"
)
MPC_TARGET = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"


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


def test_private_sink_monitor_is_captured_and_played_to_mpc_only() -> None:
    active = _active(_conf())
    capture = _node_block(active, "hapax-private-monitor-capture")
    playback = _node_block(active, "hapax-private-playback")

    assert "stream.capture.sink = true" in capture
    assert 'target.object = "hapax-private"' in capture
    assert f'target.object = "{MPC_TARGET}"' in playback
    assert "Torso_Electronics_S-4" not in playback
    assert "Blue_Microphones_Yeti" not in playback


def test_notification_private_sink_monitor_is_captured_and_played_to_mpc_only() -> None:
    active = _active(_conf())
    capture = _node_block(active, "hapax-notification-private-monitor-capture")
    playback = _node_block(active, "hapax-notification-private-playback")

    assert "stream.capture.sink = true" in capture
    assert 'target.object = "hapax-notification-private"' in capture
    assert f'target.object = "{MPC_TARGET}"' in playback
    assert "Torso_Electronics_S-4" not in playback
    assert "Blue_Microphones_Yeti" not in playback


def test_playback_streams_are_fail_closed_when_mpc_is_absent() -> None:
    active = _active(_conf())
    for node_name in ("hapax-private-playback", "hapax-notification-private-playback"):
        playback = _node_block(active, node_name)
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
