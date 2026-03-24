"""Stimmung field — custom Gtk.Widget rendering ambient color field.

GPU-composited gradients via do_snapshot(), particles via Cairo.
Encodes system mood through color temperature, breathing animation,
particle drift, voice orb, and consent beacon.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk

if TYPE_CHECKING:
    from hapax_bar.stimmung import StimmungState

# Breathing parameters per stance (§6.1)
BREATHING: dict[str, tuple[float, float]] = {
    "nominal": (0.0, 0.0),
    "cautious": (8.0, 0.05),
    "degraded": (4.0, 0.10),
    "critical": (0.6, 0.15),
}

# Dimension → (gradient_position, (r, g, b) when elevated)
DIMENSION_COLORS: dict[str, tuple[float, tuple[float, float, float]]] = {
    "health": (0.0, (0.98, 0.29, 0.20)),
    "resource_pressure": (0.18, (1.0, 0.50, 0.10)),
    "error_rate": (0.33, (0.98, 0.29, 0.20)),
    "processing_throughput": (0.48, (0.98, 0.74, 0.18)),
    "perception_confidence": (0.60, (0.98, 0.74, 0.18)),
    "llm_cost_pressure": (0.72, (1.0, 0.50, 0.10)),
}

_PARTICLE_COUNT = 24
_particles = [(random.random(), random.random() * 0.6 + 0.2) for _ in range(_PARTICLE_COUNT)]


class StimmungField(Gtk.Widget):
    """Ambient color field encoding system stimmung."""

    def __init__(self) -> None:
        super().__init__(hexpand=True, css_classes=["stimmung-field"])
        self._t: float = 0.0
        self._stance: str = "nominal"
        self._dimensions: dict = {}
        self._voice_state: str = "off"
        self._consent_recording: bool = False
        self._consent_perceiving: bool = False
        self._guest_present: bool = False
        self._agent_speed: float = 0.1
        self._stress_dampen: float = 1.0
        self._bg = (0.11, 0.12, 0.13)
        self._tick_id: int | None = None
        self._seam_toggle_callback: object = None

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)
        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)

    def set_seam_toggle(self, callback: object) -> None:
        self._seam_toggle_callback = callback

    def update_stimmung(self, state: StimmungState) -> None:
        self._stance = state.stance
        self._dimensions = state.dimensions
        self._voice_state = state.voice_state if state.voice_active else "off"
        self._consent_recording = state.recording
        self._consent_perceiving = state.consent_phase not in ("no_guest", "off", "")
        self._guest_present = state.guest_present
        stress = state.operator_stress
        energy = state.operator_energy
        if stress > 0.5 or energy < 0.3:
            self._stress_dampen = max(0.5, self._stress_dampen - 0.05)
        else:
            self._stress_dampen = min(1.0, self._stress_dampen + 0.02)

    def _on_realize(self, _w: Gtk.Widget) -> None:
        self._tick_id = self.add_tick_callback(self._on_tick)

    def _on_unrealize(self, _w: Gtk.Widget) -> None:
        if self._tick_id is not None:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = None

    def _on_tick(self, _w: Gtk.Widget, fc: Gdk.FrameClock) -> bool:
        self._t = fc.get_frame_time() / 1_000_000.0
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _on_click(self, *_a: object) -> None:
        if self._seam_toggle_callback:
            self._seam_toggle_callback()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w = self.get_width()
        h = self.get_height()
        if w <= 0 or h <= 0:
            return
        rect = Graphene.Rect().init(0, 0, w, h)
        t = self._t

        # Breathing
        period, amplitude = BREATHING.get(self._stance, (0.0, 0.0))
        amplitude *= self._stress_dampen
        breath = (
            (1.0 - amplitude + amplitude * math.sin(t * 2 * math.pi / period))
            if period > 0
            else 1.0
        )
        snapshot.push_opacity(breath)

        # Gradient
        bg_r, bg_g, bg_b = self._bg
        stops = []
        first = Gsk.ColorStop()
        first.offset = 0.0
        first.color = Gdk.RGBA(red=bg_r, green=bg_g, blue=bg_b, alpha=1.0)
        stops.append(first)

        for dim_name, (position, (cr, cg, cb)) in DIMENSION_COLORS.items():
            value = self._dimensions.get(dim_name, {}).get("value", 0.0)
            if dim_name == "processing_throughput":
                value = 0.0
            elif dim_name == "perception_confidence":
                value = max(0, 0.5 - value)
            intensity = min(value * 2.0, 1.0) * self._stress_dampen
            r = bg_r + (cr - bg_r) * intensity * 0.4
            g = bg_g + (cg - bg_g) * intensity * 0.4
            b = bg_b + (cb - bg_b) * intensity * 0.4
            stop = Gsk.ColorStop()
            stop.offset = position
            stop.color = Gdk.RGBA(red=r, green=g, blue=b, alpha=1.0)
            stops.append(stop)

        last = Gsk.ColorStop()
        last.offset = 1.0
        last.color = Gdk.RGBA(red=bg_r, green=bg_g, blue=bg_b, alpha=1.0)
        stops.append(last)
        stops.sort(key=lambda s: s.offset)

        snapshot.append_linear_gradient(
            rect,
            Graphene.Point().init(0, 0),
            Graphene.Point().init(w, 0),
            stops,
        )

        # Particles + orbs via Cairo
        cr_ctx = snapshot.append_cairo(rect)
        self._draw_particles(cr_ctx, w, h, t)
        self._draw_consent_beacon(cr_ctx, h)
        self._draw_voice_orb(cr_ctx, w, h, t)

        snapshot.pop()

    def _draw_particles(self, cr: cairo.Context, w: int, h: int, t: float) -> None:
        count = int(_PARTICLE_COUNT * self._stress_dampen)
        speed = max(0.1, self._agent_speed) * 15.0
        for i in range(count):
            bx, by = _particles[i]
            px = (bx * w + t * speed + i * 107) % w
            py = by * h + 2 * math.sin(t * 0.8 + i * 1.1)
            alpha = (0.15 + 0.1 * math.sin(t * 1.5 + i)) * self._stress_dampen
            rad = cairo.RadialGradient(px, py, 0, px, py, 4)
            rad.add_color_stop_rgba(0.0, 0.7, 0.5, 0.3, alpha)
            rad.add_color_stop_rgba(1.0, 0.7, 0.5, 0.3, 0.0)
            cr.set_source(rad)
            cr.arc(px, py, 4, 0, 2 * math.pi)
            cr.fill()

    def _draw_consent_beacon(self, cr: cairo.Context, h: int) -> None:
        if self._consent_recording or self._guest_present:
            alpha = 1.0
            if self._guest_present:
                alpha = 0.7 + 0.3 * math.sin(self._t * 4)
            cr.set_source_rgba(0.98, 0.29, 0.20, alpha)
            cr.rectangle(0, 0, 8, h)
            cr.fill()
        elif self._consent_perceiving:
            cr.set_source_rgba(0.98, 0.74, 0.18, 0.4)
            cr.rectangle(0, 0, 8, h)
            cr.fill()

    def _draw_voice_orb(self, cr: cairo.Context, w: int, h: int, t: float) -> None:
        if self._voice_state == "off":
            return
        cx = w * 0.15
        cy = h / 2
        radius = 6.0

        if self._voice_state == "idle":
            r, g, b = 0.4, 0.37, 0.33
            alpha = 0.3 + 0.1 * math.sin(t * 0.5)
            cx += 2 * math.sin(t * 0.3)
        elif self._voice_state == "listening":
            r, g, b = 0.98, 0.74, 0.18
            alpha = 0.6 + 0.2 * math.sin(t * 3)
            radius *= 1.0 + 0.05 * math.sin(t * math.pi)
        elif self._voice_state in ("transcribing", "thinking", "processing"):
            r, g, b = 0.51, 0.65, 0.60
            for seg in range(3):
                angle = t * 6 + seg * 2.1
                cr.arc(cx, cy, radius, angle, angle + 1.2)
                cr.set_source_rgba(r, g, b, 0.7 * (0.5 + 0.5 * ((seg + 1) / 3)))
                cr.set_line_width(2)
                cr.stroke()
            return
        elif self._voice_state == "speaking":
            r, g, b = 0.72, 0.73, 0.15
            for ring in range(3):
                ring_r = radius + (t * 8 + ring * 5) % 15
                ring_a = max(0, 0.7 * (1 - ring_r / 20))
                cr.arc(cx, cy, ring_r, 0, 2 * math.pi)
                cr.set_source_rgba(r, g, b, ring_a)
                cr.set_line_width(1)
                cr.stroke()
            alpha = 0.8
        else:
            r, g, b = 0.4, 0.37, 0.33
            alpha = 0.2 + 0.15 * math.sin(t * 7)
            radius *= 0.8

        rad = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
        rad.add_color_stop_rgba(0.0, r, g, b, alpha)
        rad.add_color_stop_rgba(1.0, r, g, b, 0.0)
        cr.set_source(rad)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()
