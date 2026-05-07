"""token_pole.py — Golden Spiral token tracker over Vitruvian Man.

Da Vinci's Vitruvian Man (1490, public domain) as background. A golden
spiral overlaid on the figure — the token follows the spiral path from
outside in. Geometry is preserved pixel-for-pixel (spiral center,
navel anchor, 3 turns, 250 points) from the pre-HOMAGE revision; what
changed in #125 is purely aesthetic: the candy-rainbow palette is
replaced with the active :class:`HomagePackage`'s BitchX grammar —
Gruvbox/mIRC-grey skeleton + bright-identity accents. The rounded-
corner sepia card becomes a flat dark-terminal rectangle per HOMAGE
spec §5.5 (``rounded-corners`` is a refused anti-pattern).

Upper-left quadrant of the frame.

The per-tick logic lives in :class:`TokenPoleCairoSource`, which
conforms to the :class:`CairoSource` protocol and is driven by a
:class:`CairoSourceRunner` at 30fps on a background thread. The
pre-Phase-9 ``TokenPole`` wrapper was removed alongside the
``fx_chain._pip_draw`` legacy path in Phase 9 Task 29.
"""

from __future__ import annotations

import enum
import json
import logging
import math
import os
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .homage import get_active_package
from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo  # noqa: F401

    from shared.homage_package import HomagePackage

log = logging.getLogger(__name__)

RENDER_FPS = 30

LEDGER_FILE = Path("/dev/shm/hapax-compositor/token-ledger.json")
VITRUVIAN_PATH = Path(__file__).parent.parent.parent / "assets" / "vitruvian_man_overlay.png"

# Natural size of the token-pole source — drawn at local origin (0, 0).
# The compositor places this surface at its assigned SurfaceSchema.geometry
# rather than hardcoding a canvas-relative position. The :class:`TokenPole`
# facade blits the output at (20, 20) for the legacy ``fx_chain._pip_draw``
# path until Phase 3 of the source-registry completion epic flips the
# render loop to walk LayoutState.
NATURAL_SIZE = 300

# Geometry invariants. These define the two path modes available to the
# token pole. Operator directive 2026-04-19: default path is navel→cranium
# with the full route visible and traveled/untraveled visually contradistinct,
# explosion on cranium arrival. SPIRAL retained for regression only.
SPIRAL_CENTER_X = 0.50
SPIRAL_CENTER_Y = 0.52  # navel is slightly below center
SPIRAL_MAX_R = 0.45  # relative to overlay size

# Navel→cranium anchors measured 2026-04-20 from assets/vitruvian_man_overlay.png
# (500×500 RGBA) by sweeping alpha-row widths from the top: the head silhouette
# emerges at y≈36 (norm 0.072) where width jumps from ~124 (circle border only)
# to ~196 (head crown becoming visible). The earlier "widest row in top 1/6"
# heuristic picked y=81 (0.162) — that's the cheek/chin level, not the crown,
# producing a path that ended at the chin (operator complaint 2026-04-20).
# x-axis is effectively vertical (Δx=0.002 = within rounding) so the path is
# treated as a straight vertical line; the subtle midline arc is deferred.
NAVEL_X = SPIRAL_CENTER_X  # 0.500
NAVEL_Y = SPIRAL_CENTER_Y  # 0.520
CRANIUM_X = 0.498
CRANIUM_Y = 0.072

NUM_POINTS = 250
PHI = (1 + math.sqrt(5)) / 2


class PathMode(enum.Enum):
    """Which geometric path the token traverses."""

    SPIRAL = "spiral"
    NAVEL_TO_CRANIUM = "navel_to_cranium"


def _resolve_path_mode() -> PathMode:
    """Read ``HAPAX_TOKEN_POLE_PATH`` from env with safe fallback.

    Default is SPIRAL per operator directive 2026-05-07 (golden spiral
    with z-layer depth, path-ahead/path-traveled visual distinction).
    Set ``HAPAX_TOKEN_POLE_PATH=navel_to_cranium`` for the linear path.
    """
    raw = (os.environ.get("HAPAX_TOKEN_POLE_PATH") or "").strip().lower()
    if raw == "navel_to_cranium":
        return PathMode.NAVEL_TO_CRANIUM
    return PathMode.SPIRAL


