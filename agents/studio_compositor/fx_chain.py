"""Inline GPU effects chain and per-frame tick callback."""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import TYPE_CHECKING, Any, Literal

import cairo

from agents.studio_compositor.z_plane_constants import (
    _Z_INDEX_BASE,
    DEFAULT_Z_INDEX_FLOAT,
    DEFAULT_Z_PLANE,
)
from shared.compositor_model import SurfaceGeometry

if TYPE_CHECKING:
    from agents.studio_compositor.layout_state import LayoutState
    from agents.studio_compositor.source_registry import SourceRegistry

log = logging.getLogger(__name__)


# Task #157 — non-destructive overlay ceiling. When an assignment sets
# ``non_destructive=True`` the rendered alpha is clamped below this
# value so that the underlying camera content retains at least
# ``1.0 - NONDESTRUCTIVE_ALPHA_CEILING`` visibility. 0.6 chosen so the
# operator-facing video remains ≥0.4 visible under any informational ward.
NONDESTRUCTIVE_ALPHA_CEILING: float = 0.6
DEFAULT_BLIT_READBACK_TTL_S: float = 2.0
DEFAULT_FX_SLOT_COUNT: int = 12
MAX_FX_SLOT_COUNT: int = 24
_BLIT_READBACK_LOCK = threading.Lock()
_BLIT_READBACKS: dict[str, dict[str, object]] = {}
_SCALE_CACHE_LOCK = threading.Lock()
_SCALE_CACHE: dict[tuple[object, ...], cairo.ImageSurface] = {}
_LAYOUT_COMPOSITE_CACHE_LOCK = threading.Lock()
_LAYOUT_COMPOSITE_CACHE: dict[str, dict[str, object]] = {}
RENDERED_LAYOUT_STATE_PUBLISH_INTERVAL_S: float = 1.0
RENDERED_LAYOUT_STAGE_TTL_S: float = 2.0
_RENDERED_LAYOUT_STATE_LOCK = threading.Lock()
_RENDERED_LAYOUT_STAGE_WARDS: dict[str, tuple[float, tuple[str, ...]]] = {}
_RENDERED_LAYOUT_STATE_LAST_PUBLISH_MONO: float = 0.0
_RENDERED_LAYOUT_STATE_LAST_SIGNATURE: tuple[str | None, tuple[str, ...]] | None = None


def clear_blit_readbacks() -> None:
    """Clear in-process ward blit readbacks. Used by focused tests."""
    with _BLIT_READBACK_LOCK:
        _BLIT_READBACKS.clear()


def clear_scaled_blit_cache() -> None:
    """Clear scaled ward surface cache. Used by tests and incident rollback."""
    with _SCALE_CACHE_LOCK:
        _SCALE_CACHE.clear()


def clear_layout_composite_cache() -> None:
    """Clear full-canvas layout composite cache. Used by tests and incident rollback."""
    with _LAYOUT_COMPOSITE_CACHE_LOCK:
        _LAYOUT_COMPOSITE_CACHE.clear()


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _fx_slot_count_from_env() -> int:
    raw = os.environ.get("HAPAX_COMPOSITOR_FX_SLOTS")
    if raw is None:
        return DEFAULT_FX_SLOT_COUNT
    try:
        requested = int(raw)
    except ValueError:
        log.warning("Invalid HAPAX_COMPOSITOR_FX_SLOTS=%r; using %d", raw, DEFAULT_FX_SLOT_COUNT)
        return DEFAULT_FX_SLOT_COUNT
    clamped = max(1, min(MAX_FX_SLOT_COUNT, requested))
    if clamped != requested:
        log.warning(
            "Clamped HAPAX_COMPOSITOR_FX_SLOTS=%d to supported range 1..%d",
            requested,
            MAX_FX_SLOT_COUNT,
        )
    return clamped


def _shader_fx_disabled() -> bool:
    return _env_enabled("HAPAX_COMPOSITOR_DISABLE_SHADER_FX", default=False)


def _overlay_only_output_convert_enabled() -> bool:
    return _env_enabled("HAPAX_OVERLAY_ONLY_OUTPUT_CONVERT", default=False)


def _post_fx_overlay_disabled() -> bool:
    return _env_enabled("HAPAX_COMPOSITOR_DISABLE_POST_FX_OVERLAY", default=False)


def _hero_small_overlay_enabled() -> bool:
    return _env_enabled("HAPAX_HERO_SMALL_OVERLAY_ENABLED", default=True)


def _hero_small_overlay_stage() -> Literal["pre_fx", "post_fx"]:
    raw = os.environ.get("HAPAX_HERO_SMALL_RENDER_STAGE", "post_fx").strip().lower()
    return "pre_fx" if raw == "pre_fx" else "post_fx"


def _visual_pumping_enabled() -> bool:
    return _env_enabled("HAPAX_VISUAL_PUMPING_ENABLED", default=True)


def _pre_fx_background_composite_enabled() -> bool:
    return _env_enabled("HAPAX_PRE_FX_LAYOUT_BACKGROUND_COMPOSITE_ENABLED", default=True)


def _post_fx_background_composite_enabled() -> bool:
    return _env_enabled("HAPAX_POST_FX_LAYOUT_BACKGROUND_COMPOSITE_ENABLED", default=True)


def _layout_composite_cache_enabled(stage: Literal["pre_fx", "post_fx"] | None) -> bool:
    if stage == "pre_fx":
        return _env_enabled("HAPAX_PRE_FX_LAYOUT_COMPOSITE_CACHE_ENABLED", default=True)
    if stage == "post_fx":
        return _env_enabled("HAPAX_POST_FX_LAYOUT_COMPOSITE_CACHE_ENABLED", default=True)
    return False


def _layout_composite_interval_s(stage: Literal["pre_fx", "post_fx"] | None) -> float:
    env_name = (
        "HAPAX_PRE_FX_LAYOUT_COMPOSITE_HZ"
        if stage == "pre_fx"
        else "HAPAX_POST_FX_LAYOUT_COMPOSITE_HZ"
    )
    raw = os.environ.get(env_name)
    if raw is None:
        return 0.0
    try:
        hz = float(raw)
    except ValueError:
        log.warning("Invalid %s=%r; disabling interval throttle", env_name, raw)
        return 0.0
    if hz <= 0.0:
        return 0.0
    return 1.0 / hz


def _publish_fx_runtime_feature(feature: str, active: bool) -> None:
    try:
        from . import metrics

        metrics.set_runtime_feature_active(feature, active)
    except Exception:
        log.debug("runtime feature metric publish failed for %s", feature, exc_info=True)


def recent_blit_readbacks(
    ward_ids: Any,
    *,
    now: float | None = None,
    ttl_s: float = DEFAULT_BLIT_READBACK_TTL_S,
) -> dict[str, dict[str, object]]:
    """Return fresh final-frame blit evidence for the requested wards."""
    ts = time.time() if now is None else now
    requested = {str(ward_id) for ward_id in ward_ids if isinstance(ward_id, str)}
    with _BLIT_READBACK_LOCK:
        return {
            ward_id: dict(readback)
            for ward_id, readback in _BLIT_READBACKS.items()
            if ward_id in requested
            and isinstance(readback.get("observed_at"), int | float)
            and ts - float(readback["observed_at"]) <= ttl_s
        }


def apply_nondestructive_clamp(
    requested_alpha: float,
    non_destructive: bool,
    source_id: str,
) -> float:
    """Clamp ``requested_alpha`` for a non-destructive assignment.

    Returns ``min(requested_alpha, NONDESTRUCTIVE_ALPHA_CEILING)`` when
    ``non_destructive`` is True, otherwise ``requested_alpha`` unchanged.
    When the clamp actually lowers the alpha, increments
    ``metrics.COMP_NONDESTRUCTIVE_CLAMPS_TOTAL`` labelled with
    ``source=source_id`` so Grafana can attribute defence events per
    ward. Metric emission is best-effort; any import or label failure
    is swallowed so the hot render path never raises for observability.
    """
    if not non_destructive:
        return requested_alpha
    if requested_alpha <= NONDESTRUCTIVE_ALPHA_CEILING:
        return requested_alpha
    try:
        from . import metrics as _metrics

        counter = _metrics.COMP_NONDESTRUCTIVE_CLAMPS_TOTAL
        if counter is not None:
            counter.labels(source=source_id).inc()
    except Exception:
        log.debug("nondestructive-clamp metric emit failed", exc_info=True)
    return NONDESTRUCTIVE_ALPHA_CEILING


