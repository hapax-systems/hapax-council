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


class _SpyContext(cairo.Context):
    """cairo.Context subclass that records arc calls.

    Pango accepts ``cairo.Context`` subclasses (verified), so we can
    pass this into ``PangoCairo.create_layout(cr)`` without the C-level
    type check rejecting a duck-typed wrapper. ``__init__`` chains up
    via ``cairo.Context.__init__`` because the default ``object.__init__``
    does not accept a surface argument.

    ``show_text_calls`` is populated by the ``_draw_pango`` / ``render_text``
    monkey-patches installed by :func:`_render`, not by this class
    directly — Pango does not call ``cr.show_text`` (the Cairo toy API
    entry point) at all.
    """

    def __new__(cls, surface):  # noqa: D401 — pycairo constructs Context via __new__
        inst = cairo.Context.__new__(cls, surface)
        inst.show_text_calls = []
        inst.arc_calls = 0
        return inst

    def arc(self, *args, **kwargs):  # noqa: D401 — matches cairo.Context signature
        self.arc_calls += 1
        return super().arc(*args, **kwargs)


def _render(src_cls, w=800, h=60):
    """Render into a fresh surface and return (surface, spy) for inspection."""
    from unittest.mock import patch

    import agents.studio_compositor.chat_ambient_ward as _caw
    import agents.studio_compositor.homage.rendering as _hr
    import agents.studio_compositor.legibility_sources as _ls
    from agents.studio_compositor import text_render as _tr

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = _SpyContext(surface)

    _real_render = _tr.render_text

    def _spy_render(cr_arg, style, x=0.0, y=0.0):
        # Record on the context so existing test assertions (which
        # read ``spy.show_text_calls``) keep working.
        try:
            cr_arg.show_text_calls.append(style.text)
        except AttributeError:
            pass
        return _real_render(cr_arg, style, x, y)

    with (
        patch.object(_tr, "render_text", _spy_render),
        patch.object(_ls, "_draw_pango", _make_draw_pango_spy(_ls)),
        patch.object(_caw, "_draw_pango", _make_draw_pango_spy(_caw)),
        patch.object(_hr, "irc_line_start", _make_irc_line_start_spy(_hr)),
        patch.object(_hr, "paint_bitchx_header", _make_paint_header_spy(_hr)),
    ):
        src = src_cls()
        src.render(cr, w, h, t=0.0, state={})
    return surface, cr


def _make_draw_pango_spy(module):
    """Return a spy wrapper around ``module._draw_pango`` that records text.

    Appends the text to the context's ``show_text_calls`` (the spy
    context carries the recording list). Preserves the float return
    type so width-threading callers keep working.
    """
    original = module._draw_pango

    def _spy_draw(cr, text, x, y, *, font_description, color_rgba):
        try:
            cr.show_text_calls.append(text)
        except AttributeError:
            pass
        return original(cr, text, x, y, font_description=font_description, color_rgba=color_rgba)

    return _spy_draw


def _make_irc_line_start_spy(module):
    """Spy wrapper for ``homage.rendering.irc_line_start``."""
    original = module.irc_line_start

    def _spy_line_start(cr, x, y, pkg):
        try:
            cr.show_text_calls.append(pkg.grammar.line_start_marker + " ")
        except AttributeError:
            pass
        return original(cr, x, y, pkg)

    return _spy_line_start


