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


def test_uses_sc4m_compressor(raw_config: str) -> None:
    """Mono SC4 (sc4m) — its 'Input'/'Output' audio ports address
    cleanly inside per-channel link declarations. The stereo sc4_1882
    has 'Left input'/'Right input'/'Left output'/'Right output' which
    breaks the per-channel pattern (verified via live PipeWire deploy
    + analyseplugin port introspection 2026-04-20)."""
    assert "sc4m_1916" in raw_config
    assert '"sc4m"' in raw_config  # label


def test_uses_fast_lookahead_limiter(raw_config: str) -> None:
    """Audit B #10 (2026-05-02): YT loudnorm migrated from sample-clipper
    hard_limiter_1413 to stereo fast_lookahead_limiter_1913. The mono
    sc4m compressors stay (they shape per-channel), but the limiter is
    now a single stereo instance — same shape as music + voice-fx +
    pc-loudnorm chains. Comments still document the migration so we
    strip them before checking the dead plugin name is gone."""
    body = _strip_comments(raw_config)
    assert "fast_lookahead_limiter_1913" in body
    assert '"fastLookaheadLimiter"' in body
    # Belt-and-braces: the sample-clipper must be GONE from the active
    # config (comments may still mention it for documentation).
    assert "hard_limiter_1413" not in body
    assert '"hardLimiter"' not in body


def test_stereo_pair_present(raw_config: str) -> None:
    """Stereo bed needs both per-channel sc4m compressors AND a single
    stereo fast_lookahead_limiter named yt_limiter."""
    for stage in ("comp_l", "comp_r", "yt_limiter"):
        assert stage in raw_config, f"missing stage {stage}"


def test_threshold_pinned_at_minus_12db(raw_config: str) -> None:
    """YT bed wallpaper compression starting point. Heavier than voice
    (-18 dB) because uploader variance is wider; tune from here.
    Lifted from -14 to -12 dB after PR #1144 audio remediation."""
    assert '"Threshold level (dB)" = -12' in raw_config


def test_ratio_pinned_at_4_to_1(raw_config: str) -> None:
    """4:1 ratio — heavier than voice (3:1) for wallpaper duty."""
    assert '"Ratio (1:n)" = 4' in raw_config


def test_true_peak_ceiling_pinned_at_minus_1_0_dbtp(raw_config: str) -> None:
    """Audit spec §3.4 target + audit B #10 alignment with voice and
    master ceilings (-1.0 dBTP). Control name on
    fast_lookahead_limiter_1913 is 'Limit (dB)' (NOT 'dB limit' which
    was the hard_limiter_1413 control name we migrated away from)."""
    assert '"Limit (dB)"       = -1.0' in raw_config or '"Limit (dB)" = -1.0' in raw_config


def test_audio_rate_48k(raw_config: str) -> None:
    """Match the rest of the broadcast chain — no resampling cost."""
    assert "audio.rate = 48000" in raw_config


def test_braces_balanced(raw_config: str) -> None:
    stripped = _strip_comments(raw_config)
    cleaned = re.sub(r'"[^"]*"', '""', stripped)
    assert cleaned.count("{") == cleaned.count("}")
    assert cleaned.count("[") == cleaned.count("]")