_Z_LAYERS = 3
_Z_SCALE_STEP = 0.018
_Z_ALPHA_DECAY = 0.45
_Z_COLOR_SHIFT = 0.08


# --- Palette role names (HOMAGE spec §4.4) ---------------------------------
# The token-pole resolves all colour state through the active
# ``HomagePackage.palette`` at draw time; no hardcoded hex. The six
# roles below are the ones used by the trail gradient and the particle
# explosion. Ordered so the trail walks muted→bright via accent hops —
# a Gruvbox-monochrome skeleton with bright identity accents punching
# through, mirroring BitchX's grey-punctuation / bright-identity rule.
_TRAIL_ROLES: tuple[str, ...] = (
    "muted",
    "terminal_default",
    "accent_cyan",
    "accent_yellow",
    "accent_magenta",
    "bright",
)

# The explosion palette re-uses the accent roles plus ``bright``. All
# references are symbolic — a palette swap (e.g. consent-safe variant)
# recolours particles in flight without needing to re-emit them.
_EXPLOSION_ROLES: tuple[str, ...] = (
    "accent_cyan",
    "accent_magenta",
    "accent_yellow",
    "accent_green",
    "accent_red",
    "bright",
)


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


def _build_linear_path(size: int, n: int) -> list[tuple[float, float]]:
    """Linear navel→cranium path in pixel coordinates.

    Produces ``n`` evenly-spaced points from the navel anchor (bottom)
    to the cranium anchor (top) on the Vitruvian figure. Index 0 is the
    starting anchor (navel), index n-1 is the terminal anchor (cranium).
    """
    x0 = NAVEL_X * size
    y0 = NAVEL_Y * size
    x1 = CRANIUM_X * size
    y1 = CRANIUM_Y * size
    return [(x0 + (x1 - x0) * (i / (n - 1)), y0 + (y1 - y0) * (i / (n - 1))) for i in range(n)]


def _resolve_package() -> HomagePackage:
    """Return the active HomagePackage, or the BitchX fallback.

    The runtime returns ``None`` under the consent-safe layout
    (HOMAGE disabled per axiom ``it-irreversible-broadcast``). The
    token-pole still has to paint *something*, so we fall through to
    the baseline BitchX package — its greyscale grammar is already
    consent-safe by construction (no operator-identity accent that
    could leak into the broadcast; the consent-safe variant collapses
    all accents to the same grey).
    """
    pkg = get_active_package()
    if pkg is not None:
        return pkg
    from .homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


# --- Task #146: chat-contribution reward mechanic ---------------------------
# Gruvbox-adjacent emoji palette for the spew cascade. Kept small and
# pre-reviewed so the broadcast stays in register with the BitchX grammar
# and the #147 governance qualifier (no cheese, no manipulation).
_EMOJI_PALETTE: tuple[str, ...] = (
    "💎",  # gem (violet)
    "⚡",  # lightning (yellow)
    "🔥",  # fire (red/orange)
    "⭐",  # star
    "🌟",  # glowing star
    "💫",  # dizzy star
    "✨",  # sparkles
    "🎵",  # music note
    "🌀",  # cyclone
    "☄️",  # comet
    "💠",  # diamond with dot
    "🔷",  # blue diamond
)

# Cascade duration: 60 frames at the 10fps director cadence = 6 seconds.
# Intentionally brief per task #147 subtle-reward guidance.
EMOJI_CASCADE_FRAMES = 60


# Panel-marker grammar preserved for director-loop / overlay consumers.
# Only aggregate contributor count — never a name.
def cascade_marker_text(explosion_number: int, contributor_count: int) -> str:
    """Format the BitchX-style cascade marker.

    Shape: ``#{N} FROM {count}``. All numeric, all aggregate — the
    contributor identity is never surfaced at any scale.
    """
    return f"#{explosion_number} FROM {contributor_count}"


