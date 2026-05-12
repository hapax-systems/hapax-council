"""Phase 3 render-path flip tests — blit_scaled + pip_draw_from_layout.

Parent plan E15 / E16. These tests pin the render contract:

1. ``blit_scaled`` translates + scales a natural-size source to the
   target surface geometry, honoring opacity and blend mode.
2. ``pip_draw_from_layout`` walks ``LayoutState`` in z_order, pulls
   each assignment's source from the registry, and blits it — skipping
   non-rect surfaces (those go through the glvideomixer appsrc path)
   and skipping sources that have no current surface yet.

The render path MUST NOT fall back to the legacy
``compositor._token_pole.draw(cr)`` path when a source is missing —
that is Phase 9 cleanup territory.
"""

from __future__ import annotations

import json

import cairo

from agents.studio_compositor import fx_chain
from agents.studio_compositor.fx_chain import (
    blit_scaled,
    clear_blit_readbacks,
    pip_draw_from_layout,
    recent_blit_readbacks,
)
from agents.studio_compositor.layout_state import LayoutState
from agents.studio_compositor.source_registry import SourceRegistry
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


def _solid_surface(w: int, h: int, rgb: tuple[float, float, float]) -> cairo.ImageSurface:
    """Build a single-colour cairo surface at ``w × h``."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 1.0)
    cr.paint()
    return surface


def _pixel(surface: cairo.ImageSurface, x: int, y: int) -> tuple[int, int, int, int]:
    """Return (R, G, B, A) of the pixel at ``(x, y)``.

    Cairo ``FORMAT_ARGB32`` on little-endian is laid out as BGRA in
    memory. The accessor returns the logical RGBA tuple.
    """
    data = surface.get_data()
    stride = surface.get_stride()
    off = y * stride + x * 4
    return data[off + 2], data[off + 1], data[off + 0], data[off + 3]


def _paint_black(canvas: cairo.ImageSurface) -> cairo.Context:
    cr = cairo.Context(canvas)
    cr.set_source_rgba(0, 0, 0, 1)
    cr.paint()
    return cr


class _CannedBackend:
    """Minimum SourceBackend protocol stub — returns a pre-made surface."""

    def __init__(self, surface: cairo.ImageSurface | None) -> None:
        self._surface = surface

    def get_current_surface(self) -> cairo.ImageSurface | None:
        return self._surface


# ── blit_scaled ─────────────────────────────────────────────────────


def test_blit_scaled_places_source_at_geometry() -> None:
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
    cr = _paint_black(canvas)

    src = _solid_surface(10, 10, (1.0, 0.0, 0.0))
    geom = SurfaceGeometry(kind="rect", x=50, y=30, w=40, h=20)
    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over")
    canvas.flush()

    # Inside the target rect — red.
    assert _pixel(canvas, 60, 40)[:3] == (0xFF, 0x00, 0x00)
    # Outside the target rect — black.
    assert _pixel(canvas, 10, 10)[:3] == (0x00, 0x00, 0x00)


def test_blit_scaled_skips_non_rect_geometry() -> None:
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    cr = _paint_black(canvas)
    src = _solid_surface(10, 10, (1.0, 1.0, 1.0))
    geom = SurfaceGeometry(kind="fx_chain_input")
    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over")
    canvas.flush()
    # Non-rect geometry is a no-op — canvas remains black.
    assert _pixel(canvas, 50, 50)[:3] == (0x00, 0x00, 0x00)


def test_blit_scaled_honors_opacity() -> None:
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    cr = _paint_black(canvas)
    src = _solid_surface(10, 10, (1.0, 1.0, 1.0))
    geom = SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100)
    blit_scaled(cr, src, geom, opacity=0.5, blend_mode="over")
    canvas.flush()
    r, g, b, _ = _pixel(canvas, 50, 50)
    # 50% white over black → mid-grey (allow ±2 for rounding).
    assert 126 <= r <= 130
    assert 126 <= g <= 130
    assert 126 <= b <= 130


def test_layout_composite_interval_reuses_cache_across_signature_change(monkeypatch) -> None:
    fx_chain.clear_layout_composite_cache()
    cached = _solid_surface(20, 20, (1.0, 0.0, 0.0))
    monkeypatch.setattr(fx_chain.time, "monotonic", lambda: 100.0)
    fx_chain._store_layout_composite("post_fx", ("old",), cached)

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 20, 20)
    cr = _paint_black(canvas)
    monkeypatch.setattr(fx_chain.time, "monotonic", lambda: 100.05)

    assert fx_chain._paint_cached_layout_composite(
        cr,
        stage="post_fx",
        signature=("new",),
        min_interval_s=0.1,
    )
    canvas.flush()
    assert _pixel(canvas, 10, 10)[:3] == (0xFF, 0x00, 0x00)


def test_layout_composite_interval_expires_before_signature_change(monkeypatch) -> None:
    fx_chain.clear_layout_composite_cache()
    cached = _solid_surface(20, 20, (1.0, 0.0, 0.0))
    monkeypatch.setattr(fx_chain.time, "monotonic", lambda: 100.0)
    fx_chain._store_layout_composite("post_fx", ("old",), cached)

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 20, 20)
    cr = _paint_black(canvas)
    monkeypatch.setattr(fx_chain.time, "monotonic", lambda: 100.2)

    assert not fx_chain._paint_cached_layout_composite(
        cr,
        stage="post_fx",
        signature=("new",),
        min_interval_s=0.1,
    )
    canvas.flush()
    assert _pixel(canvas, 10, 10)[:3] == (0x00, 0x00, 0x00)


def test_scaled_blit_cache_is_byte_bound(monkeypatch) -> None:
    fx_chain.clear_scaled_blit_cache()
    monkeypatch.setenv("HAPAX_SCALE_CACHE_MAX_BYTES", "512")
    monkeypatch.setenv("HAPAX_SCALE_CACHE_MAX_ENTRIES", "8")

    src = _solid_surface(4, 4, (1.0, 0.0, 0.0))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    cr = _paint_black(canvas)
    geom = SurfaceGeometry(kind="rect", x=0, y=0, w=32, h=32)

    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over", cache_key="too-large")

    assert len(fx_chain._SCALE_CACHE) == 0
    assert fx_chain._SCALE_CACHE_BYTES == 0


def test_scaled_blit_cache_evicts_oldest_over_capacity(monkeypatch) -> None:
    fx_chain.clear_scaled_blit_cache()
    monkeypatch.setenv("HAPAX_SCALE_CACHE_MAX_BYTES", "2048")
    monkeypatch.setenv("HAPAX_SCALE_CACHE_MAX_ENTRIES", "8")

    src = _solid_surface(4, 4, (1.0, 0.0, 0.0))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    cr = _paint_black(canvas)
    geom = SurfaceGeometry(kind="rect", x=0, y=0, w=16, h=16)

    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over", cache_key="first")
    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over", cache_key="second")
    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over", cache_key="third")

    assert len(fx_chain._SCALE_CACHE) == 2
    assert fx_chain._SCALE_CACHE_BYTES <= 2048
    assert all(key[0] != "first" for key in fx_chain._SCALE_CACHE)


# ── pip_draw_from_layout ────────────────────────────────────────────


def _layout_with_two_rect_surfaces() -> Layout:
    """Two sources, two overlapping rect surfaces, different z_order."""
    return Layout(
        name="t",
        sources=[
            SourceSchema(
                id="red",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
            SourceSchema(
                id="green",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="low",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50),
                z_order=1,
            ),
            SurfaceSchema(
                id="high",
                geometry=SurfaceGeometry(kind="rect", x=20, y=20, w=50, h=50),
                z_order=5,
            ),
        ],
        assignments=[
            Assignment(source="red", surface="low"),
            Assignment(source="green", surface="high"),
        ],
    )


def test_pip_draw_from_layout_walks_assignments_by_z_order() -> None:
    state = LayoutState(_layout_with_two_rect_surfaces())
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(10, 10, (0.0, 1.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()

    # Overlap point (30, 30) — green (z=5) overlays red (z=1).
    # ``blit_with_depth`` attenuates default-plane opacity by ~4% (depth
    # multiplier ≈ 0.96 for ``on-scrim``); the dominant channel must be
    # green and the suppressed channel red must remain near zero.
    r, g, _b, _a = _pixel(canvas, 30, 30)
    assert g >= 240, f"green channel should dominate, got {g}"
    assert r <= 12, f"red channel should be near zero (z-overlay), got {r}"
    # Red-only point (5, 5) — red (only the low-z surface).
    r, g, _b, _a = _pixel(canvas, 5, 5)
    assert r >= 240
    assert g <= 12
    # Outside both rects (80, 80) — still the black clear.
    assert _pixel(canvas, 80, 80)[:3] == (0x00, 0x00, 0x00)


def test_pip_draw_skips_non_rect_surfaces() -> None:
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="red",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="main",
                geometry=SurfaceGeometry(kind="fx_chain_input"),
                z_order=0,
            ),
        ],
        assignments=[Assignment(source="red", surface="main")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 1.0, 1.0))))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()
    # Non-rect surface (fx_chain_input) is handled by the glvideomixer
    # appsrc path in Phase H — cairooverlay draw callback skips it.
    assert _pixel(canvas, 25, 25)[:3] == (0x00, 0x00, 0x00)


def test_pip_draw_skips_sources_with_none_surface() -> None:
    """Missing-frame sources are skipped without falling back to legacy."""
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="sleepy",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="a",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50),
            ),
        ],
        assignments=[Assignment(source="sleepy", surface="a")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("sleepy", _CannedBackend(None))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()
    # No draw, canvas remains black. No exception raised.
    assert _pixel(canvas, 25, 25)[:3] == (0x00, 0x00, 0x00)


def test_pip_draw_skips_unknown_source_ids() -> None:
    """An assignment whose source isn't in the registry is skipped cleanly."""
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="real",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="a",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50),
            ),
        ],
        assignments=[Assignment(source="real", surface="a")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    # Deliberately do NOT register "real".
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()
    assert _pixel(canvas, 25, 25)[:3] == (0x00, 0x00, 0x00)


# ── FINDING-R diagnostics: per-ward blit metrics ─────────────────────


def test_blit_emits_success_counter_per_ward(monkeypatch) -> None:
    """Each successful blit increments WARD_BLIT_TOTAL{ward=<id>}."""
    increments: list[tuple[str, str]] = []

    class _Counter:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def labels(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(kwargs)
            return self

        def inc(self) -> None:
            kw = self.calls[-1]
            increments.append(("success" if "reason" not in kw else "skip", kw.get("ward", "")))

    fake_total = _Counter()
    fake_skipped = _Counter()
    from agents.studio_compositor import metrics

    monkeypatch.setattr(metrics, "WARD_BLIT_TOTAL", fake_total, raising=False)
    monkeypatch.setattr(metrics, "WARD_BLIT_SKIPPED_TOTAL", fake_skipped, raising=False)

    state = LayoutState(_layout_with_two_rect_surfaces())
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(10, 10, (0.0, 1.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)

    success_wards = sorted(w for kind, w in increments if kind == "success")
    assert success_wards == ["green", "red"]


def test_skip_emits_source_surface_none_reason(monkeypatch) -> None:
    """Source returning None → WARD_BLIT_SKIPPED_TOTAL{reason=source_surface_none}."""
    skip_reasons: list[tuple[str, str]] = []

    class _Counter:
        def labels(self, **kwargs):  # type: ignore[no-untyped-def]
            self._kw = kwargs
            return self

        def inc(self) -> None:
            skip_reasons.append((self._kw.get("ward", ""), self._kw.get("reason", "")))

    from agents.studio_compositor import metrics

    monkeypatch.setattr(metrics, "WARD_BLIT_TOTAL", _Counter(), raising=False)
    monkeypatch.setattr(metrics, "WARD_BLIT_SKIPPED_TOTAL", _Counter(), raising=False)

    layout = Layout(
        name="t",
        sources=[SourceSchema(id="sleepy", kind="cairo", backend="cairo", params={})],
        surfaces=[
            SurfaceSchema(id="a", geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50))
        ],
        assignments=[Assignment(source="sleepy", surface="a")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("sleepy", _CannedBackend(None))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)

    assert ("sleepy", "source_surface_none") in skip_reasons


def test_skip_emits_source_not_registered_reason(monkeypatch) -> None:
    skip_reasons: list[tuple[str, str]] = []

    class _Counter:
        def labels(self, **kwargs):  # type: ignore[no-untyped-def]
            self._kw = kwargs
            return self

        def inc(self) -> None:
            skip_reasons.append((self._kw.get("ward", ""), self._kw.get("reason", "")))

    from agents.studio_compositor import metrics

    monkeypatch.setattr(metrics, "WARD_BLIT_TOTAL", _Counter(), raising=False)
    monkeypatch.setattr(metrics, "WARD_BLIT_SKIPPED_TOTAL", _Counter(), raising=False)

    layout = Layout(
        name="t",
        sources=[SourceSchema(id="real", kind="cairo", backend="cairo", params={})],
        surfaces=[
            SurfaceSchema(id="a", geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50))
        ],
        assignments=[Assignment(source="real", surface="a")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    # Deliberately do NOT register "real".

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)

    assert ("real", "source_not_registered") in skip_reasons


def test_skip_emits_alpha_clamped_to_zero_reason(monkeypatch) -> None:
    """Non-destructive clamp can push opacity to 0 → distinct skip reason."""
    skip_reasons: list[tuple[str, str]] = []

    class _Counter:
        def labels(self, **kwargs):  # type: ignore[no-untyped-def]
            self._kw = kwargs
            return self

        def inc(self) -> None:
            skip_reasons.append((self._kw.get("ward", ""), self._kw.get("reason", "")))

    from agents.studio_compositor import metrics

    monkeypatch.setattr(metrics, "WARD_BLIT_TOTAL", _Counter(), raising=False)
    monkeypatch.setattr(metrics, "WARD_BLIT_SKIPPED_TOTAL", _Counter(), raising=False)

    layout = Layout(
        name="t",
        sources=[SourceSchema(id="muted", kind="cairo", backend="cairo", params={})],
        surfaces=[
            SurfaceSchema(id="a", geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50))
        ],
        assignments=[Assignment(source="muted", surface="a", opacity=0.0)],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("muted", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)

    assert ("muted", "alpha_clamped_to_zero") in skip_reasons


# ── FINDING-W deepening: per-ward source-surface dimensions gauge ────


def test_blit_records_source_surface_pixels(monkeypatch) -> None:
    """Each successful blit calls
    ``WARD_SOURCE_SURFACE_PIXELS.labels(ward=…).set(w*h)`` so the audit
    can distinguish "blitting a 1×1 empty surface" from "blitting real
    content" without inspecting cairo internals from the metric scrape.
    """
    set_calls: list[tuple[str, float]] = []

    class _Gauge:
        def __init__(self) -> None:
            self._kw: dict = {}

        def labels(self, **kwargs):  # type: ignore[no-untyped-def]
            self._kw = kwargs
            return self

        def set(self, value: float) -> None:
            set_calls.append((self._kw.get("ward", ""), float(value)))

    from agents.studio_compositor import metrics

    monkeypatch.setattr(metrics, "WARD_SOURCE_SURFACE_PIXELS", _Gauge(), raising=False)

    state = LayoutState(_layout_with_two_rect_surfaces())
    registry = SourceRegistry()
    # Two distinct surface sizes to confirm we record actual w*h, not a constant.
    registry.register("red", _CannedBackend(_solid_surface(20, 30, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(40, 50, (0.0, 1.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)

    by_ward = dict(set_calls)
    assert by_ward.get("red") == 20 * 30
    assert by_ward.get("green") == 40 * 50


def test_blit_records_recent_readback_for_responsible_layout() -> None:
    clear_blit_readbacks()
    try:
        state = LayoutState(_layout_with_two_rect_surfaces())
        registry = SourceRegistry()
        registry.register("red", _CannedBackend(_solid_surface(20, 30, (1.0, 0.0, 0.0))))
        registry.register("green", _CannedBackend(_solid_surface(40, 50, (0.0, 1.0, 0.0))))

        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
        cr = _paint_black(canvas)
        pip_draw_from_layout(cr, state, registry)

        readbacks = recent_blit_readbacks(("red", "green"), ttl_s=60.0)
        assert readbacks["red"]["source_pixels"] == 20 * 30
        assert readbacks["green"]["source_pixels"] == 40 * 50
        assert readbacks["red"]["effective_alpha"] > 0.0

        observed_at = float(readbacks["red"]["observed_at"])
        assert recent_blit_readbacks(("red",), now=observed_at + 3.0, ttl_s=1.0) == {}
    finally:
        clear_blit_readbacks()


def test_pip_draw_publishes_fresh_active_wards_and_current_layout(monkeypatch, tmp_path) -> None:
    from agents.studio_compositor import active_wards

    with fx_chain._RENDERED_LAYOUT_STATE_LOCK:
        fx_chain._RENDERED_LAYOUT_STAGE_WARDS.clear()
        fx_chain._RENDERED_LAYOUT_STATE_LAST_PUBLISH_MONO = 0.0
        fx_chain._RENDERED_LAYOUT_STATE_LAST_SIGNATURE = None
    active_wards_path = tmp_path / "active_wards.json"
    current_layout_path = tmp_path / "current-layout-state.json"
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", active_wards_path)
    monkeypatch.setattr(active_wards, "CURRENT_LAYOUT_STATE_FILE", current_layout_path)

    state = LayoutState(_layout_with_two_rect_surfaces())
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(20, 30, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(40, 50, (0.0, 1.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)

    assert active_wards.read(path=active_wards_path, stale_s=60.0) == ["green", "red"]
    current_layout = json.loads(current_layout_path.read_text(encoding="utf-8"))
    assert current_layout["layout_name"] == "t"
    assert current_layout["active_ward_ids"] == ["green", "red"]
    assert current_layout["schema_version"] == 1


def test_rendered_layout_empty_readback_falls_back_to_visible_ward_properties(
    monkeypatch, tmp_path
) -> None:
    from agents.studio_compositor import active_wards

    with fx_chain._RENDERED_LAYOUT_STATE_LOCK:
        fx_chain._RENDERED_LAYOUT_STAGE_WARDS.clear()
        fx_chain._RENDERED_LAYOUT_STATE_LAST_PUBLISH_MONO = 0.0
        fx_chain._RENDERED_LAYOUT_STATE_LAST_SIGNATURE = None

    active_wards_path = tmp_path / "active_wards.json"
    current_layout_path = tmp_path / "current-layout-state.json"
    ward_properties_path = tmp_path / "ward-properties.json"
    monkeypatch.setattr(active_wards, "ACTIVE_WARDS_FILE", active_wards_path)
    monkeypatch.setattr(active_wards, "CURRENT_LAYOUT_STATE_FILE", current_layout_path)
    monkeypatch.setattr(active_wards, "WARD_PROPERTIES_FILE", ward_properties_path)
    ward_properties_path.write_text(
        json.dumps(
            {
                "wards": {
                    "album_overlay": {"visible": True},
                    "hidden": {"visible": False},
                    "token_pole": {"alpha": 1.0},
                }
            }
        ),
        encoding="utf-8",
    )

    fx_chain._publish_rendered_layout_state(
        layout_name="segment-detail",
        active_ward_ids=(),
        stage="post_fx",
    )

    assert active_wards.read(path=active_wards_path, stale_s=60.0) == [
        "album_overlay",
        "token_pole",
    ]
    current_layout = json.loads(current_layout_path.read_text(encoding="utf-8"))
    assert current_layout["layout_name"] == "segment-detail"
    assert current_layout["active_ward_ids"] == ["album_overlay", "token_pole"]


def test_blit_observability_does_not_break_on_metric_failure(monkeypatch) -> None:
    """If the metric module raises (e.g. uninitialized state, double-init),
    the render path must NOT raise — observability is fail-open per
    FINDING-R/-W policy."""
    from agents.studio_compositor import fx_chain, metrics

    class _BrokenGauge:
        def labels(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("broken")

    monkeypatch.setattr(metrics, "WARD_SOURCE_SURFACE_PIXELS", _BrokenGauge(), raising=False)

    state = LayoutState(_layout_with_two_rect_surfaces())
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(10, 10, (0.0, 1.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
    cr = _paint_black(canvas)
    # Must not raise — render path is the contract, observability is best-effort.
    fx_chain.pip_draw_from_layout(cr, state, registry)
