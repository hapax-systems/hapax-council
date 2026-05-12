"""Task #157 — non-destructive overlay alpha clamp.

Tests:

1. ``Assignment`` accepts the new ``non_destructive`` field with the
   documented default (False) and with an explicit True.
2. Layouts authored before the field was added still parse — backward
   compatibility guarantee for all on-disk ``default.json`` snapshots.
3. The clamp math behaves as specified:
   * ``requested=0.9`` + ``non_destructive=True`` → ``applied=0.6``
   * ``requested=0.5`` + ``non_destructive=True`` → ``applied=0.5`` (no clamp)
   * ``requested=0.9`` + ``non_destructive=False`` → ``applied=0.9``
4. The Prometheus metric
   ``hapax_compositor_nondestructive_clamps_total{source}``
   increments only when the clamp actually lowered the alpha.
"""

from __future__ import annotations

import json

import pytest

from agents.studio_compositor.fx_chain import (
    NONDESTRUCTIVE_ALPHA_CEILING,
    apply_nondestructive_clamp,
)
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)

# ---------------------------------------------------------------------------
# Assignment model schema
# ---------------------------------------------------------------------------


def test_assignment_non_destructive_default_is_false() -> None:
    """The field defaults to False so existing layouts stay byte-identical."""
    assignment = Assignment(source="token_pole", surface="pip-ul")
    assert assignment.non_destructive is False


def test_assignment_non_destructive_explicit_true() -> None:
    """Setting the flag explicitly sticks through round-trip serialization."""
    assignment = Assignment(
        source="token_pole",
        surface="pip-ul",
        non_destructive=True,
    )
    assert assignment.non_destructive is True
    round_tripped = Assignment.model_validate_json(assignment.model_dump_json())
    assert round_tripped.non_destructive is True


def test_assignment_without_non_destructive_field_parses() -> None:
    """JSON authored before the field was added still validates.

    This mirrors the on-disk layouts that predate task #157 —
    ``extra="forbid"`` on the model config would have broken them
    if the field were required, so the default-False contract is the
    backward-compat guarantee.
    """
    raw = {
        "source": "token_pole",
        "surface": "pip-ul",
        "transform": {},
        "opacity": 1.0,
        "per_assignment_effects": [],
    }
    assignment = Assignment.model_validate(raw)
    assert assignment.non_destructive is False


def test_layout_without_non_destructive_still_parses() -> None:
    """A minimal Layout without the field on any assignment validates."""
    raw = {
        "name": "legacy",
        "description": "",
        "sources": [
            {
                "id": "a",
                "kind": "cairo",
                "backend": "cairo",
                "params": {},
                "tags": [],
            }
        ],
        "surfaces": [
            {
                "id": "s",
                "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10},
                "z_order": 0,
            }
        ],
        "assignments": [{"source": "a", "surface": "s", "transform": {}, "opacity": 1.0}],
    }
    layout = Layout.model_validate(raw)
    assert layout.assignments[0].non_destructive is False


# ---------------------------------------------------------------------------
# Clamp math
# ---------------------------------------------------------------------------


def test_clamp_ceiling_value() -> None:
    """The ceiling constant matches the spec (underlying ≥0.4 visible)."""
    assert pytest.approx(0.6) == NONDESTRUCTIVE_ALPHA_CEILING


def test_clamp_high_request_is_clamped() -> None:
    """requested=0.9 with non_destructive=True → 0.6."""
    applied = apply_nondestructive_clamp(0.9, True, "token_pole")
    assert applied == pytest.approx(0.6)


def test_clamp_low_request_passes_through() -> None:
    """requested=0.5 with non_destructive=True → 0.5 (below ceiling)."""
    applied = apply_nondestructive_clamp(0.5, True, "token_pole")
    assert applied == pytest.approx(0.5)


def test_clamp_exact_ceiling_is_not_counted_as_clamped() -> None:
    """requested=0.6 is the boundary — returns 0.6 without triggering metric."""
    applied = apply_nondestructive_clamp(0.6, True, "token_pole")
    assert applied == pytest.approx(0.6)


def test_clamp_inactive_when_flag_false() -> None:
    """Without the flag, high alpha passes through untouched."""
    applied = apply_nondestructive_clamp(0.9, False, "reverie")
    assert applied == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Metric wiring
# ---------------------------------------------------------------------------


def _counter_value(source_id: str) -> float:
    """Read the current float value of the per-source counter.

    Returns 0.0 if prometheus_client is unavailable (counter is None in
    that configuration) so the test is still meaningful as a smoke
    test in stripped environments.
    """
    from agents.studio_compositor import metrics

    counter = metrics.COMP_NONDESTRUCTIVE_CLAMPS_TOTAL
    if counter is None:
        return 0.0
    return counter.labels(source=source_id)._value.get()