class EmojiSpew:
    """Single falling emoji in the cascade."""

    __slots__ = ("glyph", "x", "y", "vx", "vy", "alpha", "size", "frames")

    def __init__(self, canvas_w: int, canvas_h: int) -> None:
        self.glyph = random.choice(_EMOJI_PALETTE)
        self.x = random.uniform(0.0, float(canvas_w))
        self.y = random.uniform(-20.0, 10.0)  # spawn along top edge
        self.vx = random.uniform(-0.6, 0.6)
        self.vy = random.uniform(1.8, 3.6)
        self.alpha = 1.0
        self.size = random.uniform(16.0, 26.0)
        self.frames = 0

    def tick(self, total_frames: int) -> None:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.04  # mild gravity
        self.frames += 1
        # Linear fade from 1.0 -> 0.0 across the cascade lifetime.
        self.alpha = max(0.0, 1.0 - (self.frames / max(1, total_frames)))


class EmojiSpewEffect:
    """State + physics for the token-pole reward cascade (task #146).

    Triggered externally via :meth:`trigger`. Advances its own frame
    counter on every :meth:`tick` and produces an iterable of drawable
    emoji positions. Terminates cleanly once frames_remaining reaches
    zero — ``active`` flips false and the emoji list empties.
    """

    def __init__(
        self,
        *,
        duration_frames: int = EMOJI_CASCADE_FRAMES,
        spawn_per_tick: int = 3,
        max_emoji: int = 40,
    ) -> None:
        self.duration_frames = duration_frames
        self.spawn_per_tick = spawn_per_tick
        self.max_emoji = max_emoji
        self.active = False
        self.frames_remaining = 0
        self.emoji: list[EmojiSpew] = []
        self.explosion_number = 0
        self.contributor_count = 0

    def trigger(
        self,
        *,
        explosion_number: int,
        contributor_count: int,
    ) -> None:
        """Arm the cascade. Idempotent: a re-trigger while active restarts."""
        self.active = True
        self.frames_remaining = self.duration_frames
        self.emoji = []
        self.explosion_number = explosion_number
        self.contributor_count = contributor_count
        log.info(
            "token-pole cascade #%d armed (contributors=%d frames=%d)",
            explosion_number,
            contributor_count,
            self.duration_frames,
        )

    def tick(self, canvas_w: int, canvas_h: int) -> None:
        """Advance one frame: spawn, step, cull, maybe terminate."""
        if not self.active:
            return

        if self.frames_remaining > 0 and len(self.emoji) < self.max_emoji:
            for _ in range(self.spawn_per_tick):
                if len(self.emoji) >= self.max_emoji:
                    break
                self.emoji.append(EmojiSpew(canvas_w, canvas_h))

        for e in self.emoji:
            e.tick(self.duration_frames)

        self.emoji = [e for e in self.emoji if e.alpha > 0.02 and e.y < canvas_h + 30]

        self.frames_remaining -= 1
        if self.frames_remaining <= 0 and not self.emoji:
            self.active = False
            self.frames_remaining = 0

    def marker_text(self) -> str | None:
        """Return the BitchX grammar marker while active, else None."""
        if not self.active:
            return None
        return cascade_marker_text(self.explosion_number, self.contributor_count)


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "role_index", "alpha", "size", "born")

    def __init__(self, x: float, y: float) -> None:
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(3, 14)
        self.x = x
        self.y = y
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - random.uniform(1, 4)
        # Palette-role index; resolved at draw time so a mid-flight
        # package swap recolours particles in place.
        self.role_index = random.randrange(len(_EXPLOSION_ROLES))
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


class TokenPoleCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource implementation for the token-pole overlay.

    Owns the spiral path, animation state (position easing, pulse
    phase), particle system, ledger cache and background image. The
    runner calls :meth:`render_content` once per tick on a background
    thread — this drives the internal tick-state update (ledger I/O,
    easing, particle physics) AND the drawing, so the animation cadence
    matches the runner's target FPS (30).
    """

    def __init__(self) -> None:
        super().__init__(source_id="token_pole")
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
        # Build the token path in local natural-size coordinates (origin at
        # 0, 0). Mode selection is env-gated at construction; default is the
        # navel→cranium linear path per operator directive 2026-04-19.
        self._path_mode = _resolve_path_mode()
        if self._path_mode is PathMode.SPIRAL:
            cx = NATURAL_SIZE * SPIRAL_CENTER_X
            cy = NATURAL_SIZE * SPIRAL_CENTER_Y
            max_r = NATURAL_SIZE * SPIRAL_MAX_R
            self._path = _build_spiral(cx, cy, max_r, NUM_POINTS)
        else:
            self._path = _build_linear_path(NATURAL_SIZE, NUM_POINTS)
        # Backwards-compat alias so external code reading ``_spiral`` keeps
        # working while ``_path`` is the canonical name. New code should
        # reference ``_path`` directly.
        self._spiral = self._path
        # Task #146 chat-contribution cascade. Drives optional trigger()
        # calls from the wiring layer (scripts/chat-monitor.py) via a
        # setter method. Kept as an attribute so tests can poke state.
        self.emoji_spew = EmojiSpewEffect()

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Advance internal animation state then paint a full scene.

        Per-ward visibility + alpha modulation happens in the runner
        (``cairo_source.CairoSourceRunner._render_one_frame``) so this
        method draws unconditionally. The runner's
        :func:`ward_render_scope` wrap has already short-circuited the
        call when the ward is hidden.
        """
        self._tick_state()
        self._draw_scene(cr)

    def _tick_state(self) -> None:
        """Ledger I/O, position easing, pulse phase, particle physics."""
        now = time.monotonic()
        if now - self._last_read > 0.5:
            self._last_read = now
            self._read_ledger()
        diff = self._target_position - self._position
        self._position += diff * 0.06
        self._pulse += 0.1
        self._particles = [p for p in self._particles if p.tick()]
        # Task #146: advance chat-contribution emoji cascade (if armed).
        self.emoji_spew.tick(NATURAL_SIZE, NATURAL_SIZE)

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
                    # Task #146: if the ledger also carries a
                    # contribution_cascade payload, fire the emoji spew.
                    cascade = data.get("contribution_cascade")
                    if isinstance(cascade, dict):
                        self.emoji_spew.trigger(
                            explosion_number=int(cascade.get("explosion_number", new_explosions)),
                            contributor_count=int(cascade.get("contributor_count", 0)),
                        )
                self._last_explosion_count = new_explosions
                self._explosions = new_explosions
        except (json.JSONDecodeError, OSError):
            pass

    def _spawn_explosion(self) -> None:
        # Explode at the path's terminal anchor — cranium in linear mode,
        # spiral centre (navel) in legacy spiral mode. For the operator-
        # directed NAVEL_TO_CRANIUM path this fires at the head-crown
        # when the token reaches it; feels like completion rather than
        # a burst at the starting anchor.
        if self._path_mode is PathMode.NAVEL_TO_CRANIUM:
            cx = NATURAL_SIZE * CRANIUM_X
            cy = NATURAL_SIZE * CRANIUM_Y
        else:
            cx = NATURAL_SIZE * SPIRAL_CENTER_X
            cy = NATURAL_SIZE * SPIRAL_CENTER_Y
        for _ in range(60):
            self._particles.append(Particle(cx, cy))

    def _load_bg(self, cr: Any) -> None:
        """Load Vitruvian Man as cairo surface (once).

        Phase 3d: delegates to the shared ImageLoader, which handles
        both PNG (native cairo) and JPEG (PIL → premultiplied ARGB)
        decode paths in one place. Replaces the previous PNG-or-temp-
        file fallback that wrote a temporary PNG just to call
        ``create_from_png`` on it.
        """
        del cr  # unused; the loader doesn't need a draw context
        if self._bg_loaded:
            return
        self._bg_loaded = True
        if not VITRUVIAN_PATH.exists():
            return
        from .image_loader import get_image_loader

        self._bg_surface = get_image_loader().load(VITRUVIAN_PATH)
        if self._bg_surface is not None:
            log.info(
                "Vitruvian Man loaded (%dx%d)",
                self._bg_surface.get_width(),
                self._bg_surface.get_height(),
            )
        else:
            log.warning("Failed to load Vitruvian Man background")

    def _draw_scene(self, cr: Any) -> None:
        self._load_bg(cr)

        pkg = _resolve_package()
        palette = pkg.palette

        # Phase A4 (homage-completion-plan §2): the token-pole is now a
        # point-of-light emissive surface. Smiley face DELETED; token
        # glyph is centre dot + halo + outer bloom; spiral guide is 32
        # emissive points along the path; particles route through
        # ``paint_emissive_point``; status row + cascade marker render
        # through Pango Px437 via ``text_render``.
        from .homage.emissive_base import (
            paint_emissive_bg,
            paint_emissive_point,
            paint_emissive_stroke,
            stance_hz,
        )

        t_now = time.monotonic()
        stance = self._read_stance()
        pulse_hz = stance_hz(stance, fallback=1.0)

        # --- Gruvbox ground (emissive base) -------------------------------
        # Spec §5.5 refuses ``rounded-corners`` — flat background. Use the
        # package's ``background`` role so consent-safe variant collapses
        # to its muted flavour.
        bg_r, bg_g, bg_b, bg_a = palette.background
        paint_emissive_bg(cr, NATURAL_SIZE, NATURAL_SIZE, ground_rgba=(bg_r, bg_g, bg_b, bg_a))

        # --- Vitruvian engraving ------------------------------------------
        # Per success-def §1.2: paint the PNG at alpha=0.55 multiplied with
        # ``terminal_default × shimmer`` — reads as a grey engraving, not
        # sepia ink. The package-scoped tint ensures a palette swap carries
        # the figure.
        if self._bg_surface is not None:
            # 2026-04-23 operator "no flashing of any kind" — previously
            # ``shimmer = paint_breathing_alpha(t_now, hz=pulse_hz, phase=0.0)``
            # modulated the Vitruvian tint per frame. paint_breathing_alpha
            # itself now returns a static baseline, so the effect is
            # constant — but the expression ``0.55 * shimmer`` remained
            # as a lint target. Replaced with the static product
            # ``0.55 * 0.85 = 0.4675`` so the static-scan regression test
            # passes and the intent is explicit.
            _TINT_ALPHA = 0.4675  # 0.55 * paint_breathing_alpha baseline
            td_r, td_g, td_b, _ = palette.terminal_default
            cr.save()
            sw = self._bg_surface.get_width()
            sh = self._bg_surface.get_height()
            scale = NATURAL_SIZE / max(sw, sh) if max(sw, sh) > 0 else 1
            cr.scale(scale, scale)
            cr.set_source_surface(self._bg_surface, 0, 0)
            cr.paint_with_alpha(_TINT_ALPHA)
            cr.restore()
            # Tinting pass — multiply the figure with terminal_default so
            # the ink reads grey rather than raw.
            cr.save()
            cr.set_operator(__import__("cairo").OPERATOR_MULTIPLY)
            cr.set_source_rgba(td_r, td_g, td_b, _TINT_ALPHA)
            cr.rectangle(0, 0, NATURAL_SIZE, NATURAL_SIZE)
            cr.fill()
            cr.restore()

        # --- Z-layered golden spiral path with traveled/ahead distinction ---
        # Operator directive 2026-05-07: golden spiral with multiple z-layer
        # representation (like Sierpinski), path ahead vs path traveled
        # visually distinct (like map pathing progress).
        import cairo as _cairo

        idx = int(self._position * (NUM_POINTS - 1))
        muted_rgba = pkg.resolve_colour("muted")
        accent_cyan = pkg.resolve_colour("accent_cyan")
        accent_green = pkg.resolve_colour("accent_green")
        cx = NATURAL_SIZE * 0.5
        cy = NATURAL_SIZE * 0.5

        trail_rgba = tuple(pkg.resolve_colour(role) for role in _TRAIL_ROLES)
        num_c = len(trail_rgba)

        for z in range(_Z_LAYERS):
            scale_offset = 1.0 + z * _Z_SCALE_STEP
            alpha_mult = _Z_ALPHA_DECAY**z
            color_shift = z * _Z_COLOR_SHIFT

            cr.save()
            cr.translate(cx, cy)
            cr.scale(scale_offset, scale_offset)
            cr.translate(-cx, -cy)

            # PATH AHEAD (untraveled) — dashed, muted, with subtle hue cycling
            if idx < NUM_POINTS - 1:
                m_r, m_g, m_b, m_a = muted_rgba
                ac_r, ac_g, ac_b, ac_a = accent_cyan
                cr.save()
                dash_phase = (t_now * 12.0 + z * 8.0) % 20.0
                cr.set_dash([6.0, 4.0], dash_phase)
                cr.set_line_width(1.2 + z * 0.3)
                cr.set_line_cap(_cairo.LINE_CAP_ROUND)
                cr.set_line_join(_cairo.LINE_JOIN_ROUND)
                start = max(idx, 1)
                sx, sy = self._path[start]
                cr.move_to(sx, sy)
                for i in range(start + 1, NUM_POINTS):
                    px, py = self._path[i]
                    ahead_progress = (i - idx) / max(1, NUM_POINTS - idx)
                    fade = 0.25 + 0.15 * math.sin(ahead_progress * math.pi * 4 + t_now * 1.5 + z)
                    r = m_r + (ac_r - m_r) * (
                        color_shift + 0.1 * math.sin(ahead_progress * math.tau)
                    )
                    g = m_g + (ac_g - m_g) * (
                        color_shift + 0.1 * math.sin(ahead_progress * math.tau)
                    )
                    b = m_b + (ac_b - m_b) * (
                        color_shift + 0.1 * math.sin(ahead_progress * math.tau)
                    )
                    cr.set_source_rgba(r, g, b, fade * alpha_mult)
                    cr.line_to(px, py)
                cr.stroke()
                cr.restore()

            # PATH TRAVELED — solid, bright gradient, wider, with glow
            if idx > 1:
                for i in range(1, idx):
                    progress = i / idx
                    ci = progress * (num_c - 1)
                    c0 = trail_rgba[int(ci) % num_c]
                    c1 = trail_rgba[(int(ci) + 1) % num_c]
                    f = ci - int(ci)
                    r = c0[0] + (c1[0] - c0[0]) * f + color_shift * 0.3
                    g = c0[1] + (c1[1] - c0[1]) * f
                    b = c0[2] + (c1[2] - c0[2]) * f
                    a = c0[3] + (c1[3] - c0[3]) * f
                    baseline = (0.25 + 0.65 * (progress**1.3)) * alpha_mult
                    width = 2.4 + 1.2 * progress - z * 0.4
                    x0, y0 = self._path[i - 1]
                    x1, y1 = self._path[i]
                    paint_emissive_stroke(
                        cr,
                        x0,
                        y0,
                        x1,
                        y1,
                        (min(1.0, r), min(1.0, g), min(1.0, b), a),
                        t=t_now,
                        phase=i * 0.13 + z * 0.5,
                        baseline_alpha=baseline,
                        width_px=max(0.8, width),
                        shimmer_hz=pulse_hz,
                    )

                # Glow pass on the traveled path (z=0 only for perf)
                if z == 0 and idx > 10:
                    cr.save()
                    cr.set_line_width(6.0)
                    cr.set_line_cap(_cairo.LINE_CAP_ROUND)
                    cr.set_line_join(_cairo.LINE_JOIN_ROUND)
                    ag_r, ag_g, ag_b, _ = accent_green
                    glow_start = max(0, idx - 30)
                    sx, sy = self._path[glow_start]
                    cr.move_to(sx, sy)
                    for i in range(glow_start + 1, idx):
                        px, py = self._path[i]
                        cr.line_to(px, py)
                    cr.set_source_rgba(ag_r, ag_g, ag_b, 0.06)
                    cr.stroke()
                    cr.restore()

            cr.restore()

        # --- Token glyph with z-layer depth ---------------------------------
        if idx < len(self._path):
            gx, gy = self._path[idx]
        else:
            gx = NATURAL_SIZE * SPIRAL_CENTER_X
            gy = NATURAL_SIZE * SPIRAL_CENTER_Y

        pulse_r = math.sin(self._pulse) * 1.5
        bounce_y = math.sin(self._pulse * 1.7) * 1.0
        glyph_cx = gx
        glyph_cy = gy + bounce_y

        accent_yellow = pkg.resolve_colour("accent_yellow")
        accent_magenta = pkg.resolve_colour("accent_magenta")
        bright_rgba = pkg.resolve_colour("bright")
        ay_r, ay_g, ay_b, ay_a = accent_yellow
        am_r, am_g, am_b, am_a = accent_magenta

        for z in range(_Z_LAYERS):
            z_scale = 1.0 + z * _Z_SCALE_STEP
            z_alpha = _Z_ALPHA_DECAY**z
            z_offset = z * 1.5
            zcx = glyph_cx + z_offset
            zcy = glyph_cy - z_offset

            cr.save()
            cr.translate(cx, cy)
            cr.scale(z_scale, z_scale)
            cr.translate(-cx, -cy)

            paint_emissive_point(
                cr,
                zcx,
                zcy,
                (ay_r, ay_g, ay_b, ay_a * 0.12 * z_alpha),
                t=t_now,
                phase=z * 0.4,
                baseline_alpha=1.0,
                centre_radius_px=0.0,
                halo_radius_px=0.0,
                outer_glow_radius_px=22.0 + pulse_r,
                shimmer_hz=pulse_hz,
            )
            paint_emissive_point(
                cr,
                zcx,
                zcy,
                (am_r, am_g, am_b, am_a * 0.45 * z_alpha),
                t=t_now,
                phase=math.pi / 3.0 + z * 0.3,
                baseline_alpha=1.0,
                centre_radius_px=0.0,
                halo_radius_px=14.0 + pulse_r,
                outer_glow_radius_px=0.0,
                shimmer_hz=pulse_hz,
            )
            paint_emissive_point(
                cr,
                zcx,
                zcy,
                (ay_r, ay_g, ay_b, ay_a * z_alpha),
                t=t_now,
                phase=z * 0.2,
                baseline_alpha=1.0,
                centre_radius_px=4.0 + pulse_r * 0.5,
                halo_radius_px=8.0,
                outer_glow_radius_px=0.0,
                shimmer_hz=pulse_hz,
            )
            cr.restore()

        # Sparkle trail — bright, thinning, emissive.
        for i in range(1, 4):
            trail_idx = max(0, idx - i * 5)
            if trail_idx < len(self._path):
                tx, ty = self._path[trail_idx]
                br_r, br_g, br_b, br_a = bright_rgba
                paint_emissive_point(
                    cr,
                    tx,
                    ty,
                    (br_r, br_g, br_b, br_a * (0.60 - i * 0.15)),
                    t=t_now,
                    phase=i * 0.27,
                    baseline_alpha=1.0,
                    centre_radius_px=max(0.5, (4 - i) * 1.0),
                    halo_radius_px=max(1.0, (4 - i) * 2.0),
                    outer_glow_radius_px=0.0,
                    shimmer_hz=pulse_hz,
                )

        # --- Particles — emissive points, role-resolved colour -------------
        # Mid-flight package swap recolours particles already in flight.
        for p in self._particles:
            role = _EXPLOSION_ROLES[p.role_index]
            pr, pg, pb, pa = pkg.resolve_colour(role)  # type: ignore[arg-type]
            paint_emissive_point(
                cr,
                p.x,
                p.y,
                (pr, pg, pb, pa * p.alpha),
                t=t_now,
                phase=p.born % math.tau,
                baseline_alpha=1.0,
                centre_radius_px=max(0.5, p.size * 0.4),
                halo_radius_px=max(1.0, p.size * 0.9),
                outer_glow_radius_px=max(1.2, p.size * 1.4),
                shimmer_hz=pulse_hz,
            )

        # --- Status row (Px437) ------------------------------------------
        # Per success-def: ``>>> [TOKEN | <value>/<threshold>]`` rendered
        # through Pango via text_render so Px437 IBM VGA 8x16 resolves via
        # fontconfig rather than Cairo's toy fallback.
        self._draw_status_row(cr, pkg)

        # --- Task #146: chat-contribution emoji cascade ------------------
        self._draw_emoji_cascade(cr)
        self._draw_cascade_marker(cr, pkg)

    def _read_stance(self) -> str:
        """Read the current stimmung stance ("nominal" on any failure).

        Wrapped in a best-effort try so the render path never crashes
        over a missing /dev/shm file or an import-time dependency.
        """
        try:
            from shared.stimmung import read_stimmung  # type: ignore[import-not-found]

            raw = read_stimmung()
            if isinstance(raw, dict):
                return str(raw.get("overall_stance", "nominal"))
        except Exception:
            pass
        return "nominal"

    def _draw_status_row(self, cr: Any, pkg: Any) -> None:
        """Render the top-row ``>>> [TOKEN | <value>/<threshold>]`` strip.

        Uses the active package's line-start marker + Px437 typography
        via Pango; degrades gracefully to no-op when Pango is missing
        (CI-safe).
        """
        try:
            from .homage.rendering import select_bitchx_font_pango
            from .text_render import TextStyle, render_text
        except Exception:
            return
        try:
            marker = getattr(pkg.grammar, "line_start_marker", ">>>")
            value = max(0, int(self._total_tokens))
            threshold = max(1, int(self._threshold) if self._threshold else 1)
            muted = pkg.resolve_colour(pkg.grammar.punctuation_colour_role)
            bright = pkg.resolve_colour(pkg.grammar.identity_colour_role)
            # Render marker in muted, rest in bright — split for Pango so
            # the grammar survives the palette swap.
            font_desc = select_bitchx_font_pango(cr, 11, bold=True)
            marker_style = TextStyle(
                text=f"{marker} ",
                font_description=font_desc,
                color_rgba=muted,
            )
            render_text(cr, marker_style, x=6.0, y=2.0)
            # Approximate x-advance: Px437 is a fixed 8-wide cell; 4 glyphs.
            body_style = TextStyle(
                text=f"[TOKEN | {value}/{threshold}]",
                font_description=font_desc,
                color_rgba=bright,
            )
            render_text(cr, body_style, x=6.0 + 8.0 * (len(marker) + 1), y=2.0)
        except Exception:
            log.debug("token-pole status row render failed", exc_info=True)

    def _draw_emoji_cascade(self, cr: Any) -> None:
        """Draw active emoji-spew glyphs using Pango (Noto Color Emoji).

        Phase A4: no Cairo toy-text fallback — every text path goes
        through Pango. No-op when Pango is unavailable (CI).
        """
        if not self.emoji_spew.active or not self.emoji_spew.emoji:
            return
        try:
            from .text_render import _HAS_PANGO

            if not _HAS_PANGO:
                return
            import gi

            gi.require_version("Pango", "1.0")
            gi.require_version("PangoCairo", "1.0")
            from gi.repository import Pango, PangoCairo

            for e in self.emoji_spew.emoji:
                layout = PangoCairo.create_layout(cr)
                font = Pango.FontDescription.from_string(f"Noto Color Emoji {int(e.size)}")
                layout.set_font_description(font)
                layout.set_text(e.glyph, -1)
                cr.save()
                cr.move_to(e.x, e.y)
                # PangoCairo doesn't honour source-rgba alpha via
                # set_source_rgba alone; push a group for the alpha
                # multiply.
                cr.push_group()
                PangoCairo.show_layout(cr, layout)
                cr.pop_group_to_source()
                cr.paint_with_alpha(e.alpha)
                cr.restore()
        except Exception:
            log.debug("emoji cascade Pango path failed", exc_info=True)

    def _draw_cascade_marker(self, cr: Any, pkg: Any) -> None:
        """Draw ``#{n} FROM {count}`` banner at the top of the panel.

        Phase A4: renders through Pango Px437 via
        :func:`select_bitchx_font_pango`; drops the hardcoded
        ``JetBrains Mono Bold 12`` font that bypassed fontconfig.
        """
        marker = self.emoji_spew.marker_text()
        if marker is None:
            return
        try:
            from .homage.rendering import select_bitchx_font_pango
            from .text_render import TextStyle, render_text

            bright = pkg.resolve_colour(pkg.grammar.identity_colour_role)
            font_desc = select_bitchx_font_pango(cr, 12, bold=True)
            style = TextStyle(
                text=marker,
                font_description=font_desc,
                color_rgba=bright,
                outline_offsets=(),
            )
            render_text(cr, style, x=6.0, y=20.0)
        except Exception:
            log.debug("cascade marker Pango render failed", exc_info=True)


# The pre-Phase-9 ``TokenPole`` facade has been removed. Rendering now
# flows through ``TokenPoleCairoSource`` + the SourceRegistry + the
# layout walk in ``fx_chain.pip_draw_from_layout``.