_CONTRAST_FLOOR_SKIP = frozenset(
    {
        "gem",
        "reverie",
        "sierpinski",
        "durf",
        "album",
        "token_pole",
        "m8-display",
        "steamdeck-display",
        "overlay-zones",
    }
)
CONTRAST_FLOOR_ALPHA = 0.45
_GOVERNANCE_CONTRAST_SOURCES = frozenset(
    {
        "egress_footer",
        "precedent_ticker",
        "grounding_provenance_ticker",
        "activity_header",
        "stance_indicator",
        "thinking_indicator",
        "programme_banner",
        "programme_state",
        "chronicle_ticker",
    }
)
GOVERNANCE_CONTRAST_FLOOR_ALPHA = 0.70


def _paint_contrast_floor(cr: cairo.Context, geom: SurfaceGeometry, alpha: float) -> None:
    if geom.kind != "rect" or alpha <= 0.0:
        return
    cr.save()
    cr.set_source_rgba(0.02, 0.02, 0.02, alpha)
    cr.rectangle(geom.x or 0, geom.y or 0, geom.w or 0, geom.h or 0)
    cr.fill()
    cr.restore()


def blit_scaled(
    cr: cairo.Context,
    src: cairo.ImageSurface,
    geom: SurfaceGeometry,
    opacity: float,
    blend_mode: str,
    *,
    cache_key: object | None = None,
    content_token: object | None = None,
) -> None:
    """Place a natural-size source surface at ``geom``'s rect with scaling.

    Matches the scale-on-blit design from Phase E of the source-registry
    spec: each source renders once at its natural resolution on its own
    render thread, and the GStreamer cairooverlay draw callback scales
    on blit to the assigned surface geometry. Non-rect surfaces (main-
    layer ``fx_chain_input`` pads, ``wgpu_binding``, ``video_out``) are
    silently skipped — those are handled by the glvideomixer appsrc
    path, not the cairooverlay path.
    """
    if geom.kind != "rect":
        return
    cr.save()
    cr.translate(geom.x or 0, geom.y or 0)
    src_w = max(src.get_width(), 1)
    src_h = max(src.get_height(), 1)
    sx = (geom.w or src_w) / src_w
    sy = (geom.h or src_h) / src_h
    draw_src = src
    if cache_key is not None and (abs(sx - 1.0) >= 1e-6 or abs(sy - 1.0) >= 1e-6):
        draw_src = _scaled_surface_for_blit(
            src,
            int(geom.w or src_w),
            int(geom.h or src_h),
            cache_key=cache_key,
            content_token=content_token,
        )
        sx = 1.0
        sy = 1.0
    cr.scale(sx, sy)
    cr.set_source_surface(draw_src, 0, 0)
    pattern = cr.get_source()
    # Crispness pass (2026-04-21, Tier A of the livestream-crispness
    # research): pick the sharpest filter appropriate for the scale.
    # sx=sy=1.0 → FILTER_NEAREST (pixel-exact, zero interpolation cost).
    # Otherwise FILTER_BEST (bicubic; sharpest for non-integer scales).
    # Prior FILTER_BILINEAR softens text edges even at 1:1. Fallback
    # chain handles older cairo builds that may reject BEST.
    try:
        if abs(sx - 1.0) < 1e-6 and abs(sy - 1.0) < 1e-6:
            pattern.set_filter(cairo.FILTER_NEAREST)
        else:
            pattern.set_filter(cairo.FILTER_BEST)
    except Exception:
        try:
            pattern.set_filter(cairo.FILTER_BILINEAR)
        except Exception:
            log.debug("cairo filter selection failed on this pattern", exc_info=True)
    if blend_mode == "plus":
        cr.set_operator(cairo.OPERATOR_ADD)
    else:
        cr.set_operator(cairo.OPERATOR_OVER)
    cr.paint_with_alpha(opacity)
    cr.restore()


def _scaled_surface_for_blit(
    src: cairo.ImageSurface,
    width: int,
    height: int,
    *,
    cache_key: object,
    content_token: object | None,
) -> cairo.ImageSurface:
    src_w = max(src.get_width(), 1)
    src_h = max(src.get_height(), 1)
    width = max(1, width)
    height = max(1, height)
    key = (
        cache_key,
        content_token if content_token is not None else id(src),
        src_w,
        src_h,
        width,
        height,
    )
    with _SCALE_CACHE_LOCK:
        cached = _SCALE_CACHE.get(key)
        if cached is not None:
            return cached

    scaled = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    s_cr = cairo.Context(scaled)
    s_cr.scale(width / src_w, height / src_h)
    s_cr.set_source_surface(src, 0, 0)
    pattern = s_cr.get_source()
    try:
        pattern.set_filter(cairo.FILTER_BEST)
    except Exception:
        try:
            pattern.set_filter(cairo.FILTER_BILINEAR)
        except Exception:
            log.debug("scaled blit cache filter selection failed", exc_info=True)
    s_cr.paint()
    scaled.flush()
    with _SCALE_CACHE_LOCK:
        if len(_SCALE_CACHE) > 256:
            _SCALE_CACHE.clear()
        _SCALE_CACHE[key] = scaled
    return scaled


def blit_with_depth(
    cr: cairo.Context,
    src: cairo.ImageSurface,
    geom: SurfaceGeometry,
    opacity: float,
    blend_mode: str,
    z_plane: str = DEFAULT_Z_PLANE,
    z_index_float: float = DEFAULT_Z_INDEX_FLOAT,
    cache_key: object | None = None,
    content_token: object | None = None,
) -> None:
    """``blit_scaled`` with z-plane depth attenuation applied to opacity.

    Combines the ward's semantic ``z_plane`` (set by director / recruitment)
    with the modulator-written ``z_index_float`` to produce a depth-conditioned
    opacity multiplier. Default ``"on-scrim"`` + ``z_index_float=0.5`` yields
    a multiplier of ~0.96 — visually indistinguishable from a plain
    ``blit_scaled`` call. Deeper planes (``"beyond-scrim"``) drop to ~0.68.

    Phase 1: opacity-only depth. Real per-plane Cairo blur is too expensive
    in the hot path; differential blur + tint are routed through the Reverie
    colorgrade GPU node in Phase 3.
    """
    z_base = _Z_INDEX_BASE.get(z_plane, _Z_INDEX_BASE[DEFAULT_Z_PLANE])
    effective_z = max(0.0, min(1.0, z_base + (z_index_float - 0.5) * 0.2))
    depth_opacity = 0.6 + 0.4 * effective_z
    blit_scaled(
        cr,
        src,
        geom,
        opacity * depth_opacity,
        blend_mode,
        cache_key=cache_key,
        content_token=content_token,
    )


