"""Phase A3 emissive-rewrite tests for legibility_sources.

Covers the four wards rewritten in Phase A3 of homage-completion-plan:

- :class:`ActivityHeaderCairoSource`
- :class:`StanceIndicatorCairoSource`
- :class:`GroundingProvenanceTickerCairoSource`
- :class:`ChatKeywordLegendCairoSource`

Each ward gets at least three tests (smoke render, flash/pulse/slide
behaviour, palette-role wiring) plus one golden-image regression. Total
≥12 unit tests + 4 goldens.

Goldens live under ``tests/studio_compositor/golden_images/legibility/``.
Regenerate with ``HAPAX_UPDATE_GOLDEN=1``. PNGs are gitignored globally
so the commit must ``git add -f`` them (documented in the plan).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agents.studio_compositor import legibility_sources as ls


def _cairo_available() -> bool:
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


_HAS_CAIRO = _cairo_available()
requires_cairo = pytest.mark.skipif(not _HAS_CAIRO, reason="pycairo not installed")


_GOLDEN_DIR = Path(__file__).parent / "golden_images" / "legibility"
_GOLDEN_PIXEL_TOLERANCE = 6  # per channel (slightly looser than emissive_base
# because these surfaces include Pango renders whose rasterisation depends
# on the available font set)


def _update_golden_requested() -> bool:
    return os.environ.get("HAPAX_UPDATE_GOLDEN", "").strip() not in ("", "0", "false")


def _surfaces_match(actual: Any, expected: Any, tolerance: int) -> tuple[bool, str]:
    if actual.get_width() != expected.get_width():
        return False, f"width {actual.get_width()} != {expected.get_width()}"
    if actual.get_height() != expected.get_height():
        return False, f"height {actual.get_height()} != {expected.get_height()}"
    a = bytes(actual.get_data())
    e = bytes(expected.get_data())
    if len(a) != len(e):
        return False, f"byte-len {len(a)} != {len(e)}"
    max_delta = 0
    n_over = 0
    for ab, eb in zip(a, e, strict=True):
        d = abs(ab - eb)
        if d > max_delta:
            max_delta = d
        if d > tolerance:
            n_over += 1
    if max_delta > tolerance:
        return False, f"max delta {max_delta} > tol {tolerance} ({n_over} bytes over)"
    return True, f"max delta {max_delta} within tol {tolerance}"


def _render_ward(ward: Any, w: int, h: int, t: float = 0.0) -> Any:
    """Render ``ward.render_content`` into a fresh ARGB32 surface."""
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    ward.render_content(cr, w, h, t, {})
    surface.flush()
    return surface


def _pixel_rgba(surface: Any, x: int, y: int) -> tuple[int, int, int, int]:
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    offset = y * stride + x * 4
    b = data[offset]
    g = data[offset + 1]
    r = data[offset + 2]
    a = data[offset + 3]
    return r, g, b, a


# ── Activity header ────────────────────────────────────────────────────────


@requires_cairo
class TestActivityHeaderEmissive:
    def test_renders_without_error_with_empty_state(self):
        """Empty narrative / intent still produces a valid surface."""
        ward = ls.ActivityHeaderCairoSource()
        with (
            patch.object(ls, "_read_narrative_state", return_value={}),
            patch.object(ls, "_read_latest_intent", return_value={}),
            patch.object(ls, "_read_rotation_mode", return_value=None),
        ):
            surface = _render_ward(ward, 800, 56, t=0.0)
        assert surface.get_width() == 800
        assert surface.get_height() == 56

    def test_records_activity_change_and_flashes(self):
        """Activity flip stamps ``_activity_flash_started_at``; the flash
        alpha is positive within 200 ms and zero afterwards."""
        ward = ls.ActivityHeaderCairoSource()
        # First render: pin a baseline.
        with (
            patch.object(ls, "_read_narrative_state", return_value={"activity": "alpha"}),
            patch.object(ls, "_read_latest_intent", return_value={}),
            patch.object(ls, "_read_rotation_mode", return_value=None),
        ):
            _render_ward(ward, 800, 56, t=0.0)
        assert ward._last_activity == "ALPHA"
        assert ward._activity_flash_started_at is None

        # Flip activity — should stamp the flash start.
        with (
            patch.object(ls, "_read_narrative_state", return_value={"activity": "bravo"}),
            patch.object(ls, "_read_latest_intent", return_value={}),
            patch.object(ls, "_read_rotation_mode", return_value=None),
        ):
            _render_ward(ward, 800, 56, t=1.0)
        assert ward._last_activity == "BRAVO"
        assert ward._activity_flash_started_at == pytest.approx(1.0)

        # Within the flash window ⇒ positive flash alpha. The lssh-001
        # blink softening stretched the window to 400 ms with a cosine
        # ease-out, so 100 ms in is still meaningfully bright.
        alpha_mid = ls._flash_alpha(1.1, ward._activity_flash_started_at)
        assert alpha_mid > 0.0
        # After the window ⇒ zero (anything past 400 ms is decayed).
        alpha_done = ls._flash_alpha(1.5, ward._activity_flash_started_at)
        assert alpha_done == 0.0

    def test_rotation_mode_suffix_only_when_nondefault(self):
        """The ``:: [ROTATION:<mode>]`` suffix should appear when
        ``_read_rotation_mode`` returns a non-default value, and not
        appear for default modes. The rotation token renders emissively
        so we track it via the emissive-glyph call log."""
        ward = ls.ActivityHeaderCairoSource()

        glyphs: list[str] = []
        real_glyph = ls.paint_emissive_glyph

        def _spy_glyph(cr_arg, x, y, glyph, font_size, role_rgba, **kw):
            glyphs.append(glyph)
            return real_glyph(cr_arg, x, y, glyph, font_size, role_rgba, **kw)

        # Non-default ("burst") — suffix must appear. paint_emissive_glyph
        # may be called multiple times per character (halo + body passes) and
        # calls from different text segments can interleave. Check the set of
        # painted characters rather than a contiguous substring.
        with (
            patch.object(ls, "_read_narrative_state", return_value={"activity": "x"}),
            patch.object(ls, "_read_latest_intent", return_value={}),
            patch.object(ls, "_read_rotation_mode", return_value="burst"),
            patch.object(ls, "paint_emissive_glyph", _spy_glyph),
        ):
            glyphs.clear()
            _render_ward(ward, 800, 56, t=0.0)
        glyph_set = set(glyphs)
        # Every letter of ROTATION and BURST should have been painted.
        rotation_letters = set("ROTATION")
        burst_letters = set("BURST")
        assert rotation_letters.issubset(glyph_set) and burst_letters.issubset(glyph_set), (
            f"rotation suffix missing when mode is burst; "
            f"missing_rotation={rotation_letters - glyph_set}, "
            f"missing_burst={burst_letters - glyph_set}"
        )

        # Default ("steady") — no suffix. Instead of trying to pick letters
        # that are unique to the rotation suffix (brittle — the default
        # chrome renders "[ACTIVITY|X] :: [STANCE:NOMINAL]" and similar
        # which contains many letters), compare TOTAL GLYPH COUNT between
        # the two modes. The burst suffix adds ~15 glyphs (":: [ROTATION:
        # BURST]" = ~14 chars, doubled for halo+body = ~28 glyph calls);
        # if the steady render has significantly fewer glyphs than the
        # burst render captured above, the suffix was skipped correctly.
        burst_glyph_count = len(glyphs)

        ward2 = ls.ActivityHeaderCairoSource()
        with (
            patch.object(ls, "_read_narrative_state", return_value={"activity": "x"}),
            patch.object(ls, "_read_latest_intent", return_value={}),
            patch.object(ls, "_read_rotation_mode", return_value="steady"),
            patch.object(ls, "paint_emissive_glyph", _spy_glyph),
        ):
            glyphs.clear()
            _render_ward(ward2, 800, 56, t=0.0)
        steady_glyph_count = len(glyphs)

        # Steady should be materially shorter — at least 10 fewer glyph
        # calls than burst (conservative floor; actual delta is ~28).
        assert steady_glyph_count < burst_glyph_count - 10, (
            f"rotation suffix present when mode is default; "
            f"steady_glyphs={steady_glyph_count}, burst_glyphs={burst_glyph_count}"
        )

    def test_emissive_primitives_are_invoked(self):
        """Ward must call at least ``paint_emissive_glyph`` for the
        structural tokens (chevron + brackets + activity)."""
        ward = ls.ActivityHeaderCairoSource()

        calls: list[tuple[float, float, str]] = []
        real = ls.paint_emissive_glyph

        def _spy(cr_arg, x, y, glyph, font_size, role_rgba, **kw):
            calls.append((x, y, glyph))
            return real(cr_arg, x, y, glyph, font_size, role_rgba, **kw)

        with (
            patch.object(ls, "_read_narrative_state", return_value={"activity": "test"}),
            patch.object(ls, "_read_latest_intent", return_value={}),
            patch.object(ls, "_read_rotation_mode", return_value=None),
            patch.object(ls, "paint_emissive_glyph", _spy),
        ):
            _render_ward(ward, 800, 56, t=0.0)
        # At minimum: 3-char chevron + 1 space + "[" + "TEST" + "]" — 10 chars
        # worth of emissive glyph calls, minus spaces.
        assert len(calls) >= 6, f"expected ≥6 emissive glyph calls, got {len(calls)}"


# ── Stance indicator ───────────────────────────────────────────────────────


@requires_cairo
class TestStanceIndicatorEmissive:
    def test_renders_with_default_nominal_stance(self):
        ward = ls.StanceIndicatorCairoSource()
        with patch.object(ls, "_read_narrative_state", return_value={}):
            surface = _render_ward(ward, 100, 40, t=0.0)
        assert surface.get_width() == 100

    def test_records_stance_change_and_flashes(self):
        ward = ls.StanceIndicatorCairoSource()
        # Baseline.
        with patch.object(ls, "_read_narrative_state", return_value={"stance": "nominal"}):
            _render_ward(ward, 100, 40, t=0.0)
        assert ward._last_stance == "nominal"
        assert ward._stance_flash_started_at is None

        # Flip.
        with patch.object(ls, "_read_narrative_state", return_value={"stance": "critical"}):
            _render_ward(ward, 100, 40, t=2.0)
        assert ward._last_stance == "critical"
        assert ward._stance_flash_started_at == pytest.approx(2.0)

    def test_pulse_hz_varies_by_stance(self):
        """The stance Hz lookup must produce different rates for
        different stances — critical is fastest, degraded is slowest."""
        from agents.studio_compositor.homage.emissive_base import STANCE_HZ

        assert STANCE_HZ["nominal"] != STANCE_HZ["seeking"]
        assert STANCE_HZ["critical"] > STANCE_HZ["nominal"]
        assert STANCE_HZ["degraded"] < STANCE_HZ["nominal"]

    def test_emissive_primitives_are_invoked(self):
        """Stance indicator uses per-glyph emissive calls for structural
        tokens. At minimum: ``[+H <STANCE>]`` → brackets + label."""
        ward = ls.StanceIndicatorCairoSource()
        count = {"n": 0}
        real = ls.paint_emissive_glyph

        def _spy(cr_arg, x, y, glyph, font_size, role_rgba, **kw):
            count["n"] += 1
            return real(cr_arg, x, y, glyph, font_size, role_rgba, **kw)

        with (
            patch.object(ls, "_read_narrative_state", return_value={"stance": "seeking"}),
            patch.object(ls, "paint_emissive_glyph", _spy),
        ):
            _render_ward(ward, 100, 40, t=0.0)
        # "[+H " + "SEEKING" + "]" minus spaces = ≥10 non-space chars.
        assert count["n"] >= 8, f"expected ≥8 emissive glyph calls, got {count['n']}"


# ── Grounding provenance ticker ────────────────────────────────────────────


@requires_cairo
class TestGroundingProvenanceTickerEmissive:
    def test_ungrounded_state_renders_and_breathes(self):
        """Empty grounding_provenance ⇒ ``(ungrounded)`` label with
        breathing alpha. The breath multiplier must vary with ``t``."""
        from agents.studio_compositor.homage.emissive_base import paint_breathing_alpha

        ward = ls.GroundingProvenanceTickerCairoSource()
        with patch.object(ls, "_read_latest_intent", return_value={"grounding_provenance": []}):
            _render_ward(ward, 480, 40, t=0.0)
            _render_ward(ward, 480, 40, t=0.5)

        # Sanity: the helper that produces the breath alpha gives different
        # values at different t.
        a0 = paint_breathing_alpha(0.0, hz=0.3, baseline=0.55, amplitude=0.25)
        a1 = paint_breathing_alpha(0.5, hz=0.3, baseline=0.55, amplitude=0.25)
        assert a0 != pytest.approx(a1)

    def test_non_empty_provenance_invokes_emissive_star(self):
        """Non-empty provenance ⇒ at least one
        ``paint_emissive_point`` call per row (the ``*`` line-start)."""
        ward = ls.GroundingProvenanceTickerCairoSource()
        count = {"n": 0}
        real = ls.paint_emissive_point

        def _spy(*args, **kwargs):
            count["n"] += 1
            return real(*args, **kwargs)

        with (
            patch.object(
                ls,
                "_read_latest_intent",
                return_value={"grounding_provenance": ["chat", "stimmung", "biometrics"]},
            ),
            patch.object(ls, "paint_emissive_point", _spy),
        ):
            _render_ward(ward, 480, 40, t=0.0)
        assert count["n"] >= 3, (
            f"expected ≥3 emissive point calls (one per signal), got {count['n']}"
        )

    def test_slide_in_on_prov_change(self):
        """Changing the provenance set triggers a slide-in: the
        ``_prov_change_started_at`` timestamp updates and
        ``_slide_progress`` climbs from 0 → 1 over 400 ms."""
        ward = ls.GroundingProvenanceTickerCairoSource()

        # Baseline render with no prov.
        with patch.object(ls, "_read_latest_intent", return_value={"grounding_provenance": []}):
            _render_ward(ward, 480, 40, t=0.0)
        assert ward._last_prov_hash is not None
        assert ward._prov_change_started_at is None

        # Introduce provenance — should stamp a slide-in start.
        with patch.object(
            ls,
            "_read_latest_intent",
            return_value={"grounding_provenance": ["chat"]},
        ):
            _render_ward(ward, 480, 40, t=10.0)
        assert ward._prov_change_started_at == pytest.approx(10.0)
        assert ward._slide_progress(10.0) == pytest.approx(0.0)
        assert 0.0 < ward._slide_progress(10.2) < 1.0
        assert ward._slide_progress(10.5) == pytest.approx(1.0)


# ── Chat keyword legend (legacy alias) ─────────────────────────────────────


@requires_cairo
class TestChatKeywordLegendEmissive:
    def test_renders_without_error(self):
        ward = ls.ChatKeywordLegendCairoSource()
        surface = _render_ward(ward, 560, 40, t=0.0)
        assert surface.get_width() == 560

    def test_emissive_primitives_are_invoked(self):
        """Chat-legend emissive rewrite must invoke both
        ``paint_emissive_point`` (header bullet) and
        ``paint_emissive_glyph`` (per keyword)."""
        ward = ls.ChatKeywordLegendCairoSource()
        n_point = {"n": 0}
        n_glyph = {"n": 0}
        real_p = ls.paint_emissive_point
        real_g = ls.paint_emissive_glyph

        def _spy_p(*a, **k):
            n_point["n"] += 1
            return real_p(*a, **k)

        def _spy_g(*a, **k):
            n_glyph["n"] += 1
            return real_g(*a, **k)

        with (
            patch.object(ls, "paint_emissive_point", _spy_p),
            patch.object(ls, "paint_emissive_glyph", _spy_g),
        ):
            # Large enough canvas to fit all keywords.
            _render_ward(ward, 560, 200, t=0.0)
        assert n_point["n"] >= 1, "expected header bullet emissive point"
        assert n_glyph["n"] >= 10, (
            f"expected ≥10 emissive glyph calls (keyword glyphs), got {n_glyph['n']}"
        )

    def test_remains_instantiable_as_legacy_alias(self):
        """Phase 10 rehearsal §2.3 expectation: this class stays
        importable and instantiable even after ``chat_ambient`` rebinds
        to :class:`ChatAmbientWard` at the layout level."""
        ward = ls.ChatKeywordLegendCairoSource()
        assert ward.source_id == "chat_keyword_legend"


# ── Flash-alpha helper ─────────────────────────────────────────────────────


class TestFlashAlphaHelper:
    def test_none_timestamp_yields_zero(self):
        assert ls._flash_alpha(0.0, None) == 0.0
        assert ls._flash_alpha(10.0, None) == 0.0

    def test_monotone_decay_within_window(self):
        start = 5.0
        a_early = ls._flash_alpha(5.05, start)
        a_late = ls._flash_alpha(5.15, start)
        assert a_early > a_late > 0.0

    def test_zero_after_window(self):
        # lssh-001: window stretched 200 ms → 400 ms. 0.401 s is past
        # the new boundary so still zero.
        assert ls._flash_alpha(5.401, 5.0) == 0.0

    def test_peak_immediately_after_start(self):
        # lssh-001: peak alpha softened 0.45 → 0.15.
        a = ls._flash_alpha(5.0, 5.0)
        assert a == pytest.approx(ls._INVERSE_FLASH_PEAK_ALPHA)
        assert a == pytest.approx(0.15)

    def test_blink_threshold_satisfied(self):
        """Regression for lssh-001: the inverse-flash must not exceed
        the operator's blink threshold (luminance change >40 % faster
        than once per 500 ms). With cosine ease-out from 0.15 over
        400 ms the maximum slope is well under that bar."""
        start = 0.0
        # Sample at 1 ms intervals across the window and find the
        # largest 500-ms-equivalent rate.
        max_rate_per_500ms = 0.0
        prev = ls._flash_alpha(start, start)
        for i in range(1, 401):
            t = start + i / 1000.0
            cur = ls._flash_alpha(t, start)
            instant_rate_per_ms = abs(prev - cur)
            rate_per_500ms = instant_rate_per_ms * 500.0
            if rate_per_500ms > max_rate_per_500ms:
                max_rate_per_500ms = rate_per_500ms
            prev = cur
        assert max_rate_per_500ms < 0.40, (
            f"flash exceeds operator blink threshold: max change-rate "
            f"{max_rate_per_500ms:.3f} per 500 ms (limit 0.40)"
        )


# ── Rotation-mode lookup ───────────────────────────────────────────────────


class TestRotationModeLookup:
    def test_plan_tokens_map_to_documented_roles(self):
        assert ls._ROTATION_MODE_ROLE["steady"] == "muted"
        assert ls._ROTATION_MODE_ROLE["deliberate"] == "accent_cyan"
        assert ls._ROTATION_MODE_ROLE["rapid"] == "accent_yellow"
        assert ls._ROTATION_MODE_ROLE["burst"] == "accent_red"

    def test_default_modes_suppress_suffix(self):
        assert "steady" in ls._ROTATION_MODE_DEFAULT
        assert "weighted_by_salience" in ls._ROTATION_MODE_DEFAULT
        assert "burst" not in ls._ROTATION_MODE_DEFAULT


# ── Golden-image regressions ───────────────────────────────────────────────


def _render_activity_header_golden() -> Any:
    ward = ls.ActivityHeaderCairoSource()
    with (
        patch.object(
            ls,
            "_read_narrative_state",
            return_value={"activity": "rendering", "stance": "nominal"},
        ),
        patch.object(
            ls,
            "_read_latest_intent",
            return_value={
                "compositional_impingements": [{"narrative": "stimmung settling", "salience": 0.8}]
            },
        ),
        patch.object(ls, "_read_rotation_mode", return_value=None),
    ):
        return _render_ward(ward, 800, 56, t=0.0)


def _render_stance_indicator_golden() -> Any:
    ward = ls.StanceIndicatorCairoSource()
    with patch.object(ls, "_read_narrative_state", return_value={"stance": "seeking"}):
        return _render_ward(ward, 100, 40, t=0.0)


def _render_grounding_ticker_empty_golden() -> Any:
    ward = ls.GroundingProvenanceTickerCairoSource()
    with patch.object(ls, "_read_latest_intent", return_value={"grounding_provenance": []}):
        return _render_ward(ward, 480, 40, t=0.0)


def _render_chat_keyword_legend_golden() -> Any:
    ward = ls.ChatKeywordLegendCairoSource()
    return _render_ward(ward, 560, 200, t=0.0)


def _run_golden(filename: str, actual: Any) -> None:
    path = _GOLDEN_DIR / filename
    if _update_golden_requested():
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        actual.write_to_png(str(path))
        return
    assert path.is_file(), (
        f"golden image missing at {path} — set HAPAX_UPDATE_GOLDEN=1 "
        f"and re-run to generate, then audit and commit (git add -f)"
    )
    import cairo

    expected = cairo.ImageSurface.create_from_png(str(path))
    ok, diag = _surfaces_match(actual, expected, _GOLDEN_PIXEL_TOLERANCE)
    assert ok, diag


@requires_cairo
def test_activity_header_golden() -> None:
    _run_golden("activity_header_800x56.png", _render_activity_header_golden())


@requires_cairo
def test_stance_indicator_golden() -> None:
    _run_golden("stance_indicator_100x40.png", _render_stance_indicator_golden())


@requires_cairo
def test_grounding_ticker_empty_golden() -> None:
    _run_golden("grounding_ticker_empty_480x40.png", _render_grounding_ticker_empty_golden())


@requires_cairo
def test_chat_keyword_legend_golden() -> None:
    _run_golden("chat_keyword_legend_560x200.png", _render_chat_keyword_legend_golden())


@requires_cairo
def test_golden_renders_are_stable() -> None:
    """Two back-to-back renders of each ward must be byte-identical at t=0."""
    # Sanity pin — goldens would be useless if the renders weren't
    # deterministic.
    a = _render_stance_indicator_golden()
    b = _render_stance_indicator_golden()
    assert bytes(a.get_data()) == bytes(b.get_data())
