"""token_pole.py — Golden Spiral token tracker over Vitruvian Man.

Da Vinci's Vitruvian Man (1490, public domain) as background.
A golden spiral overlaid on the figure — the token follows the spiral
path from outside in. Cute, colorful token contrasts the somber
Renaissance geometry.

Upper-left quadrant of the frame.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LEDGER_FILE = Path("/dev/shm/hapax-compositor/token-ledger.json")
VITRUVIAN_PATH = Path(__file__).parent.parent.parent / "assets" / "vitruvian_man_overlay.png"

# Layout — upper left quadrant
OVERLAY_X = 20
OVERLAY_Y = 20
OVERLAY_SIZE = 300  # display size of the vitruvian background

# Spiral is centered on the figure's navel (golden ratio center of the human body)
# Relative to the overlay image (0-1 normalized)
SPIRAL_CENTER_X = 0.50
SPIRAL_CENTER_Y = 0.52  # navel is slightly below center
SPIRAL_MAX_R = 0.45  # relative to overlay size

NUM_POINTS = 250
PHI = (1 + math.sqrt(5)) / 2

# Colors — candy-bright against Renaissance sepia
COLOR_SPIRAL_LINE = (0.6, 0.45, 0.7, 0.2)
COLOR_TRAIL = [
    (1.0, 0.4, 0.6),  # hot pink
    (1.0, 0.6, 0.2),  # tangerine
    (1.0, 0.9, 0.3),  # sunshine
    (0.4, 1.0, 0.6),  # mint
    (0.3, 0.8, 1.0),  # sky blue
    (0.7, 0.4, 1.0),  # violet
    (1.0, 0.5, 0.8),  # bubblegum
]
COLOR_GLYPH_OUTER = (1.0, 0.45, 0.7)
COLOR_GLYPH = (1.0, 0.9, 0.4)
COLOR_GLYPH_INNER = (1.0, 1.0, 0.85)
COLOR_GLYPH_CHEEK = (1.0, 0.55, 0.55, 0.5)
COLOR_TEXT = (0.95, 0.9, 0.95, 0.9)
COLOR_EXPLOSION = [
    (1.0, 0.4, 0.6),
    (1.0, 0.9, 0.3),
    (0.4, 1.0, 0.6),
    (0.3, 0.8, 1.0),
    (1.0, 0.6, 0.2),
    (0.7, 0.4, 1.0),
    (1.0, 0.5, 0.8),
    (0.5, 1.0, 0.9),
]


def _build_spiral(cx: float, cy: float, max_r: float, n: int) -> list[tuple[float, float]]:
    """Golden spiral from outside in, in pixel coordinates."""
    points = []
    max_turns = 3.0
    max_theta = max_turns * 2 * math.pi
    for i in range(n):
        t = i / (n - 1)
        theta = max_theta * (1 - t)
        r = max_r * math.exp(-0.2 * theta)
        x = cx + r * math.cos(theta + 0.5)  # offset so spiral starts upper-right
        y = cy + r * math.sin(theta + 0.5)
        points.append((x, y))
    return points


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "alpha", "size", "born")

    def __init__(self, x: float, y: float) -> None:
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(3, 14)
        self.x = x
        self.y = y
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - random.uniform(1, 4)
        self.color = random.choice(COLOR_EXPLOSION)
        self.alpha = 1.0
        self.size = random.uniform(3, 10)
        self.born = time.monotonic()

    def tick(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.2
        self.vx *= 0.97
        self.vy *= 0.97
        age = time.monotonic() - self.born
        self.alpha = max(0, 1.0 - age / 1.5)
        self.size *= 0.98
        return self.alpha > 0.03


class TokenPole:
    def __init__(self) -> None:
        self._position: float = 0.0
        self._target_position: float = 0.0
        self._explosions: int = 0
        self._total_tokens: int = 0
        self._threshold: int = 0
        self._particles: list[Particle] = []
        self._last_read: float = 0
        self._last_explosion_count: int = 0
        self._pulse: float = 0.0
        self._bg_surface: Any = None
        self._bg_loaded = False
        # Build spiral in pixel coordinates
        cx = OVERLAY_X + OVERLAY_SIZE * SPIRAL_CENTER_X
        cy = OVERLAY_Y + OVERLAY_SIZE * SPIRAL_CENTER_Y
        max_r = OVERLAY_SIZE * SPIRAL_MAX_R
        self._spiral = _build_spiral(cx, cy, max_r, NUM_POINTS)

    def tick(self) -> None:
        now = time.monotonic()
        if now - self._last_read > 0.5:
            self._last_read = now
            self._read_ledger()
        diff = self._target_position - self._position
        self._position += diff * 0.06
        self._pulse += 0.1
        self._particles = [p for p in self._particles if p.tick()]

    def _read_ledger(self) -> None:
        try:
            if LEDGER_FILE.exists():
                data = json.loads(LEDGER_FILE.read_text())
                self._target_position = data.get("pole_position", 0.0)
                self._total_tokens = data.get("total_tokens", 0)
                active = max(1, data.get("active_viewers", 1))
                self._threshold = int(5000 * math.log2(1 + math.log2(1 + active)))
                new_explosions = data.get("explosions", 0)
                if new_explosions > self._last_explosion_count and self._last_explosion_count > 0:
                    self._spawn_explosion()
                self._last_explosion_count = new_explosions
                self._explosions = new_explosions
        except (json.JSONDecodeError, OSError):
            pass

    def _spawn_explosion(self) -> None:
        cx = OVERLAY_X + OVERLAY_SIZE * SPIRAL_CENTER_X
        cy = OVERLAY_Y + OVERLAY_SIZE * SPIRAL_CENTER_Y
        for _ in range(60):
            self._particles.append(Particle(cx, cy))

    def _load_bg(self, cr: Any) -> None:
        """Load Vitruvian Man as cairo surface (once)."""
        if self._bg_loaded:
            return
        self._bg_loaded = True
        try:
            if VITRUVIAN_PATH.exists():
                import cairo

                self._bg_surface = cairo.ImageSurface.create_from_png(str(VITRUVIAN_PATH))
                log.info(
                    "Vitruvian Man loaded (%dx%d)",
                    self._bg_surface.get_width(),
                    self._bg_surface.get_height(),
                )
        except Exception:
            # JPEG fallback via PIL → PNG temp
            try:
                from PIL import Image

                img = Image.open(str(VITRUVIAN_PATH)).convert("RGBA")
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    img.save(f.name, format="PNG")
                    import cairo

                    self._bg_surface = cairo.ImageSurface.create_from_png(f.name)
            except Exception:
                log.warning("Failed to load Vitruvian Man background")

    def draw(self, cr: Any) -> None:
        self._load_bg(cr)

        # --- Dark backing card ---
        cr.set_source_rgba(0.05, 0.04, 0.08, 0.88)
        # Rounded rectangle
        _r = 12
        cr.new_sub_path()
        cr.arc(OVERLAY_X + OVERLAY_SIZE - _r, OVERLAY_Y + _r, _r, -math.pi / 2, 0)
        cr.arc(OVERLAY_X + OVERLAY_SIZE - _r, OVERLAY_Y + OVERLAY_SIZE - _r, _r, 0, math.pi / 2)
        cr.arc(OVERLAY_X + _r, OVERLAY_Y + OVERLAY_SIZE - _r, _r, math.pi / 2, math.pi)
        cr.arc(OVERLAY_X + _r, OVERLAY_Y + _r, _r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.fill()

        # --- Vitruvian Man (transparent PNG, full alpha — ink lines pop) ---
        if self._bg_surface is not None:
            cr.save()
            sw = self._bg_surface.get_width()
            sh = self._bg_surface.get_height()
            scale = OVERLAY_SIZE / max(sw, sh) if max(sw, sh) > 0 else 1
            cr.translate(OVERLAY_X, OVERLAY_Y)
            cr.scale(scale, scale)
            cr.set_source_surface(self._bg_surface, 0, 0)
            cr.paint_with_alpha(1.0)
            cr.restore()

        # --- Spiral guide line ---
        cr.set_source_rgba(*COLOR_SPIRAL_LINE)
        cr.set_line_width(1.0)
        for i, (x, y) in enumerate(self._spiral):
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        # --- Rainbow trail ---
        idx = int(self._position * (NUM_POINTS - 1))
        if idx > 1:
            cr.set_line_width(3.5)
            num_c = len(COLOR_TRAIL)
            for i in range(1, idx):
                progress = i / idx
                ci = progress * (num_c - 1)
                c0 = COLOR_TRAIL[int(ci) % num_c]
                c1 = COLOR_TRAIL[(int(ci) + 1) % num_c]
                f = ci - int(ci)
                r = c0[0] + (c1[0] - c0[0]) * f
                g = c0[1] + (c1[1] - c0[1]) * f
                b = c0[2] + (c1[2] - c0[2]) * f
                alpha = 0.15 + 0.65 * (progress**1.5)
                cr.set_source_rgba(r, g, b, alpha)
                x0, y0 = self._spiral[i - 1]
                x, y = self._spiral[i]
                cr.move_to(x0, y0)
                cr.line_to(x, y)
                cr.stroke()

        # --- Token glyph ---
        if idx < len(self._spiral):
            gx, gy = self._spiral[idx]
        else:
            gx = OVERLAY_X + OVERLAY_SIZE * SPIRAL_CENTER_X
            gy = OVERLAY_Y + OVERLAY_SIZE * SPIRAL_CENTER_Y

        pulse_r = math.sin(self._pulse) * 2
        bounce_y = math.sin(self._pulse * 1.7) * 1.5
        glyph_r = 11 + pulse_r

        # Sparkle trail
        for i in range(1, 4):
            trail_idx = max(0, idx - i * 5)
            if trail_idx < len(self._spiral):
                tx, ty = self._spiral[trail_idx]
                sr = (4 - i) * 1.5
                cr.set_source_rgba(1.0, 1.0, 0.8, 0.6 - i * 0.15)
                cr.arc(tx, ty, sr, 0, 2 * math.pi)
                cr.fill()

        # Pink outer glow
        cr.set_source_rgba(*COLOR_GLYPH_OUTER, 0.25)
        cr.arc(gx, gy + bounce_y, glyph_r + 8, 0, 2 * math.pi)
        cr.fill()

        # Pink ring
        cr.set_source_rgba(*COLOR_GLYPH_OUTER, 0.7)
        cr.set_line_width(2.5)
        cr.arc(gx, gy + bounce_y, glyph_r + 2, 0, 2 * math.pi)
        cr.stroke()

        # Yellow body
        cr.set_source_rgba(*COLOR_GLYPH, 0.95)
        cr.arc(gx, gy + bounce_y, glyph_r, 0, 2 * math.pi)
        cr.fill()

        # Cream center
        cr.set_source_rgba(*COLOR_GLYPH_INNER, 0.85)
        cr.arc(gx, gy + bounce_y, glyph_r * 0.55, 0, 2 * math.pi)
        cr.fill()

        # Rosy cheeks
        cr.set_source_rgba(*COLOR_GLYPH_CHEEK)
        cr.arc(gx - 5, gy + bounce_y + 2, 3, 0, 2 * math.pi)
        cr.fill()
        cr.arc(gx + 5, gy + bounce_y + 2, 3, 0, 2 * math.pi)
        cr.fill()

        # Eyes
        cr.set_source_rgba(0.15, 0.1, 0.0, 1.0)
        cr.arc(gx - 3.5, gy + bounce_y - 2, 1.5, 0, 2 * math.pi)
        cr.fill()
        cr.arc(gx + 3.5, gy + bounce_y - 2, 1.5, 0, 2 * math.pi)
        cr.fill()

        # Smile
        cr.set_line_width(1.2)
        cr.arc(gx, gy + bounce_y + 1, 3.5, 0.2, math.pi - 0.2)
        cr.stroke()

        # --- Labels ---
        cr.set_source_rgba(*COLOR_TEXT)
        cr.select_font_face("monospace", 0, 1)
        cr.set_font_size(11)

        # Goal at top-right of overlay
        if self._threshold > 0:
            cr.move_to(OVERLAY_X + OVERLAY_SIZE + 8, OVERLAY_Y + 15)
            cr.show_text(self._format_tokens(self._threshold))

        # Explosion count
        if self._explosions > 0:
            cr.set_font_size(10)
            cr.move_to(OVERLAY_X + OVERLAY_SIZE + 8, OVERLAY_Y + 30)
            cr.show_text(f"x{self._explosions}")

        # Token count at bottom-left of overlay
        cr.select_font_face("monospace", 0, 0)
        cr.set_font_size(11)
        if self._total_tokens > 0:
            cr.move_to(OVERLAY_X, OVERLAY_Y + OVERLAY_SIZE + 18)
            cr.show_text(self._format_tokens(self._total_tokens))

        # --- Particles ---
        for p in self._particles:
            cr.set_source_rgba(*p.color, p.alpha)
            cr.arc(p.x, p.y, p.size, 0, 2 * math.pi)
            cr.fill()

    @staticmethod
    def _format_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