def pip_draw_from_layout(
    cr: cairo.Context,
    layout_state: LayoutState,
    source_registry: SourceRegistry,
    *,
    stage: Literal["pre_fx", "post_fx"] | None = None,
    use_composite_cache: bool = True,
) -> None:
    """Walk the current layout's assignments by z_order and blit each one.

    Called from the GStreamer cairooverlay draw callback on the
    streaming thread. Must stay cheap — no allocation in the hot path
    beyond sorting the assignment list. Surfaces whose geometry is not
    ``kind="rect"`` are skipped; they land on the glvideomixer appsrc
    path set up by Phase H.

    When a source's ``get_current_surface()`` returns ``None``, the blit
    is simply skipped for this frame — there is no fallback to the
    legacy ``compositor._token_pole.draw(cr)`` path. The legacy facades
    stay instantiated (backward compat during transition) but their
    ``draw()`` methods are only called by deprecated code paths that
    this callback has replaced.

    FINDING-R diagnostics (2026-04-21 wiring audit): each skip path
    increments a Prometheus counter labeled by ward_id + reason, and
    each successful blit increments a counter labeled by ward_id.
    Operators diagnosing visual-absence symptoms can rate-query the
    skip counter to identify which wards are not blitting and why.

    FINDING-W (ef7b-179, 2026-04-24): when ``stage`` is provided, only
    assignments whose ``render_stage`` matches are drawn. ``None``
    (default) renders every assignment — back-compat for any legacy
    caller not split across the two cairooverlay callbacks. The
    compositor wires ``stage="post_fx"`` on the post-FX callback and
    ``stage="pre_fx"`` on the BASE callback so chrome stays crisp on
    top of shaders and substrate gets decorated by them.
    """
    layout = layout_state.get()
    pairs: list[tuple[Any, Any, cairo.ImageSurface, object]] = []
    for assignment in layout.assignments:
        if stage is not None and getattr(assignment, "render_stage", "post_fx") != stage:
            continue
        surface_schema = layout.surface_by_id(assignment.surface)
        if surface_schema is None:
            _emit_blit_skip(assignment.source, "surface_not_found")
            continue
        if surface_schema.geometry.kind != "rect":
            # appsrc/wgpu/video_out paths — not a blit candidate.
            continue
        try:
            src = source_registry.get_current_surface(assignment.source)
        except KeyError:
            _emit_blit_skip(assignment.source, "source_not_registered")
            continue
        if src is None:
            _emit_blit_skip(assignment.source, "source_surface_none")
            continue
        pairs.append((assignment, surface_schema, src, id(src)))
    pairs.sort(key=lambda p: p[1].z_order)
    _publish_rendered_layout_state(
        layout_name=getattr(layout, "name", None),
        active_ward_ids=[assignment.source for assignment, *_rest in pairs],
        stage=stage,
    )

    target_size = _target_size_from_context(cr)
    if (
        use_composite_cache
        and stage is not None
        and target_size is not None
        and _layout_composite_cache_enabled(stage)
    ):
        signature = _layout_composite_signature(pairs)
        if _paint_cached_layout_composite(
            cr,
            stage=stage,
            signature=signature,
            min_interval_s=_layout_composite_interval_s(stage),
        ):
            return

        composite = cairo.ImageSurface(cairo.FORMAT_ARGB32, target_size[0], target_size[1])
        composite_cr = cairo.Context(composite)
        _draw_layout_pairs(composite_cr, pairs, stage=stage)
        composite.flush()
        _store_layout_composite(stage, signature, composite)
        cr.set_source_surface(composite, 0, 0)
        cr.paint()
        return

    _draw_layout_pairs(cr, pairs, stage=stage)


def _publish_rendered_layout_state(
    *,
    layout_name: object,
    active_ward_ids: list[str],
    stage: Literal["pre_fx", "post_fx"] | None,
) -> None:
    global _RENDERED_LAYOUT_STATE_LAST_PUBLISH_MONO, _RENDERED_LAYOUT_STATE_LAST_SIGNATURE

    now_mono = time.monotonic()
    stage_key = stage or "all"
    ward_ids = tuple(sorted(set(active_ward_ids)))
    layout_name_text = layout_name if isinstance(layout_name, str) else None
    with _RENDERED_LAYOUT_STATE_LOCK:
        _RENDERED_LAYOUT_STAGE_WARDS[stage_key] = (now_mono, ward_ids)
        active_union = tuple(
            sorted(
                {
                    ward
                    for observed_mono, observed_wards in _RENDERED_LAYOUT_STAGE_WARDS.values()
                    if now_mono - observed_mono <= RENDERED_LAYOUT_STAGE_TTL_S
                    for ward in observed_wards
                }
            )
        )
        signature = (layout_name_text, active_union)
        if (
            signature == _RENDERED_LAYOUT_STATE_LAST_SIGNATURE
            and now_mono - _RENDERED_LAYOUT_STATE_LAST_PUBLISH_MONO
            < RENDERED_LAYOUT_STATE_PUBLISH_INTERVAL_S
        ):
            return
        _RENDERED_LAYOUT_STATE_LAST_SIGNATURE = signature
        _RENDERED_LAYOUT_STATE_LAST_PUBLISH_MONO = now_mono

    try:
        from agents.studio_compositor import active_wards

        active_wards.publish(active_union)
        active_wards.publish_current_layout_state(
            layout_name=layout_name_text,
            active_ward_ids=active_union,
        )
    except Exception:
        log.debug("rendered layout state publish failed", exc_info=True)


def _draw_layout_pairs(
    cr: cairo.Context,
    pairs: list[tuple[Any, Any, cairo.ImageSurface, object]],
    *,
    stage: Literal["pre_fx", "post_fx"] | None,
) -> None:
    for assignment, surface_schema, src, content_token in pairs:
        # Task #157: clamp alpha to the non-destructive ceiling when the
        # assignment opts in, so informational wards cannot visually
        # destroy the camera content underneath them.
        effective_alpha = apply_nondestructive_clamp(
            assignment.opacity,
            assignment.non_destructive,
            assignment.source,
        )
        if effective_alpha <= 0.0:
            _emit_blit_skip(assignment.source, "alpha_clamped_to_zero")
            continue
        # Local import to avoid the runtime import of ``ward_properties`` (and
        # its ``cairo`` dependency for ``ward_render_scope``) before the
        # registry/layout modules have settled. Hot-path import is cached.
        from agents.studio_compositor.ward_properties import resolve_ward_properties

        if stage == "post_fx" and assignment.source not in _CONTRAST_FLOOR_SKIP:
            floor_alpha = (
                GOVERNANCE_CONTRAST_FLOOR_ALPHA
                if assignment.source in _GOVERNANCE_CONTRAST_SOURCES
                else CONTRAST_FLOOR_ALPHA
            )
            _paint_contrast_floor(cr, surface_schema.geometry, floor_alpha)

        props = resolve_ward_properties(assignment.source)
        blit_with_depth(
            cr,
            src,
            surface_schema.geometry,
            opacity=effective_alpha,
            blend_mode=surface_schema.blend_mode,
            z_plane=props.z_plane,
            z_index_float=props.z_index_float,
            cache_key=(
                assignment.source,
                assignment.surface,
                surface_schema.geometry.w,
                surface_schema.geometry.h,
            ),
            content_token=content_token,
        )
        _emit_blit_success(assignment.source)
        _record_blit_observability(
            assignment.source,
            src,
            surface_schema.geometry,
            effective_alpha,
        )


def _target_size_from_context(cr: cairo.Context) -> tuple[int, int] | None:
    try:
        target = cr.get_target()
        width = int(target.get_width())
        height = int(target.get_height())
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _layout_composite_signature(
    pairs: list[tuple[Any, Any, cairo.ImageSurface, object]],
) -> tuple[object, ...]:
    signature: list[object] = []
    for assignment, surface_schema, src, content_token in pairs:
        geom = surface_schema.geometry
        signature.append(
            (
                assignment.source,
                assignment.surface,
                getattr(assignment, "render_stage", "post_fx"),
                round(float(assignment.opacity), 4),
                bool(getattr(assignment, "non_destructive", False)),
                surface_schema.blend_mode,
                surface_schema.z_order,
                geom.kind,
                geom.x,
                geom.y,
                geom.w,
                geom.h,
                src.get_width(),
                src.get_height(),
                content_token,
            )
        )
    return tuple(signature)


def _paint_cached_layout_composite(
    cr: cairo.Context,
    *,
    stage: Literal["pre_fx", "post_fx"],
    signature: tuple[object, ...],
    min_interval_s: float,
) -> bool:
    now = time.monotonic()
    with _LAYOUT_COMPOSITE_CACHE_LOCK:
        entry = _LAYOUT_COMPOSITE_CACHE.get(stage)
    if entry is None:
        return False
    rendered_at = float(entry.get("rendered_at", 0.0))
    surface = entry.get("surface")
    if not isinstance(surface, cairo.ImageSurface):
        return False
    if min_interval_s > 0.0 and now - rendered_at < min_interval_s:
        # Explicit composite-Hz settings bound expensive full-layer redraws.
        # Dynamic wards may swap Cairo surface objects faster than the stream
        # can afford to repaint the whole post-FX layer; reuse the last
        # composite until the refresh interval opens, then honor the new
        # signature on the next render.
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
        return True
    if entry.get("signature") != signature:
        return False
    cr.set_source_surface(surface, 0, 0)
    cr.paint()
    return True


def _store_layout_composite(
    stage: Literal["pre_fx", "post_fx"],
    signature: tuple[object, ...],
    surface: cairo.ImageSurface,
) -> None:
    with _LAYOUT_COMPOSITE_CACHE_LOCK:
        _LAYOUT_COMPOSITE_CACHE[stage] = {
            "signature": signature,
            "surface": surface,
            "rendered_at": time.monotonic(),
        }


