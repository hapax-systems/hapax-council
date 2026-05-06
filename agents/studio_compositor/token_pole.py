"""token_pole.py — Golden Ratio token tracker over Vitruvian Man.

Da Vinci's Vitruvian Man (1490, public domain) as background. The token
follows a golden ratio path — a Fibonacci spiral anchored to the figure's
anatomical φ-proportions: feet → knees → navel → chest → throat → cranium.
At the cranium, the token spawns an explosion of human-representative
Unicode glyphs (faces, hands, runners, hearts, brains) covering 2/3 of
the livestream frame. During the explosion, the token resets to the feet
and begins climbing again.

Path ahead (token → cranium) renders as dim muted stroke with φ-landmark
dots. Path behind (feet → token) renders as bright emissive gradient
trail. All rendering is pre-fx so the GL shader chain (chromatic
aberration, bloom, tunnel, etc.) applies to every element.

Canvas is 1080×1080 transparent overlay — the Vitruvian figure occupies
the upper-left quadrant (~300×300 region) while the explosion radiates
across the full surface.
"""

from __future__ import annotations

import json
import logging
import math
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

# Natural size of the token-pole source — 300×300 as original. The
# Vitruvian figure fills this canvas. Explosion particles are rendered
# by a separate full-frame overlay (token_explosion_overlay.py) that
# reads from the module-level _SHARED_PARTICLES list.
NATURAL_SIZE = 300

# The Vitruvian figure fills the full 300×300 canvas.
_VIT_SIZE = 300
_VIT_OFFSET_X = 0
_VIT_OFFSET_Y = 0

PHI = (1 + math.sqrt(5)) / 2
NUM_POINTS = 300


# ── Golden ratio anatomical landmarks (normalised to 500×500 PNG) ─────────
# These are the φ-proportional points on the Vitruvian Man figure.
# Da Vinci's drawing encodes φ: navel divides total height at 1/φ from
# the ground. We trace through nested golden rectangles anchored to these.
#
# Coordinates are normalised [0, 1] relative to the 500×500 PNG, then
# scaled to _VIT_SIZE at path build time.
_LANDMARKS: list[tuple[float, float, str]] = [
    (0.540, 0.880, "right_foot"),  # start: right foot, lower body
    (0.580, 0.780, "right_shin"),  # ascending shin
    (0.560, 0.680, "right_knee"),  # knee bend — φ from ground to navel
    (0.540, 0.600, "right_thigh"),  # inner thigh
    (0.500, 0.520, "navel"),  # the great φ-division
    (0.460, 0.460, "lower_abdomen"),  # ascending torso
    (0.440, 0.400, "chest_base"),  # ribcage
    (0.480, 0.340, "sternum"),  # sternum / chest center
    (0.500, 0.280, "throat"),  # throat — φ from navel to crown
    (0.498, 0.220, "chin"),  # jawline
    (0.498, 0.160, "forehead"),  # forehead
    (0.498, 0.072, "cranium"),  # crown — terminal
]


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


