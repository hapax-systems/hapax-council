"""Tests for clip_renderer module."""

from __future__ import annotations

from agents.auto_clip.clip_renderer import (
    CHANNEL_ACCENT,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    _build_filter_graph,
)
from agents.auto_clip.segment_detection import DecoderChannel


def test_filter_graph_contains_output_dimensions():
    vf = _build_filter_graph("test hook", DecoderChannel.VISUAL)
    assert f"{OUTPUT_WIDTH}" in vf
    assert f"{OUTPUT_HEIGHT}" in vf


def test_filter_graph_contains_hook_text():
    vf = _build_filter_graph("watch this shimmer", DecoderChannel.SONIC)
    assert "watch this shimmer" in vf


def test_filter_graph_uses_channel_accent():
    for channel, accent in CHANNEL_ACCENT.items():
        vf = _build_filter_graph("hook", channel)
        assert accent in vf


def test_filter_graph_escapes_colons():
    vf = _build_filter_graph("test: value", DecoderChannel.LINGUISTIC)
    assert "test\\:" in vf
