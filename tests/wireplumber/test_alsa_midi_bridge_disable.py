"""Pins the workstation WirePlumber ALSA-MIDI bridge posture."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONF = REPO_ROOT / "config" / "wireplumber" / "93-hapax-disable-alsa-midi-bridge.conf"


def test_wireplumber_alsa_midi_bridge_is_disabled_without_disabling_audio_policy() -> None:
    text = CONF.read_text(encoding="utf-8")

    assert "monitor.alsa-midi = disabled" in text
    assert "monitor.alsa = disabled" not in text
    assert "policy.linking.role-based" not in text
