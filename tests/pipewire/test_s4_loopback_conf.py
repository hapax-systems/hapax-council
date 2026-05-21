"""Regression pin for the S-4 fail-closed PipeWire conf.

Pins the sink-name fixed point and module while preventing stale live
targets from silently re-enabling S-4 USB livestream egress.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-s4-loopback.conf"


@pytest.fixture()
def raw_config() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip("hapax-s4-loopback.conf missing from repo checkout")
    return CONFIG_PATH.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_capture_sink_name_fixed_point(raw_config: str) -> None:
    """The S-4 stereo content sink the operator targets — don't rename."""
    assert 'node.name        = "hapax-s4-content"' in raw_config


def test_playback_has_no_livestream_tap_target(raw_config: str) -> None:
    """S-4 is dormant until a bounded activation task proves a route."""
    assert 'target.object    = "hapax-livestream-tap"' not in raw_config
    assert "node.autoconnect = false" in raw_config


def test_uses_loopback_module(raw_config: str) -> None:
    """Phase 1 design uses module-loopback, not filter-chain
    (S-4 is a content source, not a sidechain target)."""
    assert "libpipewire-module-loopback" in raw_config


def test_stereo_position_pinned(raw_config: str) -> None:
    """S-4 carries a stereo pair; channel mapping must be FL+FR."""
    assert "[ FL FR ]" in raw_config


def test_native_format_pinned(raw_config: str) -> None:
    """S32 / 48 kHz matches the S-4 USB native format (avoids resample)."""
    assert "audio.format     = S32" in raw_config
    assert "audio.rate       = 44100" in raw_config


def test_braces_balanced(raw_config: str) -> None:
    stripped = _strip_comments(raw_config)
    cleaned = re.sub(r'"[^"]*"', '""', stripped)
    assert cleaned.count("{") == cleaned.count("}")
    assert cleaned.count("[") == cleaned.count("]")
