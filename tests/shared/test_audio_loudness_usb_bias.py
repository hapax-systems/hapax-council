"""Regression pins for USB-IN line-driver bias constants and confs.

The constants encode the analog channel-strip TRIM substitute that L-12 USB IN
lacks (the analog LINE input has it, USB IN does not). Calibrated 2026-05-02
from a measured 27 dB loss between music-duck output (-18 dBFS at L-12 USB IN)
and broadcast capture (-45 dBFS).

Spec: docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md §10
"""

from __future__ import annotations

import re
from pathlib import Path

from shared import audio_loudness

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPEWIRE_CONFIG_DIR = REPO_ROOT / "config" / "pipewire"
LINE_DRIVER_CONF = PIPEWIRE_CONFIG_DIR / "hapax-music-usb-line-driver.conf"
MUSIC_DUCK_CONF = PIPEWIRE_CONFIG_DIR / "hapax-music-duck.conf"


def test_wet_path_usb_bias_music_db_is_27() -> None:
    """+27 dB matches the measured USB-IN-to-broadcast-capture loss."""
    assert audio_loudness.WET_PATH_USB_BIAS_MUSIC_DB == 27.0


def test_wet_path_usb_bias_tts_db_is_27_reserved() -> None:
    """TTS bias constant exists as a reserved schema slot.

    Same provisional value as music; remeasure when TTS path is the active
    audit subject and a per-source `hapax-tts-usb-line-driver.conf` ships.
    """
    assert audio_loudness.WET_PATH_USB_BIAS_TTS_DB == 27.0


def test_master_input_makeup_db_unchanged() -> None:
    """MASTER_INPUT_MAKEUP_DB stays at +1.0 dB; it covers analog losses ONLY.

    The §10 amendment decouples the analog wet-path makeup from the USB-vs-
    LINE trim asymmetry; do not lump them into a single constant.
    """
    assert audio_loudness.MASTER_INPUT_MAKEUP_DB == 1.0


def test_pre_norm_target_lufs_i_unchanged() -> None:
    """Per-source pre-norm target stays at -18 LUFS-I (Phase 3 compat)."""
    assert audio_loudness.PRE_NORM_TARGET_LUFS_I == -18.0


def test_egress_target_lufs_i_unchanged() -> None:
    """Egress target stays at -14 LUFS-I (YouTube alignment)."""
    assert audio_loudness.EGRESS_TARGET_LUFS_I == -14.0


def test_line_driver_conf_file_exists() -> None:
    """hapax-music-usb-line-driver.conf must ship in the repo."""
    assert LINE_DRIVER_CONF.is_file(), (
        f"missing line-driver conf at {LINE_DRIVER_CONF.relative_to(REPO_ROOT)}"
    )


def test_line_driver_conf_input_gain_matches_constant() -> None:
    """Input gain (dB) in the conf must equal WET_PATH_USB_BIAS_MUSIC_DB."""
    body = LINE_DRIVER_CONF.read_text(encoding="utf-8")
    match = re.search(r'"Input gain \(dB\)"\s*=\s*([-+]?\d+(?:\.\d+)?)', body)
    assert match is not None, "could not find Input gain (dB) line in line-driver conf"
    conf_gain = float(match.group(1))
    assert conf_gain == audio_loudness.WET_PATH_USB_BIAS_MUSIC_DB, (
        f"line-driver conf Input gain (dB) = {conf_gain} drifted from "
        f"WET_PATH_USB_BIAS_MUSIC_DB = {audio_loudness.WET_PATH_USB_BIAS_MUSIC_DB}"
    )


def test_music_duck_targets_line_driver_not_l12_directly() -> None:
    """hapax-music-duck.conf must route through hapax-music-usb-line-driver.

    Pre-§10 the duck targeted the L-12 USB sink directly; that bypassed the
    analog-trim substitute. After §10 the duck plays into the line-driver and
    the line-driver plays into the L-12 USB sink.
    """
    body = MUSIC_DUCK_CONF.read_text(encoding="utf-8")

    # Find the music-duck PLAYBACK target (capture.props also references the
    # music-duck node name; we want the playback.props block specifically).
    playback_match = re.search(
        r"playback\.props\s*=\s*\{[^}]*?target\.object\s*=\s*\"([^\"]+)\"",
        body,
        re.DOTALL,
    )
    assert playback_match is not None, (
        "could not find playback.props target.object in hapax-music-duck.conf"
    )
    target = playback_match.group(1)
    assert target == "hapax-music-usb-line-driver", (
        f"hapax-music-duck playback target.object is {target!r}; expected "
        '"hapax-music-usb-line-driver" (spec §10 routes through the line-driver, '
        "not directly to the L-12 USB sink)"
    )
