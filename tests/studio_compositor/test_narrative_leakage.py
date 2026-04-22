"""Regression tests for narrative-leakage audit (operator 2026-04-22).

Operator screenshots showed director narrative_text + impingement
narrative leaking into ward render output:

- ``activity_header`` showed ``[OBSERVE | Cut to the wide shot of
  the room]`` — the director's narrative as a "gloss" inline with
  the activity badge.
- ``GEM`` ward showed ``>>> Compose a minimal CP437 glyph
  sequence to mark the current system status`` — the LLM's
  meta-instruction-to-self rendered as the mural content.

Both violate ``feedback_show_dont_tell_director``: wards must not
narrate compositor / director actions. The action IS the
communication; a label about the action is operator-side noise.

This test module pins both contracts:
1. activity_header must NOT render any impingement narrative inline,
   regardless of the impingement's salience or content.
2. GEM producer must REJECT meta-narration narratives (ones that
   describe what the system is about to do rather than content).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    import cairo  # noqa: F401

    _CAIRO = True
except ImportError:
    _CAIRO = False

from agents.hapax_daimonion.gem_producer import (
    _extract_emphasis_text,
    _is_meta_narration,
)
from shared.impingement import Impingement, ImpingementType


def _make_imp(**content_kwargs) -> Impingement:
    """Construct a minimal Impingement with the given content keys."""
    return Impingement(
        timestamp=1.0,
        source="test",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.5,
        intent_family="gem.emphasis.event-marker",
        content=dict(content_kwargs),
    )


requires_cairo = pytest.mark.skipif(not _CAIRO, reason="cairo not installed")


# ── activity_header gloss rejection ──────────────────────────────────────


@requires_cairo
def test_activity_header_does_not_render_impingement_narrative() -> None:
    """Even with a high-salience impingement carrying the directorial
    narrative ``Cut to the wide shot of the room``, the rendered
    activity_header surface must NOT contain that text (no inline
    gloss leakage)."""
    from agents.studio_compositor import legibility_sources as ls

    ward = ls.ActivityHeaderCairoSource()
    intent_with_meta_narrative = {
        "activity": "observe",
        "compositional_impingements": [
            {
                "narrative": "Cut to the wide shot of the room.",
                "intent_family": "camera.hero",
                "salience": 0.95,
                "diagnostic": False,
            },
        ],
    }
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 56)
    cr = cairo.Context(surface)
    with (
        patch.object(ls, "_read_narrative_state", return_value={"activity": "observe"}),
        patch.object(ls, "_read_latest_intent", return_value=intent_with_meta_narrative),
        patch.object(ls, "_read_rotation_mode", return_value=None),
    ):
        ward.render_content(cr, 800, 56, t=1.0, state={})
    surface.flush()
    # Pin via the source code: the gloss-extract code path must be
    # gone. The render itself produces a surface (no exception); we
    # cannot easily OCR it in the test, so the source-pin + render-
    # smoke pair ensures the leak isn't reintroduced.
    src = open(ls.__file__, encoding="utf-8").read()
    assert 'best.get("narrative"' not in src, (
        "activity_header re-introduced impingement-narrative gloss extraction "
        "(violates feedback_show_dont_tell_director)"
    )


# ── GEM meta-narration filter ────────────────────────────────────────────


def test_gem_meta_narration_detection_compose() -> None:
    """The exact phrase from the operator's audit screenshot must be
    flagged as meta-narration."""
    text = "Compose a minimal CP437 glyph sequence to mark the current system status."
    assert _is_meta_narration(text), f"GEM meta-narration filter missed: {text!r}"


def test_gem_meta_narration_detection_cut_to() -> None:
    text = "Cut to the wide shot of the room."
    assert _is_meta_narration(text)


def test_gem_meta_narration_detection_show_ward() -> None:
    text = "Show the album-overlay ward when music is the focus."
    assert _is_meta_narration(text)


def test_gem_meta_narration_passes_legitimate_lyric() -> None:
    """A real lyric or phrase must NOT be flagged as meta-narration —
    the producer should pass it through to the renderer."""
    for text in (
        "cradle the static",
        "the room remembers",
        "808 weight",
        "no map. no key.",
    ):
        assert not _is_meta_narration(text), (
            f"GEM meta-narration filter false-positive on legitimate lyric: {text!r}"
        )


def test_gem_extract_emphasis_text_skips_meta_narrative() -> None:
    """When narrative is meta-narration, _extract_emphasis_text returns
    empty (caller falls back to stock frame), not the meta text."""
    imp = _make_imp(narrative="Compose a minimal CP437 glyph sequence to mark status.")
    assert _extract_emphasis_text(imp) == ""


def test_gem_extract_emphasis_text_uses_explicit_emphasis_text() -> None:
    """``content.emphasis_text`` is the trusted-author field — it
    bypasses the meta filter even if the value looks meta. The author
    chose it explicitly."""
    imp = _make_imp(
        emphasis_text="FOCUS",  # author's explicit choice
        narrative="Compose a glyph to mark focus.",  # meta
    )
    assert _extract_emphasis_text(imp) == "FOCUS"


def test_gem_extract_emphasis_text_passes_legitimate_narrative() -> None:
    """Non-meta narrative still passes through (lyric, phrase, etc.)."""
    imp = _make_imp(narrative="cradle the static")
    assert _extract_emphasis_text(imp) == "cradle the static"
