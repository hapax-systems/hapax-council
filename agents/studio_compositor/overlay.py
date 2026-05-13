"""Cairo overlay rendering for the compositor."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)

# Gruvbox-hard-dark #282828 as Cairo RGB floats (0-1).
_OBSCURE_R = 40.0 / 255.0
_OBSCURE_G = 40.0 / 255.0
_OBSCURE_B = 40.0 / 255.0


def _env_enabled(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def overlay_zone_manager_draw_enabled() -> bool:
    return _env_enabled("HAPAX_OVERLAY_ZONE_MANAGER_DRAW_ENABLED", default=True)


def pre_fx_layout_draw_enabled() -> bool:
    return _env_enabled("HAPAX_PRE_FX_LAYOUT_DRAW_ENABLED", default=True)


def sierpinski_base_overlay_enabled() -> bool:
    """Return whether the legacy full-canvas Sierpinski/GEAL base overlay may run."""
    return _env_enabled("HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED", default=True)


def _paint_face_obscure_rects(compositor: Any, cr: Any) -> None:
    """Paint Gruvbox-dark rectangles over detected face regions.

    Reads normalized bboxes from the snapshot-branch detection cache and
    transforms them to composite tile coordinates. Runs every frame at
    negligible cost (a few Cairo rectangle fills).
    """
    from agents.studio_compositor.face_obscure_integration import get_live_bboxes
    from shared.face_obscure_policy import FaceObscurePolicy, resolve_policy

    policy = resolve_policy()
    if policy is FaceObscurePolicy.DISABLED:
        return

    live = get_live_bboxes()
    if not live:
        return

    tile_layout = getattr(compositor, "_tile_layout", None)
    if not tile_layout:
        return

    cr.save()
    cr.set_source_rgb(_OBSCURE_R, _OBSCURE_G, _OBSCURE_B)

    for role, norm_bboxes in live.items():
        if not norm_bboxes:
            continue
        tile = tile_layout.get(role)
        if tile is None:
            continue
        for nx1, ny1, nx2, ny2 in norm_bboxes:
            x = tile.x + nx1 * tile.w
            y = tile.y + ny1 * tile.h
            w = (nx2 - nx1) * tile.w
            h = (ny2 - ny1) * tile.h
            cr.rectangle(x, y, w, h)
            cr.fill()

    cr.restore()


def on_overlay_caps_changed(compositor: Any, overlay: Any, caps: Any) -> None:
    """Called when cairooverlay negotiates caps -- cache canvas size."""
    s = caps.get_structure(0)
    w = s.get_int("width")
    h = s.get_int("height")
    if w[0] and h[0]:
        compositor._overlay_canvas_size = (w[1], h[1])
    compositor._overlay_cache_surface = None


def on_draw(compositor: Any, overlay: Any, cr: Any, timestamp: int, duration: int) -> None:
    """Cairo draw callback -- renders Sierpinski triangle + Pango zone overlays."""
    if not compositor.config.overlay_enabled:
        return

    canvas_w, canvas_h = compositor._overlay_canvas_size

    if sierpinski_base_overlay_enabled():
        # Sierpinski triangle with video content (drawn BEFORE GL effects apply)
        sierpinski = getattr(compositor, "_sierpinski_renderer", None)
        if sierpinski is not None:
            # Feed audio energy for reactive line width
            if hasattr(compositor, "_cached_audio"):
                sierpinski.set_audio_energy(compositor._cached_audio.get("mixer_energy", 0.0))
            # Sync active slot from loader to renderer
            loader = getattr(compositor, "_sierpinski_loader", None)
            if loader is not None:
                sierpinski.set_active_slot(loader._active_slot)
            sierpinski.draw(cr, canvas_w, canvas_h)

        # GEAL (Grounding Expression Anchoring Layer) — extends Sierpinski
        # with voice halos + stance depth + grounding extrusions. Renders
        # ON TOP of Sierpinski so its additive halos + overlays layer onto
        # the same main-layer cairooverlay. No-op when HAPAX_GEAL_ENABLED
        # is unset; the gate lives inside render() so cost is essentially
        # zero in the disabled path.
        geal = getattr(compositor, "_geal_source", None)
        if geal is not None:
            state: dict[str, Any] = {}
            cached_audio = getattr(compositor, "_cached_audio", None)
            if cached_audio is not None:
                state["tts_active"] = cached_audio.get("tts_active", False)
            geal.render(cr, canvas_w, canvas_h, time.monotonic(), state)

    # Render content overlay zones (markdown/ANSI from Obsidian via Pango)
    if overlay_zone_manager_draw_enabled() and hasattr(compositor, "_overlay_zone_manager"):
        compositor._overlay_zone_manager.render(cr, canvas_w, canvas_h)

    # FINDING-W (ef7b-179, 2026-04-24): substrate layout assignments —
    # any ``render_stage="pre_fx"`` binding — are blitted on the BASE
    # cairooverlay BEFORE the glfeedback shader chain so shaders can
    # decorate them. Chrome wards remain on the post-FX callback. The
    # default layout ships chrome-only so this call is a no-op until
    # a session or layout opts substrate assignments in.
    if pre_fx_layout_draw_enabled():
        from agents.studio_compositor.fx_chain import pre_fx_draw_from_layout

        pre_fx_draw_from_layout(compositor, cr)

    # Face obscure: paint Gruvbox-dark rects LAST in the base overlay so no
    # base-layer renderer can reintroduce recognizable camera pixels over the
    # anti-parasocial mask.
    _paint_face_obscure_rects(compositor, cr)