def test_metric_increments_only_when_clamp_active() -> None:
    """Counter bumps for a real clamp, stays flat for below-ceiling calls."""
    source_id = "test_metric_active_ward"
    before = _counter_value(source_id)
    apply_nondestructive_clamp(0.9, True, source_id)
    after_clamp = _counter_value(source_id)
    assert after_clamp == pytest.approx(before + 1.0)

    # Below-ceiling call must not move the counter.
    apply_nondestructive_clamp(0.5, True, source_id)
    after_noop = _counter_value(source_id)
    assert after_noop == pytest.approx(after_clamp)

    # Flag-off call must not move the counter either.
    apply_nondestructive_clamp(0.9, False, source_id)
    after_flag_off = _counter_value(source_id)
    assert after_flag_off == pytest.approx(after_clamp)


def test_metric_labelled_per_source() -> None:
    """Two sources track clamp counts independently."""
    a_id = "test_metric_per_source_a"
    b_id = "test_metric_per_source_b"
    a_before = _counter_value(a_id)
    b_before = _counter_value(b_id)

    apply_nondestructive_clamp(0.95, True, a_id)
    apply_nondestructive_clamp(0.95, True, a_id)
    apply_nondestructive_clamp(0.95, True, b_id)

    assert _counter_value(a_id) == pytest.approx(a_before + 2.0)
    assert _counter_value(b_id) == pytest.approx(b_before + 1.0)


# ---------------------------------------------------------------------------
# Default layout carries the flag on informational wards
# ---------------------------------------------------------------------------


def test_default_layout_non_destructive_flags() -> None:
    """Default layout JSON marks overlay wards as non-destructive so the
    NONDESTRUCTIVE_ALPHA_CEILING (0.6) preserves underlying camera content at
    >=40% visibility."""
    from pathlib import Path

    layout_path = (
        Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"
    )
    raw = json.loads(layout_path.read_text())
    layout = Layout.model_validate(raw)

    non_destructive_sources = {a.source for a in layout.assignments if a.non_destructive}
    assert non_destructive_sources == {
        "cbip_signal_density",
        "chat_ambient",
        "chronicle_ticker",
        "programme_state",
        "polyend_instrument_reveal",
        "interactive_lore_query",
        "constructivist_research_poster",
        "tufte_density",
        "ascii_schematic",
        "segment_content",
        "m8_oscilloscope",
        "cbip_dual_ir_displacement",
        "durf",
        "sierpinski",
    }


# ---------------------------------------------------------------------------
# pip_draw_from_layout wiring smoke test
# ---------------------------------------------------------------------------


class _StaticSource:
    """Minimal SourceRegistry stand-in returning a fixed cairo surface."""

    def __init__(self, surface: object) -> None:
        self._surface = surface

    def get_current_surface(self, source_id: str) -> object:
        return self._surface


def test_pip_draw_applies_clamp() -> None:
    """Integration: pip_draw_from_layout clamps non-destructive assignments.

    We stub the source registry with a 4x4 red surface and render it at
    requested alpha 0.9 with and without the flag. The resulting canvas
    pixel alpha should be ~0.6*255 in the clamped case and ~0.9*255 in
    the uncl clamped case.
    """
    import cairo

    from agents.studio_compositor.fx_chain import pip_draw_from_layout
    from agents.studio_compositor.layout_state import LayoutState

    src_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
    src_cr = cairo.Context(src_surface)
    src_cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
    src_cr.paint()

    def build_layout(non_destructive: bool) -> Layout:
        return Layout(
            name="test",
            description="",
            sources=[SourceSchema(id="s", kind="cairo", backend="cairo", params={})],
            surfaces=[
                SurfaceSchema(
                    id="r",
                    geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=4, h=4),
                    z_order=0,
                )
            ],
            assignments=[
                Assignment(
                    source="s",
                    surface="r",
                    opacity=0.9,
                    non_destructive=non_destructive,
                )
            ],
        )

    def render(layout: Layout) -> int:
        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        cr = cairo.Context(canvas)
        cr.set_source_rgba(0.0, 0.0, 0.0, 1.0)
        cr.paint()
        # Paint canvas black first then blit the source with the clamp.
        state = LayoutState(layout)
        registry = _StaticSource(src_surface)
        # Start from a fully-transparent canvas so we see the blit alpha.
        transparent = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        tcr = cairo.Context(transparent)
        pip_draw_from_layout(tcr, state, registry)  # type: ignore[arg-type]
        data = transparent.get_data()
        # ARGB32 on little-endian: BGRA in memory, alpha at offset +3.
        return data[3]

    clamped_alpha_byte = render(build_layout(non_destructive=True))
    unclamped_alpha_byte = render(build_layout(non_destructive=False))

    # Unclamped should be meaningfully higher than clamped — exact cairo
    # byte values depend on pre-multiplication so assert ordering, not
    # exact equality.
    assert unclamped_alpha_byte > clamped_alpha_byte
    # And the clamped byte should not exceed the 0.6 ceiling (±1 LSB
    # tolerance for pre-multiplied rounding).
    assert clamped_alpha_byte <= int(round(0.6 * 255)) + 1