def _emit_blit_skip(ward_id: str, reason: str) -> None:
    """FINDING-R: count blit skips by ward + reason. Fail-open."""
    try:
        from agents.studio_compositor import metrics

        if metrics.WARD_BLIT_SKIPPED_TOTAL is not None:
            metrics.WARD_BLIT_SKIPPED_TOTAL.labels(ward=ward_id, reason=reason).inc()
    except Exception:
        pass


def _emit_blit_success(ward_id: str) -> None:
    """FINDING-R: count successful blits per ward. Fail-open."""
    try:
        from agents.studio_compositor import metrics

        if metrics.WARD_BLIT_TOTAL is not None:
            metrics.WARD_BLIT_TOTAL.labels(ward=ward_id).inc()
    except Exception:
        pass


# Rate-limit per-ward DEBUG logs so a long capture session doesn't flood
# the journal. Logging cadence is one line per ward per ~10s of frame
# delivery (300 frames at 30fps); the prometheus gauge is the always-on
# observability surface — DEBUG log is opt-in via journalctl --priority.
_DEBUG_LOG_PERIOD_FRAMES: int = 300
_debug_log_counters: dict[str, int] = {}


def _record_blit_observability(
    ward_id: str,
    src: cairo.ImageSurface,
    geom: SurfaceGeometry,
    effective_alpha: float,
) -> None:
    """FINDING-W deepening: record per-ward source-surface dimensions
    plus rate-limited DEBUG logging.

    The post-FX cairooverlay reports 16/16 wards blitting at full
    cadence, yet the wiring audit's visual sweep flagged 9/16 as not
    visible. The gap is "blit happens but the source surface is empty
    or 1×1". Per-ward gauge surfaces the actual surface dimensions so
    Grafana / curl can attribute "blitting nothing" to specific wards.

    Fail-open in two senses: the metric or log import can fail without
    breaking the render path, and the cairo surface accessors can raise
    on a degenerate / freed surface — both swallowed at DEBUG level.
    """
    src_w: int | None = None
    src_h: int | None = None
    source_pixels: int | None = None
    try:
        src_w = src.get_width()
        src_h = src.get_height()
        source_pixels = src_w * src_h
    except Exception:
        log.debug("ward blit readback: surface size read failed", exc_info=True)

    if source_pixels is not None:
        with _BLIT_READBACK_LOCK:
            _BLIT_READBACKS[ward_id] = {
                "ward_id": ward_id,
                "observed_at": time.time(),
                "source_width": src_w,
                "source_height": src_h,
                "source_pixels": source_pixels,
                "effective_alpha": effective_alpha,
                "surface_kind": geom.kind,
                "surface_x": geom.x,
                "surface_y": geom.y,
                "surface_w": geom.w,
                "surface_h": geom.h,
            }

    try:
        from agents.studio_compositor import metrics as _metrics

        if _metrics.WARD_SOURCE_SURFACE_PIXELS is not None:
            try:
                if source_pixels is not None:
                    _metrics.WARD_SOURCE_SURFACE_PIXELS.labels(ward=ward_id).set(
                        float(source_pixels)
                    )
            except Exception:
                log.debug("ward source-surface gauge: surface size read failed", exc_info=True)
    except Exception:
        log.debug("ward source-surface gauge: metric import failed", exc_info=True)

    if not log.isEnabledFor(logging.DEBUG):
        return
    counter = _debug_log_counters.get(ward_id, 0) + 1
    _debug_log_counters[ward_id] = counter
    if counter % _DEBUG_LOG_PERIOD_FRAMES != 1:
        return
    try:
        log.debug(
            "ward-blit ward=%s rect=(%s,%s,%s,%s) src=%dx%d alpha=%.2f",
            ward_id,
            geom.x or 0,
            geom.y or 0,
            geom.w or 0,
            geom.h or 0,
            src.get_width(),
            src.get_height(),
            effective_alpha,
        )
    except Exception:
        log.debug("ward-blit DEBUG log raised", exc_info=True)


def _pip_draw(compositor: Any, cr: Any) -> None:
    """Post-FX cairooverlay callback — renders chrome wards on top of shaders.

    Phase 9 Task 29 of the compositor unification epic removed the
    pre-Phase-3 legacy fallback and the cross-facade double-draw for
    ``_stream_overlay``. Layout state + source registry are always
    populated by ``StudioCompositor.start_layout_only`` (PR #735),
    so the layout walk is the only render path.

    FINDING-W (ef7b-179): filters assignments to those whose
    ``render_stage == "post_fx"`` so they blit AFTER the shader chain.
    Substrate assignments (``render_stage == "pre_fx"``) are drawn by
    :func:`pre_fx_draw_from_layout` on the BASE cairooverlay instead.
    """
    layout_state = getattr(compositor, "layout_state", None)
    source_registry = getattr(compositor, "source_registry", None)
    if layout_state is not None and source_registry is not None:
        target_size = _target_size_from_context(cr)
        if target_size is not None:
            draw_post_fx_layout_from_composite(compositor, cr, target_size[0], target_size[1])
        else:
            pip_draw_from_layout(cr, layout_state, source_registry, stage="post_fx")

    draw_hero_small_overlay(compositor, cr, stage="post_fx")


def draw_hero_small_overlay(
    compositor: Any,
    cr: Any,
    *,
    stage: Literal["pre_fx", "post_fx"],
) -> None:
    if not _hero_small_overlay_enabled() or _hero_small_overlay_stage() != stage:
        return
    hero_small = getattr(compositor, "_hero_small", None)
    if hero_small is None:
        return
    try:
        hero_small.draw(cr)
    except Exception:
        log.debug("hero_small.draw raised", exc_info=True)


def _has_post_fx_layout_assignments(compositor: Any) -> bool:
    layout_state = getattr(compositor, "layout_state", None)
    if layout_state is None:
        return False
    try:
        layout = layout_state.get()
    except Exception:
        log.debug("post-FX overlay requirement check failed", exc_info=True)
        return True
    for assignment in getattr(layout, "assignments", ()):
        if getattr(assignment, "render_stage", "post_fx") == "post_fx":
            return True
    return False


def _post_fx_overlay_required(compositor: Any) -> bool:
    if _post_fx_overlay_disabled():
        return False
    if _hero_small_overlay_enabled() and _hero_small_overlay_stage() == "post_fx":
        return True
    return _has_post_fx_layout_assignments(compositor)


def draw_pre_fx_layout_from_composite(
    compositor: Any,
    cr: cairo.Context,
    canvas_w: int,
    canvas_h: int,
) -> None:
    layout_state = getattr(compositor, "layout_state", None)
    source_registry = getattr(compositor, "source_registry", None)
    if layout_state is None or source_registry is None:
        return
    pip_draw_from_layout(
        cr,
        layout_state,
        source_registry,
        stage="pre_fx",
        use_composite_cache=_pre_fx_background_composite_enabled(),
    )
    draw_hero_small_overlay(compositor, cr, stage="pre_fx")


def draw_post_fx_layout_from_composite(
    compositor: Any,
    cr: cairo.Context,
    canvas_w: int,
    canvas_h: int,
) -> None:
    layout_state = getattr(compositor, "layout_state", None)
    source_registry = getattr(compositor, "source_registry", None)
    if layout_state is None or source_registry is None:
        return
    pip_draw_from_layout(
        cr,
        layout_state,
        source_registry,
        stage="post_fx",
        use_composite_cache=_post_fx_background_composite_enabled(),
    )


def pre_fx_draw_from_layout(compositor: Any, cr: Any) -> None:
    """BASE cairooverlay helper — renders substrate assignments.

    FINDING-W (ef7b-179, 2026-04-24): exposes the pre-FX layout walk so
    :mod:`agents.studio_compositor.overlay`::``on_draw`` can blit any
    assignment tagged ``render_stage="pre_fx"`` before the glfeedback
    shader chain decorates the frame. Called after Sierpinski + GEAL
    so those surfaces keep their historical z-order above the layout
    substrate.

    No-op when no assignment is tagged ``pre_fx`` (the default layout
    is chrome-only on ship, so the BASE cost stays unchanged until a
    layout opts substrate assignments in).
    """
    layout_state = getattr(compositor, "layout_state", None)
    source_registry = getattr(compositor, "source_registry", None)
    if layout_state is not None and source_registry is not None:
        target_size = _target_size_from_context(cr)
        if target_size is not None:
            draw_pre_fx_layout_from_composite(compositor, cr, target_size[0], target_size[1])
        else:
            pip_draw_from_layout(cr, layout_state, source_registry, stage="pre_fx")
            draw_hero_small_overlay(compositor, cr, stage="pre_fx")


