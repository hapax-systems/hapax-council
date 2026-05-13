"""GEM substrate tests (Candidate C Phase 1).

The "text wins" operator decision (2026-04-22) requires that under no
condition does the substrate paint brighter than the text layer. These
tests pin that invariant plus the basic Gray-Scott stepping behavior.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from agents.studio_compositor.gem_substrate import (
    DEFAULT_GRID_H,
    DEFAULT_GRID_W,
    SUBSTRATE_BRIGHTNESS_CEILING,
    GemSubstrate,
    is_within_text_priority,
)


def test_default_dimensions_match_canvas_aspect() -> None:
    """Default 230×30 grid upscales evenly into the 1840×240 GEM canvas."""
    s = GemSubstrate()
    assert s.grid_w == DEFAULT_GRID_W == 230
    assert s.grid_h == DEFAULT_GRID_H == 30
    # Each cell maps to an 8×8 block in the rendered canvas.
    assert 1840 // s.grid_w == 8
    assert 240 // s.grid_h == 8


def test_substrate_max_brightness_never_exceeds_ceiling() -> None:
    """Even after long evolution, brightness stays below the ceiling.

    Text alpha is 0.95+; substrate ceiling is 0.35. The clamp is the
    only thing that enforces "text wins" at the pixel level — verify
    it cannot be defeated by transient growth phases.
    """
    s = GemSubstrate()
    # Evolve well past the seed-spread phase so the field is populated.
    for _ in range(50):
        s.step()
    assert s.max_brightness() <= s.ceiling
    assert s.max_brightness() <= SUBSTRATE_BRIGHTNESS_CEILING


def test_text_priority_invariant_holds_against_text_alpha() -> None:
    """The is_within_text_priority predicate gates substrate vs. text."""
    s = GemSubstrate()
    for _ in range(100):
        s.step()
    # Text default alpha in gem_source is 1.0 for content_colour, 0.95 for
    # the lower outline path. Both must beat the substrate.
    assert is_within_text_priority(s.max_brightness(), text_alpha=1.0)
    assert is_within_text_priority(s.max_brightness(), text_alpha=0.95)


def test_brightness_array_shape_matches_grid() -> None:
    s = GemSubstrate(grid_w=64, grid_h=16)
    bright = s.brightness_array()
    assert bright.shape == (16, 64)
    assert bright.dtype == np.float32


def test_substrate_evolves_over_time() -> None:
    """The Gray-Scott step changes the field — a non-trivial check that
    the kernel is actually integrating, not stuck."""
    s = GemSubstrate()
    # Capture early state, evolve, compare. The seeded patch will spread
    # so the L2-norm of V should grow during the initial evolution.
    initial_v_norm = float(np.linalg.norm(s.brightness_array()))
    for _ in range(20):
        s.step()
    later_v_norm = float(np.linalg.norm(s.brightness_array()))
    assert later_v_norm != initial_v_norm, "substrate did not evolve"


def test_lower_ceiling_is_honored() -> None:
    """Operator can tune the ceiling; brightness clamps to whatever they pick."""
    s = GemSubstrate(ceiling=0.10)
    for _ in range(50):
        s.step()
    assert s.max_brightness() <= 0.10


def test_invalid_ceiling_rejected() -> None:
    with pytest.raises(ValueError):
        GemSubstrate(ceiling=-0.1)
    with pytest.raises(ValueError):
        GemSubstrate(ceiling=1.5)


def test_invalid_grid_rejected() -> None:
    with pytest.raises(ValueError):
        GemSubstrate(grid_w=0, grid_h=10)
    with pytest.raises(ValueError):
        GemSubstrate(grid_w=10, grid_h=-1)


def test_invalid_ticks_per_render_rejected() -> None:
    with pytest.raises(ValueError):
        GemSubstrate(ticks_per_render=0)


def test_substrate_disable_in_gem_source() -> None:
    """When ``enable_substrate=False`` the source path silently skips the
    background paint. v1 text-only behavior is preserved exactly."""
    from agents.studio_compositor.gem_source import GemCairoSource

    src = GemCairoSource(enable_substrate=False)
    assert src._enable_substrate is False
    # Substrate not yet constructed (lazy)
    assert src._substrate is None
    # Nothing to attempt; ensure helper returns None without raising
    result = src._ensure_substrate()
    assert result is None


def test_substrate_enabled_by_default_in_gem_source() -> None:
    """Default constructor enables the substrate (Candidate C Phase 1)."""
    from agents.studio_compositor.gem_source import GemCairoSource

    src = GemCairoSource()
    assert src._enable_substrate is True


def test_gem_source_emits_substrate_paint_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """The live proof path must observe substrate construction and paint."""
    from agents.studio_compositor import metrics
    from agents.studio_compositor.gem_source import GemCairoSource

    src = GemCairoSource()
    monkeypatch.setattr(src, "_paint_substrate_grid", lambda *args, **kwargs: None)
    metrics.set_gem_substrate_active(False)
    before = metrics.GEM_SUBSTRATE_PAINT_TOTAL._value.get()

    src._render_substrate(object(), 1840, 240)

    assert metrics.GEM_SUBSTRATE_ACTIVE._value.get() == 1.0
    assert metrics.GEM_SUBSTRATE_PAINT_TOTAL._value.get() == before + 1.0
    assert 0.0 <= metrics.GEM_SUBSTRATE_MAX_BRIGHTNESS._value.get() <= src._substrate.ceiling


def test_gem_source_emits_substrate_error_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paint failures are scrape-visible instead of silently weakening proof."""
    from agents.studio_compositor import metrics
    from agents.studio_compositor.gem_source import GemCairoSource

    src = GemCairoSource()

    def _fail_paint(*args, **kwargs) -> None:
        raise RuntimeError("forced paint failure")

    monkeypatch.setattr(src, "_paint_substrate_grid", _fail_paint)
    before = metrics.GEM_SUBSTRATE_STEP_ERRORS_TOTAL._value.get()

    src._render_substrate(object(), 1840, 240)

    assert metrics.GEM_SUBSTRATE_ACTIVE._value.get() == 0.0
    assert metrics.GEM_SUBSTRATE_STEP_ERRORS_TOTAL._value.get() == before + 1.0
