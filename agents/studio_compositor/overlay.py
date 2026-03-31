"""Cairo overlay rendering for the compositor."""

from __future__ import annotations

from typing import Any

from .visual_layer import render_visual_layer


def on_overlay_caps_changed(compositor: Any, overlay: Any, caps: Any) -> None:
    """Called when cairooverlay negotiates caps -- cache canvas size."""
    s = caps.get_structure(0)
    w = s.get_int("width")
    h = s.get_int("height")
    if w[0] and h[0]:
        compositor._overlay_canvas_size = (w[1], h[1])
    compositor._overlay_cache_surface = None


def on_draw(compositor: Any, overlay: Any, cr: Any, timestamp: int, duration: int) -> None:
    """Cairo draw callback -- renders text overlays on the composited frame."""
    if not compositor.config.overlay_enabled:
        return

    import cairo  # type: ignore[import-untyped]

    canvas_w, canvas_h = compositor._overlay_canvas_size

    with compositor._overlay_state._lock:
        state = compositor._overlay_state._data

    with compositor._camera_status_lock:
        cam_hash = "|".join(f"{r}:{s}" for r, s in sorted(compositor._camera_status.items()))

    cur_ts = state.timestamp
    cache_valid = (
        compositor._overlay_cache_surface is not None
        and cur_ts == compositor._overlay_cache_timestamp
        and cam_hash == compositor._overlay_cache_cam_hash
    )

    if not cache_valid:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
        ctx = cairo.Context(surf)
        ctx.set_operator(cairo.OPERATOR_CLEAR)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        pad = 4

        _draw_camera_labels(compositor, ctx, state, pad)
        _draw_flow_state(ctx, state, canvas_w)
        _draw_activity_tags(ctx, state, canvas_w, canvas_h)
        _draw_audio_meter(ctx, state, canvas_w, canvas_h)
        _draw_consent_banner(ctx, state, compositor.config.recording.enabled, canvas_w, canvas_h)

        compositor._overlay_cache_surface = surf
        compositor._overlay_cache_timestamp = cur_ts
        compositor._overlay_cache_cam_hash = cam_hash

    cr.set_source_surface(compositor._overlay_cache_surface, 0, 0)
    cr.paint()

    render_visual_layer(compositor, cr, canvas_w, canvas_h)


def _draw_camera_labels(compositor: Any, ctx: Any, state: Any, pad: int) -> None:
    """Draw per-camera role labels and consent badges."""
    for role, tile in compositor._tile_layout.items():
        ctx.set_font_size(14)
        text = role
        extents = ctx.text_extents(text)
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.6)
        ctx.rectangle(tile.x + pad, tile.y + pad, extents.width + pad * 2, extents.height + pad * 2)
        ctx.fill()
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.9)
        ctx.move_to(tile.x + pad * 2, tile.y + pad + extents.height + pad)
        ctx.show_text(text)

        if not compositor.config.recording.enabled:
            badge_color, badge_text = (0.5, 0.5, 0.5, 0.7), "NO-REC"
        elif state.consent_phase == "guest_detected":
            badge_color, badge_text = (1.0, 0.9, 0.2, 0.9), "DETECTING"
        elif state.consent_phase == "consent_pending":
            badge_color, badge_text = (1.0, 0.6, 0.1, 0.9), "PENDING"
        elif state.consent_phase == "consent_refused":
            badge_color, badge_text = (0.9, 0.2, 0.1, 0.9), "PAUSED"
        elif state.persistence_allowed:
            badge_color, badge_text = (0.2, 0.8, 0.2, 0.9), "REC"
        else:
            badge_color, badge_text = (0.9, 0.3, 0.1, 0.9), "PAUSED"

        ctx.set_font_size(12)
        be = ctx.text_extents(badge_text)
        bx = tile.x + tile.w - be.width - pad * 3
        by = tile.y + pad
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.6)
        ctx.rectangle(bx, by, be.width + pad * 2, be.height + pad * 2)
        ctx.fill()
        ctx.set_source_rgba(*badge_color)
        ctx.move_to(bx + pad, by + be.height + pad)
        ctx.show_text(badge_text)

        with compositor._camera_status_lock:
            cam_status = compositor._camera_status.get(role, "unknown")
        if cam_status == "offline":
            ctx.set_font_size(24)
            ctx.set_source_rgba(1.0, 0.3, 0.3, 0.8)
            ot = "OFFLINE"
            oe = ctx.text_extents(ot)
            ctx.move_to(tile.x + (tile.w - oe.width) / 2, tile.y + (tile.h + oe.height) / 2)
            ctx.show_text(ot)


def _draw_flow_state(ctx: Any, state: Any, canvas_w: int) -> None:
    if not state.flow_state:
        return
    ctx.set_font_size(20)
    flow_text = f"FLOW: {state.flow_state.upper()} ({state.flow_score:.0%})"
    fe = ctx.text_extents(flow_text)
    fx = (canvas_w - fe.width) / 2
    fy = 8
    ctx.set_source_rgba(0.0, 0.0, 0.0, 0.6)
    ctx.rectangle(fx - 6, fy, fe.width + 12, fe.height + 12)
    ctx.fill()
    if state.flow_state == "active":
        ctx.set_source_rgba(0.2, 1.0, 0.4, 0.95)
    elif state.flow_state == "warming":
        ctx.set_source_rgba(1.0, 0.9, 0.2, 0.95)
    else:
        ctx.set_source_rgba(0.8, 0.8, 0.8, 0.95)
    ctx.move_to(fx, fy + fe.height + 4)
    ctx.show_text(flow_text)


def _draw_activity_tags(ctx: Any, state: Any, canvas_w: int, canvas_h: int) -> None:
    if not (state.production_activity or state.music_genre):
        return
    ctx.set_font_size(14)
    tags = " | ".join(filter(None, [state.production_activity, state.music_genre]))
    te = ctx.text_extents(tags)
    tx, ty = 8, canvas_h - 28
    ctx.set_source_rgba(0.0, 0.0, 0.0, 0.5)
    ctx.rectangle(tx - 4, ty - te.height - 4, te.width + 8, te.height + 8)
    ctx.fill()
    ctx.set_source_rgba(0.9, 0.9, 0.9, 0.85)
    ctx.move_to(tx, ty)
    ctx.show_text(tags)


def _draw_audio_meter(ctx: Any, state: Any, canvas_w: int, canvas_h: int) -> None:
    if state.audio_energy_rms <= 0:
        return
    bar_h = 4
    bar_w = int(canvas_w * min(state.audio_energy_rms * 10, 1.0))
    ctx.set_source_rgba(0.3, 0.8, 0.3, 0.7)
    ctx.rectangle(0, canvas_h - bar_h, bar_w, bar_h)
    ctx.fill()


def _draw_consent_banner(
    ctx: Any, state: Any, recording_enabled: bool, canvas_w: int, canvas_h: int
) -> None:
    if state.persistence_allowed or not recording_enabled:
        return
    ctx.set_font_size(18)
    banner = "RECORDING PAUSED \u2014 CONSENT REQUIRED"
    be = ctx.text_extents(banner)
    bx = (canvas_w - be.width) / 2
    by = canvas_h - 50
    ctx.set_source_rgba(0.0, 0.0, 0.0, 0.7)
    ctx.rectangle(bx - 8, by - be.height - 6, be.width + 16, be.height + 12)
    ctx.fill()
    ctx.set_source_rgba(1.0, 0.3, 0.1, 0.95)
    ctx.move_to(bx, by)
    ctx.show_text(banner)