class FlashScheduler:
    """Audio-reactive live overlay flash on the camera base.

    Kick onsets trigger a flash. Flash duration scales with bass energy.
    Random baseline schedule fills gaps when no kicks are detected.
    Alpha decays smoothly from 0.6 → 0.0 for organic feel.
    """

    FLASH_ALPHA = 0.5
    # Random baseline — more on than off (bad reception feel)
    MIN_INTERVAL = 0.1  # very short gaps between flashes
    MAX_INTERVAL = 1.0  # max 1s gap
    MIN_DURATION = 0.5  # flashes last longer
    MAX_DURATION = 3.0
    # Audio-reactive
    KICK_COOLDOWN = 0.2  # normal mode
    KICK_COOLDOWN_VINYL = 0.4  # vinyl mode: half-speed = longer between kicks

    def __init__(self) -> None:
        self._next_flash_at: float = time.monotonic() + random.uniform(1.0, 3.0)
        self._flash_end_at: float = 0.0
        self._flashing: bool = False
        self._current_alpha: float = 0.0
        self._last_kick_at: float = 0.0

    def kick(self, t: float, bass_energy: float) -> None:
        """Called when a kick onset is detected. Triggers a flash."""
        cooldown = (
            self.KICK_COOLDOWN_VINYL if getattr(self, "_vinyl_mode", False) else self.KICK_COOLDOWN
        )
        if t - self._last_kick_at < cooldown:
            return  # cooldown
        self._last_kick_at = t
        self._flashing = True
        # Duration scales with bass energy: more bass = longer flash
        duration = 0.1 + bass_energy * 0.4  # 0.1s to 0.5s — short punch
        self._flash_end_at = t + min(duration, self.MAX_DURATION)
        self._current_alpha = self.FLASH_ALPHA

    def tick(self, t: float) -> float | None:
        """Returns target alpha if changed, None if no change needed."""
        if self._flashing:
            # Smooth decay toward end of flash
            remaining = self._flash_end_at - t
            total = self._flash_end_at - self._last_kick_at if self._last_kick_at > 0 else 1.0
            if remaining <= 0:
                self._flashing = False
                self._next_flash_at = t + random.uniform(self.MIN_INTERVAL, self.MAX_INTERVAL)
                if self._current_alpha != 0.0:
                    self._current_alpha = 0.0
                    return 0.0
            else:
                # Fade out over the last 40% of the flash
                fade_point = total * 0.6
                if remaining < fade_point and fade_point > 0:
                    target = self.FLASH_ALPHA * (remaining / fade_point)
                else:
                    target = self.FLASH_ALPHA
                if abs(target - self._current_alpha) > 0.02:
                    self._current_alpha = target
                    return target
        else:
            # Random baseline flash (fills silence)
            if t >= self._next_flash_at:
                self._flashing = True
                duration = random.uniform(self.MIN_DURATION, self.MAX_DURATION)
                self._flash_end_at = t + duration
                self._last_kick_at = t
                self._current_alpha = self.FLASH_ALPHA
                return self.FLASH_ALPHA
        return None


def _ensure_base_cairo_sources(compositor: Any) -> None:
    """Create renderer state expected by the base cairooverlay draw path."""
    from .overlay import sierpinski_base_overlay_enabled

    if not sierpinski_base_overlay_enabled():
        for attr in ("_sierpinski_loader", "_sierpinski_renderer"):
            source = getattr(compositor, attr, None)
            if source is not None and hasattr(source, "stop"):
                try:
                    source.stop()
                except Exception:
                    log.debug("Failed to stop %s after Sierpinski base overlay disable", attr)
            setattr(compositor, attr, None)
        compositor._geal_source = None
        _publish_fx_runtime_feature("sierpinski_base_overlay", False)
        log.info("Sierpinski/GEAL base overlay disabled by HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED")
        return

    if getattr(compositor, "_sierpinski_loader", None) is None:
        from .sierpinski_loader import SierpinskiLoader

        compositor._sierpinski_loader = SierpinskiLoader()
        compositor._sierpinski_loader.start()
    if getattr(compositor, "_sierpinski_renderer", None) is None:
        from .sierpinski_renderer import SierpinskiRenderer

        compositor._sierpinski_renderer = SierpinskiRenderer(
            budget_tracker=getattr(compositor, "_budget_tracker", None)
        )
        compositor._sierpinski_renderer.start()
    if getattr(compositor, "_geal_source", None) is None:
        from .geal_source import GealCairoSource

        compositor._geal_source = GealCairoSource(
            _sierpinski_geom_provider=compositor._sierpinski_renderer._source,
        )
    _publish_fx_runtime_feature("sierpinski_base_overlay", True)


def _build_overlay_only_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any
) -> bool:
    Gst = compositor._Gst
    from .overlay import on_draw, on_overlay_caps_changed

    queue_base = Gst.ElementFactory.make("queue", "queue-fx-base")
    if queue_base is None:
        log.error("FX overlay-only chain: queue-fx-base factory failed")
        return False
    queue_base.set_property("leaky", 2)
    queue_base.set_property("max-size-buffers", 2)

    overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
    if overlay is None:
        log.error("FX overlay-only chain: cairooverlay factory failed")
        return False

    fold_post_fx_into_base = _post_fx_overlay_required(compositor)

    def _draw_base(overlay_obj: Any, cr: Any, ts: int, dur: int) -> None:
        on_draw(compositor, overlay_obj, cr, ts, dur)
        if fold_post_fx_into_base:
            _pip_draw(compositor, cr)

    overlay.connect("draw", _draw_base)
    overlay.connect("caps-changed", lambda o, caps: on_overlay_caps_changed(compositor, o, caps))

    elements = [queue_base, overlay]
    if _overlay_only_output_convert_enabled():
        convert = Gst.ElementFactory.make("videoconvert", "fx-overlay-only-convert")
        if convert is None:
            log.error("FX overlay-only chain: videoconvert factory failed")
            return False
        convert.set_property("dither", 0)
        elements.append(convert)

    for el in elements:
        pipeline.add(el)

    tee_pad_live = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    if tee_pad_live is None:
        log.error("FX overlay-only chain: failed to request pre-fx tee pad")
        return False
    queue_sink = queue_base.get_static_pad("sink")
    if queue_sink is None or tee_pad_live.link(queue_sink) != Gst.PadLinkReturn.OK:
        log.error("FX overlay-only chain: failed to link pre-fx tee to base queue")
        return False

    for i in range(len(elements) - 1):
        if not elements[i].link(elements[i + 1]):
            log.error(
                "FX overlay-only chain: failed to link %s -> %s",
                elements[i].get_name(),
                elements[i + 1].get_name(),
            )
            return False
    if not elements[-1].link(output_tee):
        log.error("FX overlay-only chain: failed to link final element to output tee")
        return False

    compositor._slot_pipeline = None
    compositor._fx_flash_scheduler = None
    compositor._fx_flash_pad = None
    _ensure_base_cairo_sources(compositor)
    _publish_fx_runtime_feature("shader_fx", False)
    _publish_fx_runtime_feature("post_fx_overlay", False)
    _publish_fx_runtime_feature("post_fx_folded_base", fold_post_fx_into_base)
    _publish_fx_runtime_feature("flash_overlay", False)
    log.info("FX chain: overlay-only base path (post_fx_folded=%s)", fold_post_fx_into_base)
    return True