def _make_paint_header_spy(module):
    """Spy wrapper for ``homage.rendering.paint_bitchx_header``."""
    original = module.paint_bitchx_header

    def _spy_paint(cr, ward_label, pkg, **kwargs):
        try:
            cr.show_text_calls.append(pkg.grammar.line_start_marker + " ")
            cr.show_text_calls.append(ward_label)
        except AttributeError:
            pass
        return original(cr, ward_label, pkg, **kwargs)

    return _spy_paint


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
    """Return True if the surface contains any non-zero byte.

    Samples the FULL surface, not a head slice — the previous version
    sampled only the first 1000 bytes, which at typical ward dimensions
    (800×60 / 600×24 ARGB32) covers under a row. After the 2026-04-23
    "zero container opacity" directive retired ``_paint_bitchx_bg``,
    the first row is legitimately empty for wards whose content
    renders mid-canvas (y≈30); ward.render-text-at-y=30 lives ~96000
    bytes in. ytb-LEGIBILITY-SMOKE-FOLLOWUP root cause.
    """
    data = bytes(surface.get_data())
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
    def test_active_package_is_authentic_v1_by_default(self):
        from agents.studio_compositor.homage import get_active_package
        from agents.studio_compositor.homage.bitchx_authentic import (
            BITCHX_AUTHENTIC_PACKAGE,
        )

        active = get_active_package()
        # Post AUTH-HOMAGE flip, library-sourced authentic-v1 is default.
        assert active is BITCHX_AUTHENTIC_PACKAGE

    def test_activity_header_uses_line_start_marker(self, tmp_path):
        """Phase A3: chevron marker + activity token now render via
        ``paint_emissive_glyph`` (per-glyph emissive), not Pango. Gloss
        still goes through Pango. Verify via the emissive-glyph call
        log."""
        from unittest.mock import patch

        _write_narrative_state(tmp_path, activity="react")
        _write_intent(
            tmp_path,
            impingements=[{"narrative": "grounded", "salience": 1.0}],
        )
        glyph_log: list[str] = []
        real_glyph = ls.paint_emissive_glyph

        def _spy_glyph(cr_arg, x, y, glyph, font_size, role_rgba, **kw):
            glyph_log.append(glyph)
            return real_glyph(cr_arg, x, y, glyph, font_size, role_rgba, **kw)

        with patch.object(ls, "paint_emissive_glyph", _spy_glyph):
            _render(ls.ActivityHeaderCairoSource, 800, 60)

        marker_chars = {ch for ch in BITCHX_PACKAGE.grammar.line_start_marker if ch != " "}
        assert marker_chars.issubset(set(glyph_log)), (
            f"marker chars {marker_chars} not in emissive glyph log {glyph_log}"
        )
        for ch in "REACT":
            assert ch in glyph_log, f"missing emissive glyph for '{ch}' in {glyph_log}"

    def test_stance_indicator_uses_irc_mode_change_format(self, tmp_path):
        """Phase A3: stance indicator renders brackets + ``+H`` +
        stance label as emissive glyphs."""
        from unittest.mock import patch

        _write_narrative_state(tmp_path, stance="seeking")
        glyph_log: list[str] = []
        real_glyph = ls.paint_emissive_glyph

        def _spy_glyph(cr_arg, x, y, glyph, font_size, role_rgba, **kw):
            glyph_log.append(glyph)
            return real_glyph(cr_arg, x, y, glyph, font_size, role_rgba, **kw)

        with patch.object(ls, "paint_emissive_glyph", _spy_glyph):
            _render(ls.StanceIndicatorCairoSource, 180, 32)
        for ch in "+H":
            assert ch in glyph_log, f"missing emissive glyph for '{ch}'"
        for ch in "SEEKING":
            assert ch in glyph_log, f"missing emissive glyph for '{ch}'"

    def test_chat_keyword_legend_uses_topic_line_format(self, tmp_path):
        _, spy = _render(ls.ChatKeywordLegendCairoSource, 200, 200)
        assert any("Topic" in c for c in spy.show_text_calls)
        assert any("#homage" in c for c in spy.show_text_calls)

    def test_grounding_ticker_uses_join_format(self, tmp_path):
        """Phase A3: ``*`` line-start is now a ``paint_emissive_point``
        centre dot, not a Pango star. Signal name still goes through
        Pango. Verify both."""
        from unittest.mock import patch

        _write_intent(tmp_path, prov=["audio.midi.beat_position"])
        point_count = {"n": 0}
        real_point = ls.paint_emissive_point

        def _spy_point(*a, **k):
            point_count["n"] += 1
            return real_point(*a, **k)

        with patch.object(ls, "paint_emissive_point", _spy_point):
            _, spy = _render(ls.GroundingProvenanceTickerCairoSource, 600, 24)
        assert point_count["n"] >= 1, "missing emissive point for ticker line-start"
        assert any("audio.midi.beat_position" in c for c in spy.show_text_calls)

    def test_grounding_ticker_empty_renders_ungrounded_marker(self, tmp_path):
        _, spy = _render(ls.GroundingProvenanceTickerCairoSource, 600, 24)
        assert any("ungrounded" in c for c in spy.show_text_calls)


