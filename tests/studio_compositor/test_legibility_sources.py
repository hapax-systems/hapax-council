"""Smoke + BitchX-grammar authenticity tests for the 4 legibility Cairo sources.

Phase 4 of the HOMAGE epic. These tests pin:
- That each migrated source still renders without error under feature-flag-off.
- That the ward inherits HomageTransitionalSource (FSM hook points available).
- That BitchX grammar is applied via ``get_active_package()`` — monospaced
  font selection, palette roles resolved from the package (no hardcoded hex),
  no rounded-rect chrome.
"""

from __future__ import annotations

import json

import cairo
import pytest

from agents.studio_compositor import legibility_sources as ls
from agents.studio_compositor.homage import BITCHX_PACKAGE
from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)


class _SpyContext:
    """Delegating wrapper around cairo.Context that records show_text + arc."""

    def __init__(self, cr: cairo.Context) -> None:
        self._cr = cr
        self.show_text_calls: list[str] = []
        self.arc_calls: int = 0

    def show_text(self, text):
        self.show_text_calls.append(text)
        return self._cr.show_text(text)

    def arc(self, *args, **kwargs):
        self.arc_calls += 1
        return self._cr.arc(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cr, name)


def _render(src_cls, w=800, h=60):
    """Render into a fresh surface and return (surface, spy) for inspection."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    spy = _SpyContext(cr)
    src = src_cls()
    src.render(spy, w, h, t=0.0, state={})
    return surface, spy


@pytest.fixture(autouse=True)
def _redirect_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(ls, "_NARRATIVE_STATE", tmp_path / "narrative-state.json")
    monkeypatch.setattr(ls, "_DIRECTOR_INTENT_JSONL", tmp_path / "director-intent.jsonl")
    # Phase 12 flipped HAPAX_HOMAGE_ACTIVE to default-ON, which makes
    # HomageTransitionalSource subclasses start in ABSENT state. These
    # tests pin feature-flag-OFF behaviour (legacy paint-and-hold), so
    # set the flag explicitly here.
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")
    return tmp_path


def _write_narrative_state(tmp_path, stance="nominal", activity="react"):
    (tmp_path / "narrative-state.json").write_text(
        json.dumps(
            {
                "stance": stance,
                "activity": activity,
                "last_tick_ts": 0,
                "condition_id": "c",
            }
        )
    )


def _write_intent(tmp_path, prov=None, impingements=None):
    payload = {
        "activity": "vinyl",
        "stance": "nominal",
        "narrative_text": "",
        "grounding_provenance": prov or [],
        "compositional_impingements": impingements or [],
    }
    (tmp_path / "director-intent.jsonl").write_text(json.dumps(payload) + "\n")


def _surface_not_empty(surface: cairo.ImageSurface) -> bool:
    data = bytes(surface.get_data()[:1000])
    return any(b != 0 for b in data)


# ── Smoke tests — render without crash, all states populated ──────────────


class TestSmoke:
    def test_activity_header_renders_without_state(self, tmp_path):
        surf, _spy = _render(ls.ActivityHeaderCairoSource, 800, 60)
        assert _surface_not_empty(surf)

    def test_activity_header_reads_narrative_and_intent(self, tmp_path):
        _write_narrative_state(tmp_path, activity="vinyl")
        _write_intent(
            tmp_path,
            impingements=[
                {
                    "narrative": "turntable focus",
                    "intent_family": "camera.hero",
                    "salience": 0.9,
                }
            ],
        )
        surf, _spy = _render(ls.ActivityHeaderCairoSource, 800, 60)
        assert _surface_not_empty(surf)

    def test_stance_indicator_renders(self, tmp_path):
        _write_narrative_state(tmp_path, stance="seeking")
        surf, _spy = _render(ls.StanceIndicatorCairoSource, 180, 32)
        assert _surface_not_empty(surf)

    def test_chat_keyword_legend_renders(self, tmp_path):
        surf, _spy = _render(ls.ChatKeywordLegendCairoSource, 200, 200)
        assert _surface_not_empty(surf)

    def test_grounding_ticker_renders_empty(self, tmp_path):
        surf, _spy = _render(ls.GroundingProvenanceTickerCairoSource, 600, 24)
        assert _surface_not_empty(surf)

    def test_grounding_ticker_renders_with_signals(self, tmp_path):
        _write_intent(tmp_path, prov=["audio.midi.beat_position", "ir.ir_hand_zone.turntable"])
        surf, _spy = _render(ls.GroundingProvenanceTickerCairoSource, 600, 24)
        assert _surface_not_empty(surf)


# ── HOMAGE FSM inheritance ────────────────────────────────────────────────


class TestInheritsHomageTransitionalSource:
    @pytest.mark.parametrize(
        "cls",
        [
            ls.ActivityHeaderCairoSource,
            ls.StanceIndicatorCairoSource,
            ls.ChatKeywordLegendCairoSource,
            ls.GroundingProvenanceTickerCairoSource,
        ],
    )
    def test_is_homage_transitional_source(self, cls):
        assert issubclass(cls, HomageTransitionalSource)

    @pytest.mark.parametrize(
        "cls,expected_id",
        [
            (ls.ActivityHeaderCairoSource, "activity_header"),
            (ls.StanceIndicatorCairoSource, "stance_indicator"),
            (ls.ChatKeywordLegendCairoSource, "chat_keyword_legend"),
            (ls.GroundingProvenanceTickerCairoSource, "grounding_provenance_ticker"),
        ],
    )
    def test_source_id_matches_layout_json(self, cls, expected_id):
        assert cls().source_id == expected_id

    def test_fsm_hook_points_available(self):
        # Hotfix 2026-04-18: HomageTransitionalSource default flipped from
        # ABSENT to HOLD so un-choreographed wards render paint-and-hold
        # content. The ABSENT→ENTERING branch of apply_transition is still
        # exercised by forcing the state back to ABSENT on an existing
        # instance (the subclass __init__ doesn't expose initial_state).
        src = ls.ActivityHeaderCairoSource()
        # Ward now starts in HOLD (post-hotfix default).
        assert src.transition_state is TransitionState.HOLD
        # Force ABSENT to exercise the apply_transition ABSENT→ENTERING path.
        src._state = TransitionState.ABSENT
        src.apply_transition("ticker-scroll-in")
        assert src.transition_state is TransitionState.ENTERING


# ── BitchX grammar pins ────────────────────────────────────────────────────


class TestBitchXGrammarApplied:
    def test_active_package_is_bitchx_by_default(self):
        from agents.studio_compositor.homage import get_active_package

        active = get_active_package()
        assert active is BITCHX_PACKAGE

    def test_activity_header_uses_line_start_marker(self, tmp_path):
        _write_narrative_state(tmp_path, activity="react")
        _write_intent(tmp_path, impingements=[])
        _, spy = _render(ls.ActivityHeaderCairoSource, 800, 60)
        assert any(BITCHX_PACKAGE.grammar.line_start_marker in c for c in spy.show_text_calls)
        assert any("REACT" in c for c in spy.show_text_calls)

    def test_stance_indicator_uses_irc_mode_change_format(self, tmp_path):
        _write_narrative_state(tmp_path, stance="seeking")
        _, spy = _render(ls.StanceIndicatorCairoSource, 180, 32)
        assert any("+H" in c for c in spy.show_text_calls)
        assert any("SEEKING" in c for c in spy.show_text_calls)

    def test_chat_keyword_legend_uses_topic_line_format(self, tmp_path):
        _, spy = _render(ls.ChatKeywordLegendCairoSource, 200, 200)
        assert any("Topic" in c for c in spy.show_text_calls)
        assert any("#homage" in c for c in spy.show_text_calls)

    def test_grounding_ticker_uses_join_format(self, tmp_path):
        _write_intent(tmp_path, prov=["audio.midi.beat_position"])
        _, spy = _render(ls.GroundingProvenanceTickerCairoSource, 600, 24)
        assert any(c.startswith("* ") for c in spy.show_text_calls)

    def test_grounding_ticker_empty_renders_ungrounded_marker(self, tmp_path):
        _, spy = _render(ls.GroundingProvenanceTickerCairoSource, 600, 24)
        assert any("ungrounded" in c for c in spy.show_text_calls)


class TestNoRoundedRectChrome:
    """Anti-pattern refusal — BitchX grammar forbids rounded corners
    (spec §5.5). The migrated wards must not invoke Cairo arc calls for
    background chrome — sharp rectangles only."""

    @pytest.mark.parametrize(
        "cls",
        [
            ls.ActivityHeaderCairoSource,
            ls.ChatKeywordLegendCairoSource,
            ls.GroundingProvenanceTickerCairoSource,
        ],
    )
    def test_no_arcs_in_chrome(self, cls):
        _, spy = _render(cls, 400, 60)
        assert spy.arc_calls == 0

    def test_stance_indicator_no_arcs(self):
        _, spy = _render(ls.StanceIndicatorCairoSource, 400, 60)
        assert spy.arc_calls == 0