def _build_golden_ratio_path(n: int) -> list[tuple[float, float]]:
    """Build a golden ratio spiral path through the Vitruvian Man's anatomy.

    Uses cubic Bézier interpolation through the anatomical φ-landmarks
    to produce a smooth ascending curve. The path starts at the right
    foot and spirals upward through knees, navel, chest, throat to the
    cranium crown. Quarter-arc curvature between landmarks gives the
    path a natural golden-spiral feel.

    Returns ``n`` evenly-spaced (by arc length) pixel coordinates in
    the _VIT_SIZE coordinate space, offset by (_VIT_OFFSET_X, _VIT_OFFSET_Y).
    """
    # Convert normalised landmarks to pixel coords in the Vitruvian region.
    anchors: list[tuple[float, float]] = []
    for nx, ny, _name in _LANDMARKS:
        px = _VIT_OFFSET_X + nx * _VIT_SIZE
        py = _VIT_OFFSET_Y + ny * _VIT_SIZE
        anchors.append((px, py))

    if len(anchors) < 2:
        return [(anchors[0][0], anchors[0][1])] * n if anchors else [(0, 0)] * n

    # Build a smooth curve through the anchors using Catmull-Rom → Bézier.
    # First, densely sample between each pair of anchors with cubic interp.
    dense: list[tuple[float, float]] = []
    steps_per_seg = 40
    for seg in range(len(anchors) - 1):
        p0 = anchors[max(0, seg - 1)]
        p1 = anchors[seg]
        p2 = anchors[min(len(anchors) - 1, seg + 1)]
        p3 = anchors[min(len(anchors) - 1, seg + 2)]
        for step in range(steps_per_seg):
            t = step / steps_per_seg
            t2 = t * t
            t3 = t2 * t
            # Catmull-Rom coefficients (tension=0.5)
            x = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            dense.append((x, y))
    # Add the terminal anchor.
    dense.append(anchors[-1])

    # Re-parameterise by arc length to get evenly-spaced output points.
    # Compute cumulative arc length.
    arc_lengths = [0.0]
    for i in range(1, len(dense)):
        dx = dense[i][0] - dense[i - 1][0]
        dy = dense[i][1] - dense[i - 1][1]
        arc_lengths.append(arc_lengths[-1] + math.hypot(dx, dy))

    total_length = arc_lengths[-1]
    if total_length < 1e-6:
        return [dense[0]] * n

    result: list[tuple[float, float]] = []
    for i in range(n):
        target = (i / (n - 1)) * total_length
        # Binary search for the segment containing this arc length.
        lo, hi = 0, len(arc_lengths) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if arc_lengths[mid] <= target:
                lo = mid
            else:
                hi = mid
        seg_len = arc_lengths[hi] - arc_lengths[lo]
        if seg_len > 1e-6:
            frac = (target - arc_lengths[lo]) / seg_len
        else:
            frac = 0.0
        x = dense[lo][0] + (dense[hi][0] - dense[lo][0]) * frac
        y = dense[lo][1] + (dense[hi][1] - dense[lo][1]) * frac
        result.append((x, y))

    return result


def _resolve_package() -> HomagePackage:
    """Return the active HomagePackage, or the BitchX fallback."""
    pkg = get_active_package()
    if pkg is not None:
        return pkg
    from .homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


# ── Human glyph palette for the cranium explosion ────────────────────────
# Curated Unicode glyphs representing diverse aspects of humanity.
# Rendered via Pango so emoji / symbol fonts resolve through fontconfig.
_HUMAN_GLYPHS: tuple[str, ...] = (
    # Faces — diverse representation
    "🧑",
    "👶",
    "🧒",
    "👦",
    "👧",
    "🧔",
    "👩",
    "👨",
    "🧑\u200d🦱",
    "🧑\u200d🦰",
    "🧑\u200d🦳",
    # Body parts — the Vitruvian anatomy
    "🤲",
    "🙌",
    "👐",
    "💪",
    "🦶",
    "🦵",
    "👁️",
    "🧠",
    "❤️",
    "🫀",
    # Movement — the human in motion
    "🏃",
    "🧘",
    "🤸",
    "💃",
    "🕺",
    "🧗",
    "🏊",
    "🚶",
    # Hands — Da Vinci's studies
    "✋",
    "🤚",
    "👋",
    "🖐️",
    "✌️",
    "🤞",
    "👆",
    "👇",
    "👈",
    "👉",
    # Connection
    "🤝",
    "🫂",
    # Abstract human
    "⭐",
    "✨",
    "💫",
    "🌟",
)

# Blast radius in pixels: 2/3 of the 1080 canvas = 720px.
_BLAST_RADIUS_PX: float = 720.0

# Number of glyphs spawned per explosion.
_GLYPH_COUNT: int = 120

# Glyph lifetime in seconds.
_GLYPH_LIFETIME_S: float = 2.8


class HumanGlyphParticle:
    """A single human glyph in the cranium explosion."""

    __slots__ = (
        "glyph",
        "x",
        "y",
        "vx",
        "vy",
        "role_index",
        "alpha",
        "size",
        "rotation",
        "rot_speed",
        "born",
    )

    def __init__(self, cx: float, cy: float) -> None:
        self.glyph = random.choice(_HUMAN_GLYPHS)
        angle = random.uniform(0, 2 * math.pi)
        # Speed scaled so particles reach 2/3 frame in ~1.5s.
        speed = random.uniform(8, 38)
        self.x = cx
        self.y = cy
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - random.uniform(2, 8)
        self.role_index = random.randrange(len(_EXPLOSION_ROLES))
        self.alpha = 1.0
        self.size = random.uniform(14, 36)
        self.rotation = random.uniform(0, 2 * math.pi)
        self.rot_speed = random.uniform(-2.0, 2.0)
        self.born = time.monotonic()

    def tick(self) -> bool:
        """Advance physics. Returns False when the particle should be culled."""
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.12  # gentle gravity
        self.vx *= 0.985  # air drag
        self.vy *= 0.985
        self.rotation += self.rot_speed * 0.033  # ~30fps
        age = time.monotonic() - self.born
        # Smooth ease-out fade.
        t = min(1.0, age / _GLYPH_LIFETIME_S)
        self.alpha = max(0.0, 1.0 - t * t)
        return self.alpha > 0.02


