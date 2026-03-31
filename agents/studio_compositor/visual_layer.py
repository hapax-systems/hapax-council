"""Visual layer zone rendering for the compositor overlay."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

VL_ZONE_COLORS: dict[str, tuple[float, float, float]] = {
    "context_time": (0.4, 0.6, 0.85),
    "governance": (0.3, 0.7, 0.7),
    "work_tasks": (0.85, 0.65, 0.3),
    "health_infra": (0.3, 0.8, 0.3),
    "profile_state": (0.9, 0.9, 0.9),
    "ambient_sensor": (0.6, 0.6, 0.7),
}

VL_ZONES: dict[str, tuple[float, float, float, float]] = {
    "context_time": (0.01, 0.03, 0.25, 0.12),
    "governance": (0.74, 0.03, 0.25, 0.12),
    "work_tasks": (0.01, 0.20, 0.18, 0.45),
    "health_infra": (0.78, 0.78, 0.21, 0.18),
    "profile_state": (0.35, 0.01, 0.30, 0.06),
    "ambient_sensor": (0.01, 0.92, 0.75, 0.06),
}

VL_LERP_RATE = 3.0
VL_TOGGLE_PATH = Path("/dev/shm/hapax-compositor/visual-layer-enabled.txt")


def rounded_rect(cr: Any, x: float, y: float, w: float, h: float, radius: float) -> None:
    """Draw a rounded rectangle path."""
    cr.new_sub_path()
    cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def render_visual_layer(compositor: Any, cr: Any, canvas_w: int, canvas_h: int) -> None:
    """Render visual layer zones with per-zone opacity interpolation."""
    import cairo  # type: ignore[import-untyped]

    try:
        if VL_TOGGLE_PATH.exists():
            if VL_TOGGLE_PATH.read_text().strip() == "false":
                return
    except OSError:
        pass

    with compositor._vl_state_lock:
        vl = compositor._vl_state

    if vl is None:
        return

    zone_opacities = vl.get("zone_opacities", {})
    signals = vl.get("signals", {})

    if not zone_opacities and not signals:
        return

    now = time.monotonic()
    dt = (
        min(now - compositor._VL_LAST_FRAME_TIME, 0.1)
        if compositor._VL_LAST_FRAME_TIME > 0
        else 0.016
    )
    compositor._VL_LAST_FRAME_TIME = now

    for zone_name, target in zone_opacities.items():
        current = compositor._vl_zone_opacities.get(zone_name, 0.0)
        if abs(current - target) < 0.01:
            compositor._vl_zone_opacities[zone_name] = target
        else:
            step = VL_LERP_RATE * dt
            if target > current:
                compositor._vl_zone_opacities[zone_name] = min(target, current + step)
            else:
                compositor._vl_zone_opacities[zone_name] = max(target, current - step)

    pad = 6
    cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

    for zone_name, (zx, zy, zw, zh) in VL_ZONES.items():
        opacity = compositor._vl_zone_opacities.get(zone_name, 0.0)
        if opacity < 0.02:
            continue

        zone_signals = signals.get(zone_name, [])
        if not zone_signals:
            continue

        x = int(zx * canvas_w)
        y = int(zy * canvas_h)
        w = int(zw * canvas_w)
        h = int(zh * canvas_h)

        r, g, b = VL_ZONE_COLORS.get(zone_name, (0.5, 0.5, 0.5))

        if zone_name == "health_infra" and zone_signals:
            max_sev = max(s.get("severity", 0) for s in zone_signals)
            if max_sev > 0.7:
                r, g, b = (0.9, 0.2, 0.1)
            elif max_sev > 0.4:
                r, g, b = (0.85, 0.65, 0.2)

        cr.set_source_rgba(0.0, 0.0, 0.0, 0.45 * opacity)
        rounded_rect(cr, x, y, w, h, 8)
        cr.fill()

        cr.set_font_size(13)
        text_y = y + pad + 13
        for sig in zone_signals[:3]:
            title = sig.get("title", "")[:40]
            if not title:
                continue

            cr.set_source_rgba(r, g, b, 0.9 * opacity)
            cr.move_to(x + pad, text_y)
            cr.show_text(title)

            detail = sig.get("detail", "")[:50]
            if detail:
                text_y += 14
                cr.set_font_size(11)
                cr.set_source_rgba(0.79, 0.82, 0.85, 0.7 * opacity)
                cr.move_to(x + pad, text_y)
                cr.show_text(detail)
                cr.set_font_size(13)

            text_y += 18