def build_inline_fx_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any, fps: int
) -> bool:
    """Build GPU effects chain with glvideomixer for camera+live flash overlay.

    Pipeline:
      input-selector (camera) → queue → cairooverlay → glupload → glcolorconvert ─→ glvideomixer sink_0 (base, alpha=1)
      pre_fx_tee (live flash)  → queue →                glupload → glcolorconvert ─→ glvideomixer sink_1 (flash, alpha=0↔0.6)
                                                                                            ↓
                                                                                   [24 glfeedback slots]
                                                                                            ↓
                                                                                   glcolorconvert → gldownload → output_tee

    Both sources composited on GPU via glvideomixer. FlashScheduler
    animates the flash pad's alpha property (0.0 ↔ 0.6) on a random
    schedule. Text overlay (cairooverlay) on the base path goes through
    all shader effects.
    """
    Gst = compositor._Gst
    if os.environ.get("HAPAX_COMPOSITOR_DISABLE_INLINE_FX") == "1":
        compositor._slot_pipeline = None
        log.warning("HAPAX_COMPOSITOR_DISABLE_INLINE_FX=1 — bypassing GL inline FX chain")
        return False
    if _shader_fx_disabled():
        log.warning("HAPAX_COMPOSITOR_DISABLE_SHADER_FX=1 — using overlay-only FX chain")
        return _build_overlay_only_chain(compositor, pipeline, pre_fx_tee, output_tee)

    # --- Input selector for camera source switching ---
    input_sel = Gst.ElementFactory.make("input-selector", "fx-input-selector")
    input_sel.set_property("sync-streams", False)
    pipeline.add(input_sel)

    # --- Base path: input-selector → queue → cairooverlay → glupload → glcolorconvert ---
    queue_base = Gst.ElementFactory.make("queue", "queue-fx-base")
    queue_base.set_property("leaky", 2)
    queue_base.set_property("max-size-buffers", 2)

    from .overlay import on_draw, on_overlay_caps_changed

    overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
    overlay.connect("draw", lambda o, cr, ts, dur: on_draw(compositor, o, cr, ts, dur))
    overlay.connect("caps-changed", lambda o, caps: on_overlay_caps_changed(compositor, o, caps))

    convert_base = Gst.ElementFactory.make("videoconvert", "fx-convert-base")
    convert_base.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    glupload_base = Gst.ElementFactory.make("glupload", "fx-glupload-base")
    glcc_base = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-base")

    # --- Flash path: pre_fx_tee → queue → glupload → glcolorconvert ---
    queue_flash = Gst.ElementFactory.make("queue", "queue-fx-flash")
    queue_flash.set_property("leaky", 2)
    queue_flash.set_property("max-size-buffers", 2)
    convert_flash = Gst.ElementFactory.make("videoconvert", "fx-convert-flash")
    convert_flash.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    glupload_flash = Gst.ElementFactory.make("glupload", "fx-glupload-flash")
    glcc_flash = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-flash")

    # --- glvideomixer: GPU-native compositing ---
    glmixer = Gst.ElementFactory.make("glvideomixer", "fx-glmixer")
    glmixer.set_property("background", 1)  # 1=black (default is 0=checker!)
    # Delta drop #40 GLM-1: same GstAggregator `latency=0` issue as
    # cudacompositor (see pipeline.py COMP-1). The base path has a
    # cairooverlay streaming-thread callback (~6-10 ms per frame, drop #39)
    # that the flash path does not, creating a consistent 6-10 ms pad
    # timing mismatch. 33 ms of grace aligns both pads on the same
    # source-frame timestamp and eliminates the 18-31% of output frames
    # that would otherwise carry one-frame-old base content. No
    # `ignore-inactive-pads` counterpart: glvideomixer does not expose
    # that property (its internal aggregator base does not surface it).
    #
    # Beta pass-4 L-01: wrap in try/except for uniformity with the
    # cudacompositor setters in pipeline.py COMP-1/COMP-2. `latency` is
    # a well-known GstAggregator property so failure is extremely
    # unlikely on any modern gst-plugins-bad build, but the asymmetry
    # is a code-review flag — one of the two patterns should win.
    try:
        glmixer.set_property("latency", 33_000_000)
    except Exception:
        log.debug("glvideomixer: latency property not supported", exc_info=True)

    # --- Post-mixer: shader chain → output ---
    from agents.effect_graph.pipeline import SlotPipeline

    registry = compositor._graph_runtime._registry if compositor._graph_runtime else None
    # A+ Stage 0 (2026-04-17): 24 → 12 glfeedback slots. Audit of all
    # presets used by the compositor (chat_reactor + random_mode): max
    # node count is 8 (trap, screwed, mirror_rorschach, heartbeat,
    # ambient, dither_retro). 12 slots preserves 50% headroom above the
    # largest preset while halving the per-frame full-screen quad work
    # for passthrough slots — the fx-glmi+ thread at 54% CPU in the
    # thread dump is dominated by these passthrough shader invocations.
    compositor._slot_pipeline = SlotPipeline(registry, num_slots=_fx_slot_count_from_env())

    hero_effect_slot = _make_hero_effect_slot(Gst)
    glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")
    fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")
    fx_convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns

    all_elements = [
        input_sel,
        queue_base,
        overlay,
        convert_base,
        glupload_base,
        glcc_base,
        queue_flash,
        convert_flash,
        glupload_flash,
        glcc_flash,
        glmixer,
    ]
    if hero_effect_slot is not None:
        all_elements.append(hero_effect_slot)
    all_elements.extend([glcolorconvert_out, gldownload, fx_convert])
    for el in all_elements:
        if el is None:
            log.error("Failed to create FX element — effects disabled")
            return False
        pipeline.add(el)

    # --- Link base path ---
    input_sel.link(queue_base)
    queue_base.link(overlay)
    overlay.link(convert_base)
    convert_base.link(glupload_base)
    glupload_base.link(glcc_base)

    # --- Link flash path ---
    tee_pad_flash = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    tee_pad_flash.link(queue_flash.get_static_pad("sink"))
    queue_flash.link(convert_flash)
    convert_flash.link(glupload_flash)
    glupload_flash.link(glcc_flash)

    # --- glvideomixer pads ---
    base_pad = glmixer.request_pad(glmixer.get_pad_template("sink_%u"), None, None)
    base_pad.set_property("zorder", 0)
    base_pad.set_property("alpha", 1.0)
    glcc_base.link_pads("src", glmixer, base_pad.get_name())

    flash_pad = glmixer.request_pad(glmixer.get_pad_template("sink_%u"), None, None)
    flash_pad.set_property("zorder", 1)
    flash_pad.set_property("alpha", 0.0)  # hidden until flash
    glcc_flash.link_pads("src", glmixer, flash_pad.get_name())

    # --- Store glmixer ref ---
    compositor._fx_glmixer = glmixer

    # --- Shader chain after mixer ---
    shader_downstream = hero_effect_slot if hero_effect_slot is not None else glcolorconvert_out
    compositor._slot_pipeline.build_chain(pipeline, Gst, glmixer, shader_downstream)

    if hero_effect_slot is not None:
        if not hero_effect_slot.link(glcolorconvert_out):
            log.error("Failed to link hero-effect-slot -> fx-glcc-out")
            return False
        _install_hero_effect_rotator(compositor, hero_effect_slot)

    glcolorconvert_out.link(gldownload)
    gldownload.link(fx_convert)

    # --- Post-FX cairooverlay: composites chrome wards AFTER shader chain ---
    # Avoid creating this extra streaming-thread cairooverlay when there is
    # nothing to draw or when an incident canary has explicitly disabled it.
    if _post_fx_overlay_required(compositor):
        pip_overlay = Gst.ElementFactory.make("cairooverlay", "pip-overlay")
        pip_overlay.connect("draw", lambda o, cr, ts, dur: _pip_draw(compositor, cr))
        pipeline.add(pip_overlay)
        fx_convert.link(pip_overlay)
        pip_overlay.link(output_tee)
        _publish_fx_runtime_feature("post_fx_overlay", True)
        _publish_fx_runtime_feature("post_fx_folded_base", False)
    else:
        fx_convert.link(output_tee)
        _publish_fx_runtime_feature("post_fx_overlay", False)
        _publish_fx_runtime_feature("post_fx_folded_base", False)

    # --- Input-selector: default to live (tiled composite) ---
    live_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
    tee_pad_live = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    tee_pad_live.link(live_pad)
    input_sel.set_property("active-pad", live_pad)

    # --- Store everything ---
    compositor._fx_input_selector = input_sel
    compositor._fx_input_pads = {"live": live_pad}
    compositor._fx_active_source = "live"
    compositor._fx_camera_branch = []  # list[Any] — camera branch elements for teardown
    compositor._fx_switching = False
    compositor._fx_flash_pad = flash_pad
    compositor._fx_flash_scheduler = FlashScheduler()

    # PiP cairo sources (token_pole, album, stream_overlay) are now
    # instantiated by the SourceRegistry from default.json — Phase 9 Task 29
    # removed their legacy facade construction sites.
    #
    # SierpinskiLoader + SierpinskiRenderer remain: Sierpinski is a full-
    # canvas main-layer render (not a PiP) driven by overlay.py::on_draw,
    # with the renderer holding set_active_slot / set_audio_energy state.
    # Migrating Sierpinski to the source registry's fx_chain_input surface
    # is a separate refactor tracked as a follow-up ticket.
    _ensure_base_cairo_sources(compositor)
    log.info("SierpinskiLoader + SierpinskiRenderer created (render thread at 10fps)")
    log.info("GealCairoSource constructed (gated behind HAPAX_GEAL_ENABLED=1)")
    _publish_fx_runtime_feature("shader_fx", True)
    _publish_fx_runtime_feature("flash_overlay", _visual_pumping_enabled())

    log.info(
        "FX chain: %d shader slots, glvideomixer (camera base + live flash 60%%)",
        compositor._slot_pipeline.num_slots,
    )
    return True


