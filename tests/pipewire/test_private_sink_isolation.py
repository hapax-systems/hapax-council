"""Private sink isolation for the L-12 inverse invariant."""

from __future__ import annotations

from pathlib import Path

CONF_REPO_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-stream-split.conf"
)


def _active(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_private_sink_exists_as_fail_closed_null_sink() -> None:
    text = CONF_REPO_PATH.read_text(encoding="utf-8")
    active = _active(text)

    assert 'node.name          = "hapax-private"' in active
    assert "support.null-audio-sink" in active
    assert "fail-closed" in text


def test_private_sink_has_no_downstream_playback_target() -> None:
    text = CONF_REPO_PATH.read_text(encoding="utf-8")
    active = _active(text)

    assert "hapax-private-playback" not in active
    assert "target.object" not in active
    assert "node.target" not in active


def test_private_sink_does_not_reference_broadcast_paths_in_active_config() -> None:
    text = CONF_REPO_PATH.read_text(encoding="utf-8")
    active = _active(text)

    forbidden = [
        "alsa_output.usb-ZOOM_Corporation_L-12",
        "hapax-livestream-tap",
        "hapax-voice-fx-capture",
        "hapax-pc-loudnorm",
    ]
    for target in forbidden:
        assert target not in active, (
            f"private sink active config references broadcast path {target}"
        )
