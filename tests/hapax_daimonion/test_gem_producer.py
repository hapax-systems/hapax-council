"""Tests for gem_producer (GEM frame authoring from impingements)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.hapax_daimonion.gem_producer import (
    MAX_FRAME_TEXT_CHARS,
    MAX_FRAMES_PER_IMPINGEMENT,
    _extract_emphasis_text,
    _frame_text_safe,
    _intent_matches,
    frames_for_impingement,
    render_composition_template,
    render_emphasis_template,
    write_frames_atomic,
)
from agents.studio_compositor.gem_source import GemFrame
from shared.impingement import Impingement, ImpingementType


def _make_impingement(
    *,
    intent_family: str | None = "gem.emphasis.idea",
    content: dict | None = None,
) -> Impingement:
    return Impingement(
        timestamp=1.0,
        source="test",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
        content=content or {},
        intent_family=intent_family,
    )


# ── Intent gating ────────────────────────────────────────────────────────


def test_intent_matches_emphasis_prefix() -> None:
    assert _intent_matches(_make_impingement(intent_family="gem.emphasis"))
    assert _intent_matches(_make_impingement(intent_family="gem.emphasis.word"))


def test_intent_matches_composition_prefix() -> None:
    assert _intent_matches(_make_impingement(intent_family="gem.composition"))
    assert _intent_matches(_make_impingement(intent_family="gem.composition.tree"))


def test_intent_rejects_non_gem() -> None:
    assert not _intent_matches(_make_impingement(intent_family="ward.highlight.token_pole"))
    assert not _intent_matches(_make_impingement(intent_family="camera.hero"))
    assert not _intent_matches(_make_impingement(intent_family=None))


# ── Text extraction ──────────────────────────────────────────────────────


def test_extract_emphasis_text_prefers_explicit() -> None:
    imp = _make_impingement(content={"emphasis_text": "ACIDIC", "narrative": "less specific"})
    assert _extract_emphasis_text(imp) == "ACIDIC"


def test_extract_emphasis_text_falls_back_to_narrative() -> None:
    imp = _make_impingement(content={"narrative": "spectral drift"})
    assert _extract_emphasis_text(imp) == "spectral drift"


def test_extract_emphasis_text_empty_when_no_keys() -> None:
    assert _extract_emphasis_text(_make_impingement(content={})) == ""


# ── Sanitization ─────────────────────────────────────────────────────────


def test_frame_text_safe_strips_emoji() -> None:
    assert _frame_text_safe("hello 😀") == ""


def test_frame_text_safe_truncates_long() -> None:
    long_text = "x" * (MAX_FRAME_TEXT_CHARS + 50)
    safe = _frame_text_safe(long_text)
    assert len(safe) <= MAX_FRAME_TEXT_CHARS
    assert safe.endswith("…")


def test_frame_text_safe_preserves_short_cp437() -> None:
    assert _frame_text_safe("» hapax «") == "» hapax «"
    assert _frame_text_safe("┌─[ ACIDIC ]─┐") == "┌─[ ACIDIC ]─┐"


# ── Templates ────────────────────────────────────────────────────────────


def test_emphasis_template_produces_three_frames() -> None:
    frames = render_emphasis_template("ACIDIC")
    assert len(frames) == 3
    # First frame is empty banner, second has the text, third is post-fade
    assert "ACIDIC" in frames[1].text
    assert "ACIDIC" in frames[2].text


def test_emphasis_template_returns_empty_on_emoji() -> None:
    assert render_emphasis_template("hello 😀") == []


def test_composition_template_single_frame() -> None:
    frames = render_composition_template("spectral drift")
    assert len(frames) == 1
    assert frames[0].text.startswith(">>> ")


# ── frames_for_impingement integration ──────────────────────────────────


def test_frames_for_impingement_emphasis() -> None:
    imp = _make_impingement(intent_family="gem.emphasis.word", content={"emphasis_text": "ACIDIC"})
    frames = frames_for_impingement(imp)
    assert len(frames) == 3
    assert all(isinstance(f, GemFrame) for f in frames)


def test_frames_for_impingement_composition_routes_to_composition_template() -> None:
    imp = _make_impingement(
        intent_family="gem.composition.tree", content={"narrative": "growing branches"}
    )
    frames = frames_for_impingement(imp)
    assert len(frames) == 1
    assert frames[0].text == ">>> growing branches"


def test_frames_for_impingement_caps_at_max() -> None:
    """No template currently exceeds the cap, but the cap itself must be enforced."""
    imp = _make_impingement(intent_family="gem.emphasis.x", content={"emphasis_text": "x"})
    frames = frames_for_impingement(imp)
    assert len(frames) <= MAX_FRAMES_PER_IMPINGEMENT


def test_frames_for_impingement_rejects_non_gem() -> None:
    imp = _make_impingement(
        intent_family="ward.highlight.token_pole", content={"emphasis_text": "x"}
    )
    assert frames_for_impingement(imp) == []


def test_frames_for_impingement_rejects_emoji_payload() -> None:
    imp = _make_impingement(intent_family="gem.emphasis.x", content={"emphasis_text": "yo 😀"})
    assert frames_for_impingement(imp) == []


# ── Atomic write ─────────────────────────────────────────────────────────


def test_write_frames_atomic_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "gem-frames.json"
    frames = [GemFrame(text="a", hold_ms=400), GemFrame(text="b", hold_ms=1500)]
    write_frames_atomic(frames, target)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert len(payload["frames"]) == 2
    assert payload["frames"][0]["text"] == "a"
    assert payload["frames"][0]["hold_ms"] == 400
    assert payload["frames"][1]["hold_ms"] == 1500
    assert "written_ts" in payload


def test_write_frames_atomic_no_partial_files_on_success(tmp_path: Path) -> None:
    target = tmp_path / "gem-frames.json"
    write_frames_atomic([GemFrame(text="x")], target)
    # No .tmp leftovers in the directory.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_write_frames_atomic_rejects_space_only_payload(tmp_path: Path) -> None:
    target = tmp_path / "gem-frames.json"

    with pytest.raises(ValueError, match="renderable frame"):
        write_frames_atomic([GemFrame(text=" ", hold_ms=100)], target)

    assert not target.exists()