def _make_hero_effect_slot(Gst: Any) -> Any | None:
    """Create the optional dedicated hero-effect GL pass."""
    if os.environ.get("HAPAX_COMPOSITOR_DISABLE_HERO_EFFECT") == "1":
        log.info("HeroEffectRotator disabled by HAPAX_COMPOSITOR_DISABLE_HERO_EFFECT=1")
        return None
    if Gst.ElementFactory.find("glfeedback") is None:
        log.info("HeroEffectRotator disabled: glfeedback factory unavailable")
        return None
    slot = Gst.ElementFactory.make("glfeedback", "hero-effect-slot")
    if slot is None:
        log.info("HeroEffectRotator disabled: hero-effect-slot creation failed")
        return None
    try:
        from .hero_effect_rotator import HERO_EFFECT_PASSTHROUGH

        slot.set_property("fragment", HERO_EFFECT_PASSTHROUGH)
    except Exception:
        log.debug("HeroEffectRotator passthrough seed failed", exc_info=True)
    return slot


def _hero_effect_target(compositor: Any) -> tuple[str, Any] | None:
    """Return the configured hero camera's tile in the active tiled layout."""
    layout = getattr(compositor, "_tile_layout", {}) or {}
    cameras = getattr(getattr(compositor, "config", None), "cameras", ()) or ()
    for cam in cameras:
        role = getattr(cam, "role", "")
        if not getattr(cam, "hero", False) or not role:
            continue
        tile = layout.get(role)
        if tile is None:
            continue
        if getattr(tile, "w", 0) <= 0 or getattr(tile, "h", 0) <= 0:
            continue
        return role, tile
    return None


def _install_hero_effect_rotator(compositor: Any, slot: Any) -> None:
    """Attach HeroEffectRotator to the dedicated post-FX GL pass."""
    try:
        from .hero_effect_rotator import HeroEffectRotator

        rotator = getattr(compositor, "_hero_effect_rotator", None)
        if not isinstance(rotator, HeroEffectRotator):
            rotator = HeroEffectRotator()
        rotator.set_slot(slot)
        target = _hero_effect_target(compositor)
        if target is not None:
            _, tile = target
            rotator.update_hero_tile(tile)
            rotator.tick()
        compositor._hero_effect_rotator = rotator
        log.info("HeroEffectRotator slot bound: effects=%d target=%s", rotator.effect_count, target)
    except Exception:
        compositor._hero_effect_rotator = None
        log.exception("HeroEffectRotator wiring failed")


def switch_fx_source(compositor: Any, source: str) -> bool:
    """Switch FX chain input to a different camera or back to tiled composite.

    Uses IDLE pad probe to safely modify the pipeline while PLAYING.
    Creates camera branch on-demand (lazy), tears down old one.

    HOMAGE Phase 6 Layer 5 — on a real swap (source actually changes),
    publish ``FXEvent(kind="chain_swap")`` so token_pole + activity_variety_log
    get a brief scale bump synced to the visible source change.
    """
    if not hasattr(compositor, "_fx_input_selector"):
        return False
    if source == getattr(compositor, "_fx_active_source", "live"):
        return True  # already active
    if getattr(compositor, "_fx_switching", False):
        return False  # switch in progress

    # HOMAGE Phase 6 Layer 5: chain swap event. Publish immediately
    # (before the IDLE probe fires) so the reactor ward-property write
    # happens concurrently with the visible switch. Best-effort; a bus
    # failure must never block the camera switch.
    try:
        from shared.ward_fx_bus import FXEvent, get_bus

        get_bus().publish_fx(FXEvent(kind="chain_swap"))
    except Exception:
        log.debug("ward_fx_bus publish_fx (chain_swap) failed", exc_info=True)

    Gst = compositor._Gst
    input_sel = compositor._fx_input_selector
    pipeline = compositor.pipeline

    if source == "live":
        # Switch back to tiled composite — just set active pad
        live_pad = compositor._fx_input_pads.get("live")
        if live_pad is None:
            return False
        input_sel.set_property("active-pad", live_pad)
        _teardown_camera_branch(compositor, Gst)
        compositor._fx_active_source = "live"
        log.info("FX source: switched to live (tiled composite)")
        return True

    # YouTube source: v4l2src from /dev/video50
    is_youtube = source == "youtube"

    if not is_youtube:
        # Switch to individual camera — need to create branch on-demand
        role = source.replace("-", "_")
        cam_tee = pipeline.get_by_name(f"tee_{role}")
        if cam_tee is None:
            log.warning("FX source: camera tee for %s not found", source)
            return False

    compositor._fx_switching = True

    # Use IDLE probe on input-selector src pad for safe modification
    src_pad = input_sel.get_static_pad("src")

    def _probe_callback(pad: Any, info: Any) -> Any:
        try:
            # Tear down previous camera branch if any
            _teardown_camera_branch(compositor, Gst)

            out_w = compositor.config.output_width
            out_h = compositor.config.output_height
            fps = compositor.config.framerate

            if is_youtube:
                # YouTube: v4l2src from /dev/video50
                v4l2 = Gst.ElementFactory.make("v4l2src", "fxsrc-yt")
                v4l2.set_property("device", "/dev/video50")
                v4l2.set_property("do-timestamp", True)
                q = Gst.ElementFactory.make("queue", "fxsrc-q")
                q.set_property("leaky", 2)
                q.set_property("max-size-buffers", 1)
                convert = Gst.ElementFactory.make("videoconvert", "fxsrc-convert")
                convert.set_property("dither", 0)
                scale = Gst.ElementFactory.make("videoscale", "fxsrc-scale")
                caps = Gst.ElementFactory.make("capsfilter", "fxsrc-caps")
                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(f"video/x-raw,format=BGRA,width={out_w},height={out_h}"),
                )
                elements = [v4l2, q, convert, scale, caps]
                for el in elements:
                    pipeline.add(el)
                v4l2.link(q)
                q.link(convert)
                convert.link(scale)
                scale.link(caps)
                for el in elements:
                    el.sync_state_with_parent()
            else:
                # Camera: branch from camera_tee
                q = Gst.ElementFactory.make("queue", "fxsrc-q")
                q.set_property("leaky", 2)
                q.set_property("max-size-buffers", 1)
                convert = Gst.ElementFactory.make("videoconvert", "fxsrc-convert")
                convert.set_property("dither", 0)
                scale = Gst.ElementFactory.make("videoscale", "fxsrc-scale")
                caps = Gst.ElementFactory.make("capsfilter", "fxsrc-caps")
                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,format=BGRA,width={out_w},height={out_h},framerate={fps}/1"
                    ),
                )

                elements = [q, convert, scale, caps]
                for el in elements:
                    pipeline.add(el)
                q.link(convert)
                convert.link(scale)
                scale.link(caps)
                for el in elements:
                    el.sync_state_with_parent()

                # Link camera tee → queue
                tee_pad = cam_tee.request_pad(cam_tee.get_pad_template("src_%u"), None, None)
                q_sink = q.get_static_pad("sink")
                tee_pad.link(q_sink)

            # Link caps → new input-selector pad
            sel_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
            caps.link_pads("src", input_sel, sel_pad.get_name())

            # Switch active pad
            input_sel.set_property("active-pad", sel_pad)

            # Store for teardown
            if is_youtube:
                elements = [
                    el
                    for el in [
                        pipeline.get_by_name("fxsrc-yt"),
                        pipeline.get_by_name("fxsrc-q"),
                        pipeline.get_by_name("fxsrc-convert"),
                        pipeline.get_by_name("fxsrc-scale"),
                        pipeline.get_by_name("fxsrc-caps"),
                    ]
                    if el is not None
                ]
            compositor._fx_camera_branch = elements
            compositor._fx_camera_tee_pad = None if is_youtube else tee_pad
            compositor._fx_camera_sel_pad = sel_pad
            compositor._fx_active_source = source
            compositor._fx_switching = False

            log.info("FX source: switched to %s (lazy branch created)", source)
        except Exception:
            log.exception("FX source switch failed")
            compositor._fx_switching = False

        return Gst.PadProbeReturn.REMOVE

    src_pad.add_probe(Gst.PadProbeType.IDLE, _probe_callback)
    return True


