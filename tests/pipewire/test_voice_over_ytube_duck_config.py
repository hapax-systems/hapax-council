"""Regression pin for LRR Phase 9 §3.8 ducker PipeWire config.

Keeps the file parseable (comment-stripped, balanced braces, sink-name
fixed point) so future edits don't silently regress the filter-chain
shape OBS and Chromium rely on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-voice-over-ytube-duck.conf"
)


@pytest.fixture()
def raw_config() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip("ducker config missing from repo checkout")
    return CONFIG_PATH.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Strip full-line comments so brace balancing isn't thrown off."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_sink_name_fixed_point(raw_config: str):
    """OBS + browsers bind to ``hapax-ytube-ducked`` — don't rename it."""
    assert 'node.name = "hapax-ytube-ducked"' in raw_config


def test_braces_balanced(raw_config: str):
    stripped = _strip_comments(raw_config)
    # Strip quoted strings so braces inside comments / descriptions don't count.
    cleaned = re.sub(r'"[^"]*"', '""', stripped)
    assert cleaned.count("{") == cleaned.count("}")
    assert cleaned.count("[") == cleaned.count("]")


def test_uses_filter_chain_module(raw_config: str):
    assert "libpipewire-module-filter-chain" in raw_config


def test_uses_sidechain_compressor_plugin(raw_config: str):
    assert "sc4m_1916" in raw_config
    assert "sc4m" in raw_config  # label


def test_stereo_pair_wiring(raw_config: str):
    """Sidechain nodes are duplicated for L + R channels."""
    assert "duck_l" in raw_config
    assert "duck_r" in raw_config


def test_sc4m_mono_audio_ports_match_runtime_plugin(raw_config: str):
    """sc4m_1916 exposes mono audio ports named Input/Output.

    The stereo ``Left input``/``Left output`` names belong to a different
    LADSPA plugin and make the PipeWire filter-chain fail to link.
    """
    assert 'inputs  = [ "duck_l:Input" "duck_r:Input" ]' in raw_config
    assert 'outputs = [ "duck_l:Output" "duck_r:Output" ]' in raw_config
    assert "duck_l:Left input" not in raw_config
    assert "duck_r:Left input" not in raw_config
    assert "duck_l:Left output" not in raw_config
    assert "duck_r:Left output" not in raw_config


def test_filter_chain_has_threshold_and_ratio_defaults(raw_config: str):
    """Starting-point tuning values stay pinned — operator tunes from here."""
    assert '"Threshold level (dB)" = -30.0' in raw_config
    assert '"Ratio (1:n)" = 8.0' in raw_config
    assert '"Attack time (ms)" = 5.0' in raw_config
    assert '"Release time (ms)" = 300.0' in raw_config


def test_readme_documents_ducker_section():
    readme = (CONFIG_PATH.parent / "README.md").read_text(encoding="utf-8")
    assert "Operator-voice-over-YouTube ducker" in readme
    assert "hapax-ytube-ducked" in readme
    assert "sc4m_1916" in readme
