"""Music-loudnorm invariant pins.

Defect #2 from `/tmp/audio-research-topology-audit.md` (2026-05-03):
the deployed `~/.config/pipewire/pipewire.conf.d/hapax-music-loudnorm.conf`
was hand-edited to bypass the governed routing plane (target.object =
L-12 USB sink directly) and to raise the limiter ceiling to -3.0 dBFS
(+15 dB hotter than designed). Both edits silently break the current
MPC-first audio architecture: music leaves the reconciled link map,
operator-visible routing drifts, and downstream program level runs
near-clip.

This test pins the canonical values in the repo conf so the next time
someone hand-edits the deployed copy out of band, regenerating from
the repo (the canonical workflow) restores correct behavior.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONF_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-music-loudnorm.conf"
)


@pytest.fixture(scope="module")
def loudnorm_conf_text() -> str:
    if not CONF_PATH.exists():
        pytest.skip(f"loudnorm conf {CONF_PATH} missing from repo checkout")
    return CONF_PATH.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class TestLimiterCeiling:
    """The fast_lookahead_limiter ceiling MUST stay at -18.0 dBFS.

    Anything hotter (closer to 0) sends near-clip program material into
    the MPC input and downstream chain. The -18 dBFS calibration is
    sized for the MPC USB input path plus the broadcast master makeup
    (+14 dB per
    `MASTER_INPUT_MAKEUP_DB` in `shared/audio_loudness.py`). Hand-edits
    to the deployed conf bypassing this calibration produce broadcast
    overshoot and defeat the per-source headroom assumption.
    """

    def test_limit_db_is_minus_18(self, loudnorm_conf_text: str) -> None:
        stripped = _strip_comments(loudnorm_conf_text)
        match = re.search(r'"Limit \(dB\)"\s*=\s*(-?\d+(?:\.\d+)?)', stripped)
        assert match is not None, (
            'loudnorm filter graph missing fast_lookahead_limiter "Limit (dB)" control'
        )
        ceiling = float(match.group(1))
        assert ceiling == -18.0, (
            f"music-loudnorm limiter ceiling MUST be -18.0 dBFS (got {ceiling}); "
            "see header comment in hapax-music-loudnorm.conf for calibration "
            "rationale and /tmp/audio-research-topology-audit.md Defect #2"
        )

    def test_limiter_plugin_is_lookahead_not_clipper(self, loudnorm_conf_text: str) -> None:
        """Phase 1.5 hot-fix replaced hard_limiter_1413 (sample-clipper,
        produces square-wave distortion at low ceilings) with
        fast_lookahead_limiter_1913 (true lookahead limiter). Pin the
        plugin so a future "let's just swap back" doesn't reintroduce
        the distortion regression.
        """
        assert "fast_lookahead_limiter_1913" in loudnorm_conf_text, (
            "music-loudnorm MUST use fast_lookahead_limiter_1913 — "
            "hard_limiter_1413 is a sample-clipper and produces square-wave "
            "distortion at low ceilings on hot program material"
        )


class TestMpcHandoff:
    """The playback target is owned by the MPC link map, not target.object.

    Audio ducking is retired for the MPC Live III baseline. This node
    must expose stable FL/FR playback ports with autoconnect disabled;
    the reconciler maps those ports to MPC USB IN 1/2.
    """

    def test_playback_target_is_reconciler_owned(self, loudnorm_conf_text: str) -> None:
        stripped = _strip_comments(loudnorm_conf_text)
        playback_idx = stripped.find("playback.props")
        assert playback_idx >= 0, "loudnorm conf missing playback.props block"
        rest = stripped[playback_idx:]
        target_match = re.search(r'target\.object\s*=\s*"([^"]+)"', rest)
        assert target_match is None, (
            "music-loudnorm playback.props must not declare target.object; "
            "the MPC-first routing contract is owned by hapax-audio-reconciler"
        )
        assert "node.autoconnect = false" in rest
        assert 'node.description = "Hapax Music Loudnorm → MPC USB IN 1/2"' in rest

    def test_playback_target_is_not_duck_or_l12_alsa_sink(self, loudnorm_conf_text: str) -> None:
        """Explicit negative pin: the deployed conf's failure mode was
        target.object = a duck node or an alsa_output.usb-ZOOM_Corporation_L-12...
        sink name. Catch both retired routing shapes head-on.
        """
        stripped = _strip_comments(loudnorm_conf_text)
        playback_idx = stripped.find("playback.props")
        assert playback_idx >= 0
        rest = stripped[playback_idx:]
        assert "hapax-music-duck" not in rest
        assert "alsa_output.usb-ZOOM_Corporation_L-12" not in rest
