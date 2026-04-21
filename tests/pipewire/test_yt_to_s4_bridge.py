"""YT loudnorm → S-4 content bridge (Phase A5).

Static schema pin for the pre-staged bridge loopback. The bridge is
a no-op consumer until the S-4 is physically plugged in; on plug-in
it immediately carries YT / SoundCloud audio into the S-4 USB input
for Phase B routing (Track 2 MUSIC-BED scene).
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONF_REPO_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-yt-to-s4-bridge.conf"
)


@pytest.fixture()
def conf_text() -> str:
    if not CONF_REPO_PATH.exists():
        pytest.skip(f"conf missing from repo: {CONF_REPO_PATH}")
    return CONF_REPO_PATH.read_text(encoding="utf-8")


def test_conf_exists(conf_text: str) -> None:
    assert len(conf_text) > 0


def test_uses_loopback_module(conf_text: str) -> None:
    assert "libpipewire-module-loopback" in conf_text


def test_capture_side_targets_yt_loudnorm(conf_text: str) -> None:
    assert 'target.object  = "hapax-yt-loudnorm-playback"' in conf_text, (
        "Bridge must capture from hapax-yt-loudnorm-playback (the "
        "−16 LUFS normalized YT bed stream)."
    )


def test_playback_side_targets_s4_content(conf_text: str) -> None:
    assert 'target.object  = "hapax-s4-content"' in conf_text, (
        "Bridge must route into hapax-s4-content (the S-4 USB input sink)."
    )


def test_declares_stereo(conf_text: str) -> None:
    assert "audio.channels = 2" in conf_text
    assert "[ FL FR ]" in conf_text


def test_capture_is_passive(conf_text: str) -> None:
    assert "node.passive   = true" in conf_text or "node.passive = true" in conf_text, (
        "Capture side must be passive so the bridge doesn't claim the "
        "yt-loudnorm output when no S-4 consumer is downstream."
    )


def test_documents_s4_absence_behavior(conf_text: str) -> None:
    assert "no-op" in conf_text.lower() or "absent" in conf_text.lower(), (
        "Conf file must document that the bridge is inert until S-4 is physically plugged in."
    )
