"""Per-ward shader-domination contrast tests (lssh-005).

The 2026-04-21 per-ward opacity audit flagged ``stance_indicator``
(~4 k px²) and ``thinking_indicator`` (~7.5 k px²) as the highest-risk
small wards for halftone / chromatic shader domination. PR #1167
promoted them to surface-scrim but the operator's audit noted
effective opacity still ~0.6–0.8 against bright presets. This module
extends the lssh-001 luminance harness with WCAG contrast measurement:
each ward must read against a worst-case bright background at
≥ 3.0 : 1 (WCAG-AA UI threshold).

A failing test here means the mitigation phase of lssh-005 (outline-
contrast bump, non-destructive flag audit, geometric size bump) needs
to fire. The test is the diagnostic — its failure message names the
ward, the background, the measured ratio, and the threshold it missed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    import cairo  # noqa: F401

    _CAIRO = True
except ImportError:
    _CAIRO = False

from tests.studio_compositor.blink_harness import (
    DEFAULT_MIN_CONTRAST_RATIO,
    audit_ward_against_background,
    synthetic_bright_background,
)

requires_cairo = pytest.mark.skipif(not _CAIRO, reason="cairo not installed")


def _render_factory(ward, w: int, h: int):
    """Return a ``render_fn(t)`` that renders the ward into a fresh
    ARGB32 surface at time ``t``."""

    def _render(t: float):
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        ward.render_content(cr, w, h, t, {})
        surface.flush()
        return surface

    return _render


# ── stance_indicator ──────────────────────────────────────────────────────


@requires_cairo
def test_stance_indicator_contrast_against_bright_shader() -> None:
    """stance_indicator must remain readable against a worst-case bright
    halftone-like background (synthetic 0.85 luminance field)."""
    from agents.studio_compositor import legibility_sources as ls

    ward = ls.StanceIndicatorCairoSource()
    with (
        patch.object(ls, "_read_narrative_state", return_value={"stance": "nominal"}),
        patch.object(ls, "_read_rotation_mode", return_value=None),
    ):
        result = audit_ward_against_background(
            ward_name="stance_indicator",
            render_fn=_render_factory(ward, 320, 56),
            background_factory=synthetic_bright_background,
            width=320,
            height=56,
            sample_at=1.0,
        )
    assert result.passes, result.diagnostic()


# ── thinking_indicator ────────────────────────────────────────────────────


@requires_cairo
def test_thinking_indicator_contrast_against_bright_shader() -> None:
    """thinking_indicator at the 0.3 Hz idle breath must remain readable
    against a worst-case bright background."""
    from agents.studio_compositor.hothouse_sources import ThinkingIndicatorCairoSource

    ward = ThinkingIndicatorCairoSource()
    result = audit_ward_against_background(
        ward_name="thinking_indicator",
        render_fn=_render_factory(ward, 100, 40),
        background_factory=synthetic_bright_background,
        width=100,
        height=40,
        sample_at=2.0,
    )
    assert result.passes, result.diagnostic()


# ── threshold contract ───────────────────────────────────────────────────


def test_default_contrast_threshold_matches_wcag_aa_ui() -> None:
    """The default 3.0 : 1 threshold corresponds to WCAG 2.1 §1.4.3
    'large text + UI components.' Bumping requires explicit operator
    sign-off — wards readable below this read poorly against bright
    shaders, which is the operator's audit surface."""
    assert DEFAULT_MIN_CONTRAST_RATIO == 3.0
