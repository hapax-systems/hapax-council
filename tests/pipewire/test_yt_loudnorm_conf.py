"""Regression pin for B2 / H#13 YT-bed loudnorm conf.

Pins the conf shape so a future edit can't silently break the
LUFS / dBTP target the voice-vs-YT level invariant depends on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pipewire" / "yt-loudnorm.conf"


@pytest.fixture()
def raw_config() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip("yt-loudnorm.conf missing from repo checkout")
    return CONFIG_PATH.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_sink_name_fixed_point(raw_config: str) -> None:
    """OBS / browser binds to ``hapax-yt-loudnorm`` — don't rename."""
    assert 'node.name = "hapax-yt-loudnorm"' in raw_config


def test_chains_into_ytube_ducker(raw_config: str) -> None:
    """The whole point — normalised output must target the ducker so
    the voice sidechain attenuates the normalised (not raw) level."""
    assert 'target.object = "hapax-ytube-ducked"' in raw_config


def test_uses_filter_chain_module(raw_config: str) -> None:
    assert "libpipewire-module-filter-chain" in raw_config


def test_uses_sc4_compressor(raw_config: str) -> None:
    """SC4 LADSPA compressor — same plugin as voice-fx-loudnorm.conf
    (proven in production for the TTS chain)."""
    assert "sc4_1882" in raw_config
    assert '"sc4"' in raw_config  # label


def test_uses_fast_lookahead_limiter(raw_config: str) -> None:
    """Steve Harris fast-lookahead-limiter for true-peak ceiling."""
    assert "fast_lookahead_limiter_1913" in raw_config
    assert '"fastLookaheadLimiter"' in raw_config


def test_stereo_pair_present(raw_config: str) -> None:
    """Stereo bed needs both _l + _r instances (SC4 + limiter both mono)."""
    for stage in ("yt_comp_l", "yt_comp_r", "yt_limit_l", "yt_limit_r"):
        assert stage in raw_config, f"missing stereo stage {stage}"


def test_threshold_pinned_at_minus_14db(raw_config: str) -> None:
    """YT bed wallpaper compression starting point. Heavier than voice
    (-18 dB) because uploader variance is wider; tune from here."""
    assert '"Threshold level (dB)" = -14' in raw_config


def test_ratio_pinned_at_4_to_1(raw_config: str) -> None:
    """4:1 ratio — heavier than voice (3:1) for wallpaper duty."""
    assert '"Ratio (1:n)" = 4' in raw_config


def test_true_peak_ceiling_pinned_at_minus_1_5_dbtp(raw_config: str) -> None:
    """Audit spec §3.4 target. Leaves 0.5 dB headroom under voice
    (-1.0 dB) so YT bed can never out-peak the operator voice."""
    assert '"Limit (dB)" = -1.5' in raw_config


def test_audio_rate_48k(raw_config: str) -> None:
    """Match the rest of the broadcast chain — no resampling cost."""
    assert "audio.rate = 48000" in raw_config


def test_braces_balanced(raw_config: str) -> None:
    stripped = _strip_comments(raw_config)
    cleaned = re.sub(r'"[^"]*"', '""', stripped)
    assert cleaned.count("{") == cleaned.count("}")
    assert cleaned.count("[") == cleaned.count("]")