# ── Shared explosion state ────────────────────────────────────────────────
# Module-level list shared between TokenPoleCairoSource (spawns particles)
# and TokenExplosionOverlayCairoSource (renders them at full-frame).
# Both sources run in the same process on background threads; the list
# is append/filter only, so races produce at most a skipped frame.
_SHARED_PARTICLES: list[HumanGlyphParticle] = []


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


class TokenPoleCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource implementation for the token-pole overlay.

    Golden ratio path from feet→cranium over the Vitruvian Man. At cranium
    arrival, spawns ~120 human-representative Unicode glyphs covering 2/3
    of the frame. Token resets and cycles. Path ahead is dim muted; path
    behind is bright gradient. All elements rendered pre-fx so the GL
    shader chain (bloom, chromatic aberration, tunnel) processes them.
    """

    def __init__(self) -> None:
        super().__init__(source_id="token_pole")
        self._position: float = 0.0
        self._target_position: float = 0.0
        self._explosions: int = 0
        self._total_tokens: int = 0
        self._threshold: int = 0
        self._particles: list[HumanGlyphParticle] = []
        self._last_read: float = 0
        self._last_explosion_count: int = 0
        self._pulse: float = 0.0
        self._bg_surface: Any = None
        self._bg_loaded = False
        # Golden ratio path through anatomical landmarks.
        self._path = _build_golden_ratio_path(NUM_POINTS)
        self._spiral = self._path  # backwards-compat alias
        # Pre-compute landmark indices for φ-marker rendering.
        self._landmark_indices: list[int] = []
        for _i, (nx, ny, _name) in enumerate(_LANDMARKS):
            px = _VIT_OFFSET_X + nx * _VIT_SIZE
            py = _VIT_OFFSET_Y + ny * _VIT_SIZE
            best_idx = 0
            best_dist = float("inf")
            for j, (ppx, ppy) in enumerate(self._path):
                d = (ppx - px) ** 2 + (ppy - py) ** 2
                if d < best_dist:
                    best_dist = d
                    best_idx = j
            self._landmark_indices.append(best_idx)
        # Task #146 chat-contribution cascade.
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
        # Tick shared explosion particles (culled by the overlay source).
        _SHARED_PARTICLES[:] = [p for p in _SHARED_PARTICLES if p.tick()]
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
        """Spawn human glyph explosion at the cranium and reset token to feet.

        Particles are spawned in frame-space coordinates (1920×1080) so
        the separate full-frame overlay can render them. The cranium
        position is converted from the 300px canvas → 240px pip-ul →
        frame position.
        """
        # Cranium point in canvas coords → frame coords.
        # pip-ul: x=16, y=12, 240×240 surface, source=300×300.
        canvas_cx = _VIT_OFFSET_X + _LANDMARKS[-1][0] * _VIT_SIZE
        canvas_cy = _VIT_OFFSET_Y + _LANDMARKS[-1][1] * _VIT_SIZE
        scale = 240.0 / NATURAL_SIZE  # 0.8
        frame_cx = 16 + canvas_cx * scale
        frame_cy = 12 + canvas_cy * scale
        for _ in range(_GLYPH_COUNT):
            _SHARED_PARTICLES.append(HumanGlyphParticle(frame_cx, frame_cy))
        # Reset token to start of path (feet) for cycling.
        self._position = 0.0
        self._target_position = 0.0

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

        from .homage.emissive_base import (
            paint_emissive_bg,
            paint_emissive_point,
            paint_emissive_stroke,
            stance_hz,
        )

        t_now = time.monotonic()
        stance = self._read_stance()
        pulse_hz = stance_hz(stance, fallback=1.0)

        # --- Transparent ground (no container bg) -------------------------
        bg_r, bg_g, bg_b, bg_a = palette.background
        paint_emissive_bg(cr, NATURAL_SIZE, NATURAL_SIZE, ground_rgba=(bg_r, bg_g, bg_b, bg_a))

        # --- Vitruvian engraving in the _VIT_SIZE region ------------------
        if self._bg_surface is not None:
            _TINT_ALPHA = 0.4675
            td_r, td_g, td_b, _ = palette.terminal_default
            cr.save()
            sw = self._bg_surface.get_width()
            sh = self._bg_surface.get_height()
            scale = _VIT_SIZE / max(sw, sh) if max(sw, sh) > 0 else 1
            cr.translate(_VIT_OFFSET_X, _VIT_OFFSET_Y)
            cr.scale(scale, scale)
            cr.set_source_surface(self._bg_surface, 0, 0)
            cr.paint_with_alpha(_TINT_ALPHA)
            cr.restore()
            # Tinting pass.
            cr.save()
            cr.set_operator(__import__("cairo").OPERATOR_MULTIPLY)
            cr.set_source_rgba(td_r, td_g, td_b, _TINT_ALPHA)
            cr.rectangle(_VIT_OFFSET_X, _VIT_OFFSET_Y, _VIT_SIZE, _VIT_SIZE)
            cr.fill()
            cr.restore()

        muted_rgba = pkg.resolve_colour("muted")
        accent_yellow = pkg.resolve_colour("accent_yellow")
        accent_magenta = pkg.resolve_colour("accent_magenta")
        accent_cyan = pkg.resolve_colour("accent_cyan")
        bright_rgba = pkg.resolve_colour("bright")

        idx = int(self._position * (NUM_POINTS - 1))
        idx = min(idx, NUM_POINTS - 1)

        # --- Path ahead (token → cranium): dim muted stroke ---------------
        m_r, m_g, m_b, m_a = muted_rgba
        if idx < NUM_POINTS - 1:
            cr.save()
            cr.set_source_rgba(m_r, m_g, m_b, m_a * 0.35)
            cr.set_line_width(1.2)
            cr.set_line_cap(__import__("cairo").LINE_CAP_ROUND)
            cr.set_line_join(__import__("cairo").LINE_JOIN_ROUND)
            ax, ay = self._path[idx]
            cr.move_to(ax, ay)
            for px, py in self._path[idx + 1 :]:
                cr.line_to(px, py)
            cr.stroke()
            cr.restore()
            # Dim landmark dots ahead of token.
            for li in self._landmark_indices:
                if li > idx:
                    lx, ly = self._path[li]
                    paint_emissive_point(
                        cr,
                        lx,
                        ly,
                        muted_rgba,
                        t=t_now,
                        phase=li * 0.17,
                        baseline_alpha=0.4,
                        centre_radius_px=2.0,
                        halo_radius_px=5.0,
                        outer_glow_radius_px=8.0,
                        shimmer_hz=pulse_hz,
                    )

        # --- Path behind (start → token): bright gradient trail -----------
        if idx > 1:
            trail_rgba = tuple(pkg.resolve_colour(role) for role in _TRAIL_ROLES)
            num_c = len(trail_rgba)
            # Draw every 2nd segment for performance on the 300-point path.
            for i in range(1, idx, 2):
                progress = i / idx
                ci = progress * (num_c - 1)
                c0 = trail_rgba[int(ci) % num_c]
                c1 = trail_rgba[(int(ci) + 1) % num_c]
                f = ci - int(ci)
                r = c0[0] + (c1[0] - c0[0]) * f
                g = c0[1] + (c1[1] - c0[1]) * f
                b = c0[2] + (c1[2] - c0[2]) * f
                a = c0[3] + (c1[3] - c0[3]) * f
                baseline = 0.20 + 0.60 * (progress**1.3)
                x0, y0 = self._path[i - 1]
                x1, y1 = self._path[i]
                paint_emissive_stroke(
                    cr,
                    x0,
                    y0,
                    x1,
                    y1,
                    (r, g, b, a),
                    t=t_now,
                    phase=i * 0.13,
                    baseline_alpha=baseline,
                    width_px=2.2,
                    shimmer_hz=pulse_hz,
                )
            # Bright landmark dots behind token.
            for li in self._landmark_indices:
                if li <= idx:
                    lx, ly = self._path[li]
                    paint_emissive_point(
                        cr,
                        lx,
                        ly,
                        accent_cyan,
                        t=t_now,
                        phase=li * 0.17,
                        baseline_alpha=0.9,
                        centre_radius_px=3.0,
                        halo_radius_px=7.0,
                        outer_glow_radius_px=11.0,
                        shimmer_hz=pulse_hz,
                    )

        # --- Token glyph — centre dot + halo + outer bloom ----------------
        if idx < len(self._path):
            gx, gy = self._path[idx]
        else:
            gx, gy = self._path[-1]

        pulse_r = math.sin(self._pulse) * 1.5
        bounce_y = math.sin(self._pulse * 1.7) * 1.0
        glyph_cx = gx
        glyph_cy = gy + bounce_y

        ay_r, ay_g, ay_b, ay_a = accent_yellow
        # Outer bloom.
        paint_emissive_point(
            cr,
            glyph_cx,
            glyph_cy,
            (ay_r, ay_g, ay_b, ay_a * 0.12),
            t=t_now,
            phase=0.0,
            baseline_alpha=1.0,
            centre_radius_px=0.0,
            halo_radius_px=0.0,
            outer_glow_radius_px=22.0 + pulse_r,
            shimmer_hz=pulse_hz,
        )
        # Halo.
        am_r, am_g, am_b, am_a = accent_magenta
        paint_emissive_point(
            cr,
            glyph_cx,
            glyph_cy,
            (am_r, am_g, am_b, am_a * 0.45),
            t=t_now,
            phase=math.pi / 3.0,
            baseline_alpha=1.0,
            centre_radius_px=0.0,
            halo_radius_px=14.0 + pulse_r,
            outer_glow_radius_px=0.0,
            shimmer_hz=pulse_hz,
        )
        # Centre dot.
        paint_emissive_point(
            cr,
            glyph_cx,
            glyph_cy,
            accent_yellow,
            t=t_now,
            phase=0.0,
            baseline_alpha=1.0,
            centre_radius_px=4.0 + pulse_r * 0.5,
            halo_radius_px=8.0,
            outer_glow_radius_px=0.0,
            shimmer_hz=pulse_hz,
        )

        # Sparkle trail — bright, thinning.
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

        # --- Status row (Px437) -------------------------------------------
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

    def _draw_glyph_particles(self, cr: Any, pkg: Any, t_now: float, pulse_hz: float) -> None:
        """Render human glyph explosion particles via Pango.

        Each glyph gets an emissive halo underneath (via paint_emissive_point)
        and a rotated Pango-rendered Unicode glyph on top. The rotation and
        alpha are per-particle. No-op when no particles are active or Pango
        is unavailable.
        """
        if not self._particles:
            return
        try:
            import gi

            gi.require_version("Pango", "1.0")
            gi.require_version("PangoCairo", "1.0")
            from gi.repository import Pango, PangoCairo
        except Exception:
            # Fallback: render as emissive dots only (no glyph text).
            from .homage.emissive_base import paint_emissive_point

            for p in self._particles:
                role = _EXPLOSION_ROLES[p.role_index]
                pr, pg, pb, pa = pkg.resolve_colour(role)
                paint_emissive_point(
                    cr,
                    p.x,
                    p.y,
                    (pr, pg, pb, pa * p.alpha),
                    t=t_now,
                    phase=p.born % math.tau,
                    baseline_alpha=1.0,
                    centre_radius_px=max(1.0, p.size * 0.3),
                    halo_radius_px=max(2.0, p.size * 0.6),
                    outer_glow_radius_px=max(3.0, p.size * 0.9),
                    shimmer_hz=pulse_hz,
                )
            return

        from .homage.emissive_base import paint_emissive_point

        for p in self._particles:
            role = _EXPLOSION_ROLES[p.role_index]
            pr, pg, pb, pa = pkg.resolve_colour(role)
            glyph_alpha = p.alpha

            # Emissive halo under the glyph.
            paint_emissive_point(
                cr,
                p.x,
                p.y,
                (pr, pg, pb, pa * glyph_alpha * 0.5),
                t=t_now,
                phase=p.born % math.tau,
                baseline_alpha=1.0,
                centre_radius_px=0.0,
                halo_radius_px=max(2.0, p.size * 0.4),
                outer_glow_radius_px=max(4.0, p.size * 0.8),
                shimmer_hz=pulse_hz,
            )

            # Pango glyph with rotation.
            cr.save()
            cr.translate(p.x, p.y)
            cr.rotate(p.rotation)
            layout = PangoCairo.create_layout(cr)
            font = Pango.FontDescription.from_string(f"Noto Color Emoji {int(p.size)}")
            layout.set_font_description(font)
            layout.set_text(p.glyph, -1)
            _w, _h = layout.get_pixel_size()
            cr.move_to(-_w / 2.0, -_h / 2.0)
            cr.push_group()
            PangoCairo.show_layout(cr, layout)
            cr.pop_group_to_source()
            cr.paint_with_alpha(glyph_alpha)
            cr.restore()

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