def _teardown_camera_branch(compositor: Any, Gst: Any) -> None:
    """Remove the previous camera-specific FX source branch."""
    elements = getattr(compositor, "_fx_camera_branch", [])
    if not elements:
        return

    pipeline = compositor.pipeline

    # Unlink camera tee pad
    tee_pad = getattr(compositor, "_fx_camera_tee_pad", None)
    if tee_pad is not None:
        peer = tee_pad.get_peer()
        if peer is not None:
            tee_pad.unlink(peer)

    # Release input-selector pad
    sel_pad = getattr(compositor, "_fx_camera_sel_pad", None)
    if sel_pad is not None:
        compositor._fx_input_selector.release_request_pad(sel_pad)

    # Stop and remove elements
    for el in reversed(elements):
        el.set_state(Gst.State.NULL)
        pipeline.remove(el)

    compositor._fx_camera_branch = []
    compositor._fx_camera_tee_pad = None
    compositor._fx_camera_sel_pad = None


def fx_tick_callback(compositor: Any) -> bool:
    """GLib timeout: update graph shader uniforms at ~30fps."""
    if not compositor._running:
        return False
    if not hasattr(compositor, "_slot_pipeline") or compositor._slot_pipeline is None:
        return False

    from .fx_tick import tick_governance, tick_modulator, tick_slot_pipeline

    if not hasattr(compositor, "_fx_monotonic_start"):
        compositor._fx_monotonic_start = time.monotonic()
    t = time.monotonic() - compositor._fx_monotonic_start

    with compositor._overlay_state._lock:
        energy = compositor._overlay_state._data.audio_energy_rms
    beat = min(energy * 4.0, 1.0)
    if not hasattr(compositor, "_fx_beat_smooth"):
        compositor._fx_beat_smooth = 0.0
    compositor._fx_beat_smooth = max(beat, compositor._fx_beat_smooth * 0.85)
    b = compositor._fx_beat_smooth

    # Cache audio signals BEFORE tick_modulator (which calls get_signals and decays them)
    cached_audio: dict[str, float] = {}
    if hasattr(compositor, "_audio_capture"):
        cached_audio = compositor._audio_capture.get_signals()
    compositor._cached_audio = cached_audio

    # CVS #149: unified reactivity bus tick. When the feature flag is
    # OFF (default), this is a no-op from the consumer's perspective —
    # the bus publishes to SHM but fx_tick_callback continues to read
    # from ``_cached_audio`` (direct AudioCapture path). When ON,
    # consumers may prefer the bus-blended signals via
    # ``shared.audio_reactivity.read_shm_snapshot`` or by reading the
    # bus's ``last_snapshot()`` directly.
    try:
        from shared.audio_reactivity import get_bus
        from shared.audio_reactivity import is_active as _unified_active

        _bus = get_bus()
        if _bus.sources():
            _bus.tick(publish=True)
            if _unified_active():
                _snapshot = _bus.last_snapshot()
                if _snapshot is not None:
                    compositor._unified_reactivity = _snapshot
    except Exception:
        # Never let the unified bus crash fx_tick — direct path remains.
        log.debug("unified-reactivity tick failed", exc_info=True)

    tick_governance(compositor, t)
    tick_modulator(compositor, t, energy, b)
    # Ward stimmung modulator (z-axis spec Phase 2). Default-off behind
    # ``HAPAX_WARD_MODULATOR_ACTIVE``; ``maybe_tick`` early-returns and
    # never raises into the fx tick path.
    modulator = getattr(compositor, "_ward_stimmung_modulator", None)
    if modulator is not None:
        modulator.maybe_tick()
    tick_slot_pipeline(compositor, t)

    # Flash scheduler: animate glvideomixer flash pad alpha
    scheduler = getattr(compositor, "_fx_flash_scheduler", None)
    flash_pad = getattr(compositor, "_fx_flash_pad", None)
    if _visual_pumping_enabled() and scheduler and flash_pad:
        now = time.monotonic()
        kick = cached_audio.get("onset_kick", 0.0)
        beat = cached_audio.get("beat_pulse", 0.0)
        bass = cached_audio.get("mixer_bass", 0.0)
        if kick > 0.3 or beat > 0.6:
            scheduler.kick(now, bass)
        alpha = scheduler.tick(now)
        if alpha is not None:
            flash_pad.set_property("alpha", alpha)

    # HOMAGE Phase 6 Layer 5: publish audio-driven FX events so wards
    # can react on the beat. Edge-triggered with short cooldowns so we
    # emit one event per kick / one event per sustained intensity band,
    # not an event per frame.
    _maybe_publish_audio_fx_events(compositor, cached_audio)

    # Facade tick() hooks removed in Phase 9 Task 29. Cairo sources now
    # tick autonomously on their CairoSourceRunner background threads.
    return True


# HOMAGE Phase 6 Layer 5 cooldowns. The fx_tick_callback runs at ~30Hz,
# but wards only need one event per kick and one per intensity window.
# These constants hold the edge-trigger thresholds + minimum inter-event
# spacing. Tuned so a typical 120 BPM kick (2Hz, 500ms between kicks)
# emits one event per kick without ever emitting more than one per 150ms.
_AUDIO_KICK_FX_THRESHOLD: float = 0.6
_AUDIO_KICK_FX_COOLDOWN_S: float = 0.15
_INTENSITY_SPIKE_FX_THRESHOLD: float = 0.75
_INTENSITY_SPIKE_FX_COOLDOWN_S: float = 0.8


def _maybe_publish_audio_fx_events(compositor: Any, audio: dict[str, float]) -> None:
    """Publish audio-reactive FX events on edge-triggered thresholds.

    HOMAGE Phase 6 Layer 5 — consumed by the ward-FX reactor to push a
    ``scale_bump_pct`` / ``border_pulse_hz`` onto audio-reactive wards.
    Best-effort: import failures and publish exceptions are swallowed
    so the rendering hot path stays crash-safe.
    """
    if not audio:
        return
    try:
        from shared.ward_fx_bus import FXEvent, get_bus
    except Exception:
        log.debug("ward_fx_bus import failed; skipping audio publish", exc_info=True)
        return
    now = time.monotonic()

    kick_strength = float(audio.get("onset_kick", 0.0))
    last_kick = getattr(compositor, "_fx_ward_kick_last_pub", 0.0)
    if kick_strength >= _AUDIO_KICK_FX_THRESHOLD and (now - last_kick) >= _AUDIO_KICK_FX_COOLDOWN_S:
        compositor._fx_ward_kick_last_pub = now
        try:
            # FXEvent.__post_init__ clamps strength to [0,1] (single canonical site).
            get_bus().publish_fx(FXEvent(kind="audio_kick_onset", strength=kick_strength))
        except Exception:
            log.debug("ward_fx_bus publish_fx (audio_kick_onset) failed", exc_info=True)

    mixer_energy = float(audio.get("mixer_energy", 0.0))
    last_spike = getattr(compositor, "_fx_ward_spike_last_pub", 0.0)
    if (
        mixer_energy >= _INTENSITY_SPIKE_FX_THRESHOLD
        and (now - last_spike) >= _INTENSITY_SPIKE_FX_COOLDOWN_S
    ):
        compositor._fx_ward_spike_last_pub = now
        try:
            # FXEvent.__post_init__ clamps strength to [0,1] (single canonical site).
            get_bus().publish_fx(FXEvent(kind="intensity_spike", strength=mixer_energy))
        except Exception:
            log.debug("ward_fx_bus publish_fx (intensity_spike) failed", exc_info=True)