class TestNoRoundedRectChrome:
    """Anti-pattern refusal — BitchX grammar forbids rounded corners
    (spec §5.5). Phase A3 broke the naive "no ``cr.arc`` calls" pin
    because emissive halos legitimately paint radial gradients (bounded
    via an arc). The new invariant: **no rounded-rect background chrome**
    — i.e. ``_paint_bitchx_bg`` must not invoke ``cr.arc`` even though
    the content render may.
    """

    @pytest.mark.parametrize(
        "cls",
        [
            ls.ActivityHeaderCairoSource,
            ls.StanceIndicatorCairoSource,
            ls.ChatKeywordLegendCairoSource,
            ls.GroundingProvenanceTickerCairoSource,
        ],
    )
    def test_bg_chrome_has_no_arcs(self, cls, tmp_path):
        from unittest.mock import patch

        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 60)
        cr = _SpyContext(surface)

        real_bg = ls._paint_bitchx_bg
        arcs_during_bg = {"n": 0}

        def _bg_with_arc_spy(cr_arg, w, h, pkg, **kwargs):
            before = cr_arg.arc_calls
            real_bg(cr_arg, w, h, pkg, **kwargs)
            arcs_during_bg["n"] += cr_arg.arc_calls - before

        with patch.object(ls, "_paint_bitchx_bg", _bg_with_arc_spy):
            src = cls()
            src.render(cr, 400, 60, t=0.0, state={})
        assert arcs_during_bg["n"] == 0, (
            f"{cls.__name__} bg chrome invoked {arcs_during_bg['n']} arcs"
        )


# ── Defensive readers — non-dict JSON root ────────────────────────────────


class TestReadersRejectNonDictRoot:
    """Pin that ``_read_narrative_state`` and ``_read_latest_intent``
    survive a writer that produces valid JSON whose root is not a
    mapping. The Cairo callsites at lines 396–398 and 748 do
    ``ns.get(...)`` immediately, so a non-dict return previously raised
    AttributeError into the render callback for activity_header,
    stance_indicator, chat_keyword_legend, and grounding_provenance_ticker.
    """

    @pytest.mark.parametrize(
        "payload,kind",
        [
            ("null", "null"),
            ('"a string"', "string"),
            ("[1, 2, 3]", "list"),
            ("42", "int"),
        ],
    )
    def test_narrative_state_non_dict_root_returns_empty(
        self, payload, kind, tmp_path, monkeypatch
    ):
        path = tmp_path / "narrative.json"
        path.write_text(payload)
        monkeypatch.setattr(ls, "_NARRATIVE_STATE", path)
        result = ls._read_narrative_state()
        assert result == {}, f"narrative root={kind} must yield empty dict"
        # Critical regression pin: callsite must not raise.
        result.get("activity")  # would raise AttributeError on a non-dict

    @pytest.mark.parametrize(
        "payload,kind",
        [
            ("null", "null"),
            ('"a string"', "string"),
            ("[1, 2, 3]", "list"),
            ("42", "int"),
        ],
    )
    def test_latest_intent_non_dict_root_returns_empty(self, payload, kind, tmp_path, monkeypatch):
        path = tmp_path / "intent.jsonl"
        path.write_text(payload + "\n")
        monkeypatch.setattr(ls, "_DIRECTOR_INTENT_JSONL", path)
        result = ls._read_latest_intent()
        assert result == {}, f"intent root={kind} must yield empty dict"
        result.get("activity")  # would raise AttributeError on a non-dict
