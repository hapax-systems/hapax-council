"""Tests for agents.studio_compositor.stream_overlay (A4).

Covers the formatting helpers, graceful degradation when SHM files are
missing/malformed, and a one-shot render tick to confirm the CairoSource
draws into the runner's output surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import cairo
import pytest

from agents.studio_compositor import stream_overlay as so
from agents.studio_compositor.cairo_source import CairoSourceRunner


def _pango_available() -> bool:
    """True iff the GI Pango/PangoCairo typelibs are importable.

    CI containers without GTK skip the render-path tests. Same pattern as
    tests/test_text_render.py.
    """
    try:
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


_HAS_PANGO = _pango_available()
requires_pango = pytest.mark.skipif(
    not _HAS_PANGO, reason="GI Pango/PangoCairo typelibs not installed"
)


# HOMAGE Phase A4 rewrote stream_overlay format helpers to BitchX grammar:
#   >>> [FX|<chain>]    >>> [VIEWERS|<count>]    >>> [CHAT|<status>]
# Tests updated accordingly.


def test_format_preset_known_value():
    assert so._format_preset("chain") == ">>> [FX|chain]"


def test_format_preset_empty_falls_back():
    assert so._format_preset("") == ">>> [FX|—]"


def test_format_preset_truncates_long_values():
    assert so._format_preset("a" * 50) == ">>> [FX|" + "a" * 20 + "]"


def test_format_viewers_singular():
    assert so._format_viewers({"active_viewers": 1}) == ">>> [VIEWERS|1]"


def test_format_viewers_plural():
    assert so._format_viewers({"active_viewers": 42}) == ">>> [VIEWERS|42]"


def test_format_viewers_missing_falls_back():
    assert so._format_viewers({}) == ">>> [VIEWERS|—]"


def test_format_viewers_rejects_non_int():
    assert so._format_viewers({"active_viewers": "infinite"}) == ">>> [VIEWERS|—]"


def test_format_viewers_rejects_negative():
    assert so._format_viewers({"active_viewers": -3}) == ">>> [VIEWERS|—]"


def test_format_chat_idle_on_empty_dict():
    assert so._format_chat({}) == ">>> [CHAT|idle]"


def test_format_chat_idle_on_zero_messages():
    assert so._format_chat({"total_messages": 0, "unique_authors": 0}) == ">>> [CHAT|idle]"


def test_format_chat_quiet_on_single_author():
    assert so._format_chat({"total_messages": 5, "unique_authors": 1}) == ">>> [CHAT|quiet 5]"


def test_format_chat_active_on_multiple_authors():
    assert so._format_chat({"total_messages": 17, "unique_authors": 4}) == ">>> [CHAT|4t/17m]"


def test_format_chat_rejects_non_int_fields():
    assert so._format_chat({"total_messages": "x", "unique_authors": 2}) == ">>> [CHAT|idle]"


def test_read_text_missing_file(tmp_path: Path):
    assert so._read_text(tmp_path / "does-not-exist") == ""


def test_read_text_strips_whitespace(tmp_path: Path):
    p = tmp_path / "f.txt"
    p.write_text("  chain\n")
    assert so._read_text(p) == "chain"


def test_read_json_missing_file(tmp_path: Path):
    assert so._read_json(tmp_path / "missing.json") == {}


def test_read_json_malformed(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not-json")
    assert so._read_json(p) == {}


def test_read_json_round_trip(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"active_viewers": 7}))
    assert so._read_json(p) == {"active_viewers": 7}


@pytest.fixture
def populated_shm(tmp_path: Path, monkeypatch):
    """Populate tmp SHM with realistic-looking files and patch module paths."""
    (tmp_path / "fx-current.txt").write_text("halftone")
    (tmp_path / "token-ledger.json").write_text(
        json.dumps({"active_viewers": 3, "total_tokens": 100})
    )
    (tmp_path / "chat-state.json").write_text(
        json.dumps({"total_messages": 12, "unique_authors": 4})
    )
    monkeypatch.setattr(so, "SHM_DIR", tmp_path)
    monkeypatch.setattr(so, "FX_CURRENT_FILE", tmp_path / "fx-current.txt")
    monkeypatch.setattr(so, "TOKEN_LEDGER_FILE", tmp_path / "token-ledger.json")
    monkeypatch.setattr(so, "CHAT_STATE_FILE", tmp_path / "chat-state.json")
    return tmp_path


@requires_pango
def test_render_tick_draws_into_surface(populated_shm):
    """A single render tick must write visible pixels to the output surface."""
    source = so.StreamOverlayCairoSource()
    runner = CairoSourceRunner(
        source_id="test-stream-overlay",
        source=source,
        canvas_w=640,
        canvas_h=360,
        target_fps=2.0,
    )
    runner.tick_once()

    surface = runner.get_output_surface()
    assert surface is not None
    assert surface.get_width() == 640
    assert surface.get_height() == 360
    # At least some pixels must be non-zero (text rendered).
    data = bytes(surface.get_data())
    assert any(b != 0 for b in data), "render produced an empty surface"


@requires_pango
def test_render_tick_survives_missing_shm_files(tmp_path: Path, monkeypatch):
    """Missing SHM files must not break rendering — all three fall back."""
    # Nothing populated in tmp_path.
    monkeypatch.setattr(so, "FX_CURRENT_FILE", tmp_path / "nope.txt")
    monkeypatch.setattr(so, "TOKEN_LEDGER_FILE", tmp_path / "nope.json")
    monkeypatch.setattr(so, "CHAT_STATE_FILE", tmp_path / "nope.json")

    source = so.StreamOverlayCairoSource()
    runner = CairoSourceRunner(
        source_id="test-stream-overlay-degraded",
        source=source,
        canvas_w=480,
        canvas_h=270,
        target_fps=2.0,
    )
    runner.tick_once()  # must not raise

    surface = runner.get_output_surface()
    assert surface is not None


@requires_pango
def test_render_tick_respects_canvas_size(populated_shm):
    """Arbitrary canvas sizes work — text should anchor to bottom-right regardless."""
    source = so.StreamOverlayCairoSource()
    for w, h in [(1920, 1080), (1280, 720), (640, 360)]:
        runner = CairoSourceRunner(
            source_id=f"test-stream-overlay-{w}x{h}",
            source=source,
            canvas_w=w,
            canvas_h=h,
            target_fps=2.0,
        )
        runner.tick_once()
        surface = runner.get_output_surface()
        assert surface is not None
        assert surface.get_format() == cairo.FORMAT_ARGB32
        assert surface.get_width() == w
        assert surface.get_height() == h


# ── Defensive _read_json — non-dict JSON root ──────────────────────────


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a string"', "string"), ("[1, 2, 3]", "list"), ("42", "int")],
)
def test_read_json_non_dict_root_returns_empty(tmp_path: Path, payload: str, kind: str):
    """Pin ``_read_json`` against non-dict JSON roots. The ``_format_viewers``
    and ``_format_chat`` callers call ``ledger.get(\"active_viewers\")`` /
    ``state.get(\"total_messages\")`` directly on the returned value — a
    non-dict root previously raised AttributeError out of the stream-overlay
    cairo callback."""
    path = tmp_path / "ledger.json"
    path.write_text(payload)
    assert so._read_json(path) == {}, f"non-dict root={kind} must yield empty dict"
    # Critical: the callsite contract.
    so._read_json(path).get("active_viewers")
