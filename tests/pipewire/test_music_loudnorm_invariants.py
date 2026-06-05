"""Music-loudnorm invariant pins.

Defect #2 from `/tmp/audio-research-topology-audit.md` (2026-05-03):
the deployed `~/.config/pipewire/pipewire.conf.d/hapax-music-loudnorm.conf`
was hand-edited to bypass the governed routing plane (target.object = L-12 USB
sink directly) and to change live level handling out of band. Both edits
silently break the current mk5/S-4 audio architecture: music leaves the
reconciled software-sum link map, operator-visible routing drifts, and
downstream program level can run near-clip or silently disappear.

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


class TestAudibilityPassthrough:
    """Music-loudnorm must stay audibility-preserving until re-witnessed.

    The deployed live route used builtin mixers after the LADSPA limiter path
    proved capable of emitting silence. Reintroducing a limiter requires fresh
    live audibility evidence at music-loudnorm-playback and livestream-tap.
    """

    def test_limiter_stage_is_not_active(self, loudnorm_conf_text: str) -> None:
        stripped = _strip_comments(loudnorm_conf_text)
        assert "type = ladspa" not in stripped
        assert "fast_lookahead_limiter_1913" not in stripped
        assert '"Limit (dB)"' not in stripped

    def test_passthrough_gain_is_pinned_to_live_headroom(self, loudnorm_conf_text: str) -> None:
        stripped = _strip_comments(loudnorm_conf_text)
        gains = [float(match) for match in re.findall(r'"Gain 1"\s*=\s*([\d.]+)', stripped)]
        assert gains == [0.35, 0.35]
        assert stripped.count("type = builtin") == 2


class TestSoftwareSumHandoff:
    """The playback target is owned by the link map, not target.object.

    Audio ducking is retired for the mk5/S-4 baseline. This node
    must expose stable FL/FR playback ports with autoconnect disabled;
    the reconciler maps those ports to hapax-livestream-tap.
    """

    def test_playback_target_is_reconciler_owned(self, loudnorm_conf_text: str) -> None:
        stripped = _strip_comments(loudnorm_conf_text)
        playback_idx = stripped.find("playback.props")
        assert playback_idx >= 0, "loudnorm conf missing playback.props block"
        rest = stripped[playback_idx:]
        target_match = re.search(r'target\.object\s*=\s*"([^"]+)"', rest)
        assert target_match is None, (
            "music-loudnorm playback.props must not declare target.object; "
            "the software-sum routing contract is owned by hapax-audio-reconciler"
        )
        assert "node.autoconnect = false" in rest
        assert 'node.description = "Hapax Music Loudnorm -> livestream-tap software sum"' in rest

    def test_playback_target_is_not_duck_or_l12_alsa_sink(self, loudnorm_conf_text: str) -> None:
        """Explicit negative pin: the deployed conf's failure mode was
        target.object = a duck node or a retired hardware sink. Catch both
        retired routing shapes head-on.
        """
        stripped = _strip_comments(loudnorm_conf_text)
        playback_idx = stripped.find("playback.props")
        assert playback_idx >= 0
        rest = stripped[playback_idx:]
        assert "hapax-music-duck" not in rest
        assert "alsa_output.usb-ZOOM_Corporation_L-12" not in rest
        assert "alsa_output.usb-Akai_Professional_MPC" not in rest
