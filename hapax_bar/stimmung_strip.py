"""Stimmung strip — 4px ambient color gradient at screen edge.

Breathes with operator heartbeat, ghosts previous state, distorts edge
when stressed. This is the system's vital sign rendered as peripheral color.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import TYPE_CHECKING

import cairo  # noqa: TC002
from gi.repository import GLib, Gtk

if TYPE_CHECKING:
    from hapax_bar.stimmung import StimmungState

# Dimension → (gradient_position, palette_color_key)
DIMENSION_POSITIONS: dict[str, tuple[float, str]] = {
    "health": (0.0, "red_400"),
    "resource_pressure": (0.18, "orange_400"),
    "error_rate": (0.33, "red_400"),
    "processing_throughput": (0.48, "yellow_400"),
    "perception_confidence": (0.60, "yellow_400"),
    "llm_cost_pressure": (0.72, "orange_400"),
}

# Small particles for the strip
_PARTICLE_COUNT = 12
_particles = [(random.random(), random.random()) for _ in range(_PARTICLE_COUNT)]


class StimmungStrip(Gtk.DrawingArea):
    """4px color strip + 4px penumbra at a screen edge.

    Args:
        edge: "top" or "bottom" — controls penumbra direction.
    """

    def __init__(self, edge: str = "top") -> None:
        super().__init__(css_classes=["stimmung-strip"])
        self.set_content_height(8)  # 4px strip + 4px penumbra
        self.set_hexpand(True)

        self._edge = edge
        self._t: float = 0.0
        self._stance: str = "nominal"
        self._dimensions: dict = {}
        self._heart_rate: int = 0
        self._recording: bool = False
        self._agent_speed: float = 0.1
        self._history: deque[dict] = deque(maxlen=15)  # 30s at 2s intervals

        self.set_draw_func(self._draw, None)
        GLib.timeout_add(100, self._tick)  # ~60fps

    def _tick(self) -> bool:
        import time

        self._t = time.monotonic()
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def update_stimmung(self, state: StimmungState) -> None:
        """Called by stimmung reader on state change."""
        # Store history snapshot for ghosting
        self._history.append(
            {
                "dimensions": dict(state.dimensions),
                "stance": state.stance,
                "time": self._t,
            }
        )
        self._stance = state.stance
        self._dimensions = state.dimensions
        self._heart_rate = state.heart_rate
        self._recording = state.recording
        self._agent_speed = max(0.1, getattr(state, "_agent_speed", 0.1))

    def _draw(
        self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int, _data: object
    ) -> None:
        if w <= 0 or h <= 0:
            return

        from hapax_bar.palette import get_palette

        pal = get_palette()
        t = self._t
        bg_r, bg_g, bg_b = pal["bg"]
        strip_h = 4  # visible strip height
        penumbra_h = h - strip_h  # fade zone

        # Determine strip and penumbra y positions based on edge
        if self._edge == "top":
            strip_y = 0
            penumbra_y = strip_h
        else:
            strip_y = penumbra_h
            penumbra_y = 0

        # --- Breathing opacity (heartbeat-synced §6.1 cadence) ---
        if self._heart_rate > 30:
            period = 60.0 / self._heart_rate
            breath_alpha = 0.7 + 0.3 * math.sin(t * 2 * math.pi / period)
        else:
            # Fallback: severity-driven
            periods = {"nominal": 12.0, "cautious": 8.0, "degraded": 4.0, "critical": 0.6}
            period = periods.get(self._stance, 12.0)
            breath_alpha = 0.85 + 0.15 * math.sin(t * 2 * math.pi / period)

        # --- Build gradient colors from dimensions ---
        def _gradient_color(
            dims: dict, position: float, color_key: str
        ) -> tuple[float, float, float]:
            value = dims.get(color_key.replace("_400", ""), {})
            if isinstance(value, dict):
                value = value.get("value", 0.0)
            else:
                value = 0.0
            # Look up by dimension name, not color key
            return bg_r, bg_g, bg_b  # fallback

        # Compute strip color at each x position
        def _strip_color_at(x_pct: float) -> tuple[float, float, float, float]:
            r, g, b = bg_r, bg_g, bg_b
            for dim_name, (position, color_key) in DIMENSION_POSITIONS.items():
                value = self._dimensions.get(dim_name, {}).get("value", 0.0)
                if dim_name == "processing_throughput":
                    value = 0.0
                elif dim_name == "perception_confidence":
                    value = max(0, 0.5 - value)
                # Gaussian influence: dimension affects nearby gradient positions
                dist = abs(x_pct - position)
                influence = math.exp(-(dist * dist) / 0.02) * min(value * 2.0, 1.0)
                cr_c, cg_c, cb_c = pal[color_key]
                r += (cr_c - bg_r) * influence * 0.6
                g += (cg_c - bg_g) * influence * 0.6
                b += (cb_c - bg_b) * influence * 0.6
            return r, g, b, breath_alpha

        # --- Temporal ghost (§6.4 decay) ---
        if self._history:
            oldest = self._history[0]
            age = t - oldest.get("time", t)
            if age > 0 and age < 30:
                ghost_alpha = 0.15 * (1 - age / 30)
                # Draw ghost gradient (simplified: single color from stance)
                ghost_stance = oldest.get("stance", "nominal")
                ghost_colors = {
                    "nominal": pal["bg"],
                    "cautious": pal["yellow_400"],
                    "degraded": pal["orange_400"],
                    "critical": pal["red_400"],
                }
                gr, gg, gb = ghost_colors.get(ghost_stance, pal["bg"])
                cr.set_source_rgba(gr, gg, gb, ghost_alpha)
                cr.rectangle(0, strip_y, w, strip_h)
                cr.fill()

        # --- Main gradient strip ---
        pat = cairo.LinearGradient(0, 0, w, 0)
        steps = 12
        for i in range(steps + 1):
            x_pct = i / steps
            r, g, b, a = _strip_color_at(x_pct)
            pat.add_color_stop_rgba(x_pct, r, g, b, a)
        cr.set_source(pat)

        # --- Edge distortion (§6.5 ambient motion) ---
        severity_amp = {"nominal": 0, "cautious": 1, "degraded": 2, "critical": 3}
        amp = severity_amp.get(self._stance, 0)
        wavelength = max(50, 200 - amp * 50)
        speed = 0.5 + amp * 0.5

        if amp > 0 and self._edge == "top":
            # Distorted bottom edge of strip
            cr.move_to(0, strip_y)
            cr.line_to(w, strip_y)
            cr.line_to(w, strip_y + strip_h)
            for x in range(w, -1, -4):
                dy = amp * math.sin(x / wavelength * 2 * math.pi + t * speed)
                cr.line_to(x, strip_y + strip_h + dy)
            cr.close_path()
            cr.fill()
        elif amp > 0 and self._edge == "bottom":
            # Distorted top edge of strip
            cr.move_to(0, strip_y + strip_h)
            cr.line_to(w, strip_y + strip_h)
            for x in range(w, -1, -4):
                dy = amp * math.sin(x / wavelength * 2 * math.pi + t * speed)
                cr.line_to(x, strip_y - dy)
            cr.line_to(0, strip_y)
            cr.close_path()
            cr.fill()
        else:
            cr.rectangle(0, strip_y, w, strip_h)
            cr.fill()

        # --- Consent beacon: full-strip red tint ---
        if self._recording:
            rr, rg, rb = pal["red_400"]
            cr.set_source_rgba(rr, rg, rb, 0.4 + 0.2 * math.sin(t * 4))
            cr.rectangle(0, strip_y, w, strip_h)
            cr.fill()

        # --- Penumbra: fade from strip color to transparent ---
        pen_pat = cairo.LinearGradient(
            0,
            strip_y,
            0,
            strip_y
            + (strip_h if self._edge == "top" else -strip_h)
            + penumbra_h * (1 if self._edge == "top" else -1),
        )
        if self._edge == "top":
            pen_pat = cairo.LinearGradient(0, strip_y + strip_h, 0, strip_y + strip_h + penumbra_h)
        else:
            pen_pat = cairo.LinearGradient(0, strip_y, 0, strip_y - penumbra_h)

        # Glow color from stance (§3.4)
        glow_colors = {
            "nominal": pal["bg"],
            "cautious": pal["yellow_400"],
            "degraded": pal["orange_400"],
            "critical": pal["red_400"],
        }
        glow_r, glow_g, glow_b = glow_colors.get(self._stance, pal["bg"])
        glow_opacity = {"nominal": 0.0, "cautious": 0.06, "degraded": 0.10, "critical": 0.15}
        glow_a = glow_opacity.get(self._stance, 0.0) * breath_alpha

        pen_pat.add_color_stop_rgba(0, glow_r, glow_g, glow_b, glow_a)
        pen_pat.add_color_stop_rgba(1, glow_r, glow_g, glow_b, 0.0)
        cr.set_source(pen_pat)
        if self._edge == "top":
            cr.rectangle(0, strip_y + strip_h, w, penumbra_h)
        else:
            cr.rectangle(0, penumbra_y, w, penumbra_h)
        cr.fill()

        # --- Micro-particles ---
        speed_mult = max(0.1, self._agent_speed) * 20.0
        pr, pg, pb = pal["green_400"]
        for i in range(_PARTICLE_COUNT):
            bx, _ = _particles[i]
            px = (bx * w + t * speed_mult + i * 213) % w
            py = strip_y + strip_h / 2 + math.sin(t * 1.2 + i) * 1.5
            alpha = (0.25 + 0.15 * math.sin(t * 2 + i)) * breath_alpha
            cr.set_source_rgba(pr, pg, pb, alpha)
            cr.arc(px, py, 1.5, 0, 2 * math.pi)
            cr.fill()
