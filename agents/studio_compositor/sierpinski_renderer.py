"""Sierpinski triangle Cairo renderer for the GStreamer pre-FX cairooverlay.

Draws a 2-level Sierpinski triangle with local visual-pool frames masked into the 3
corner regions and a waveform in the center void. Renders BEFORE the GL
shader chain so glfeedback effects apply to the triangle.

Phase 3b: the rendering logic lives in :class:`SierpinskiCairoSource`,
which conforms to the :class:`CairoSource` protocol. The thread loop and
output-surface caching are owned by :class:`CairoSourceRunner`. The
:class:`SierpinskiRenderer` facade preserves the original public API
(``start``/``stop``/``draw``/``set_active_slot``/``set_audio_energy``)
so existing call sites in ``fx_chain.py`` and ``overlay.py`` keep working.
"""

from __future__ import annotations

import logging
import math
import os
import struct
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.visual_pool.repository import LocalVisualPoolSelector

from .cairo_source import CairoSourceRunner
from .homage.transitional_source import HomageTransitionalSource
from .image_loader import get_image_loader

if TYPE_CHECKING:
    import cairo

    from agents.studio_compositor.budget import BudgetTracker

log = logging.getLogger(__name__)

RENDER_FPS = 10
# Per operator directive 2026-05-06
# (`feedback_audio_reactivity_must_be_tight_speech_representation`):
# audio reactivity must be TIGHT. The Sierpinski center waveform is
# Hapax's speech representation and MUST stay raw (it does — see
# `_draw_waveform` call which uses `self._audio_energy`). The
# line-width / alpha MODULATIONS previously used asymmetric IIR
# (attack=0.45, release=0.22) for transient-whip prevention. Replaced
# with instant-response bounded amplitude — peaks above the burst
# clamp don't whip the line into pathological territory, but response
# to audio is single-frame tight. Default alphas now 1.0 (no
# smoothing); attack/release knobs retained for backward-compat with
# any instance that requests explicit smoothing.
SIERPINSKI_AUDIO_ATTACK_ALPHA = 1.0
SIERPINSKI_AUDIO_RELEASE_ALPHA = 1.0
SIERPINSKI_AUDIO_BURST_CLAMP = 0.85

# Phase 2 of yt-content-reverie-sierpinski-separation (2026-04-21).
# The reverie mixer's affordance pipeline writes this state file when
# ``content.yt.feature`` recruits at a director scene cut-point. The
# Sierpinski renderer reads it each tick and elevates the named slot's
# opacity for FEATURED_TTL_S seconds before reverting to the
# active-slot-only highlight (``set_active_slot``). Stays in
# ``hapax-compositor`` SHM because Sierpinski is part of the studio
# compositor process; reverie writes from a sister process.
FEATURED_YT_SLOT_FILE = Path("/dev/shm/hapax-compositor/featured-yt-slot")
FEATURED_TTL_S = 6.0

# GEAL spec §5.1 — ``video_attention`` scalar. Sierpinski writes a single
# little-endian f32 here each tick; GEAL reads it to scale its activation
# budget so an active video rect pulls GEAL back to ~30 % and GEAL never
# fills an empty rect.
VIDEO_ATTENTION_PATH = Path("/dev/shm/hapax-compositor/video-attention.f32")
VIDEO_ATTENTION_FRESH_S = 2.0  # freshness plateau
VIDEO_ATTENTION_DECAY_TAU_S = 2.0  # exponential decay time constant beyond plateau
FEATURED_OPACITY_BOOST = 1.0  # max opacity when featured (vs 0.9 active, 0.4 idle)
FEATURED_FALLBACK_OPACITY = 0.9  # active-slot opacity (legacy default)
FEATURED_IDLE_OPACITY = 0.4  # non-active opacity (legacy default)

# Synthwave palette (neon pink, cyan, purple)
COLORS = [
    (1.0, 0.2, 0.6),  # neon pink
    (0.0, 0.9, 1.0),  # cyan
    (0.7, 0.3, 1.0),  # purple
    (1.0, 0.4, 0.8),  # hot pink
]

AUDIO_LINE_WIDTH_BASE_PX = 1.5
AUDIO_LINE_WIDTH_SCALE_PX = 2.0
AUDIO_LINE_WIDTH_ATTACK_LIFT = 0.35
AUDIO_LINE_WIDTH_MAX_PX = AUDIO_LINE_WIDTH_BASE_PX + AUDIO_LINE_WIDTH_SCALE_PX

# GEAL spec §4.2 — per-level stroke width + alpha table for the extended
# geometry cache. Indexed by depth. Tuple is
# ``(core_stroke_px, glow_stroke_px, core_alpha, glow_alpha)``. L4 has no
# glow stroke (encoded as 0.0 / 0.0); audio-reactive stroke bumps apply to
# L0–L2 only (L3/L4 stay structural).
LEVEL_STROKE_ALPHA: dict[int, tuple[float, float, float, float]] = {
    0: (2.0, 6.0, 0.80, 0.15),
    1: (1.5, 4.5, 0.80, 0.15),
    2: (1.25, 3.0, 0.70, 0.10),
    3: (1.0, 1.8, 0.55, 0.06),
    4: (0.75, 0.0, 0.35, 0.0),
}


# --- Extended geometry cache (GEAL Phase 0 Task 0.2) ---

Point = tuple[float, float]
Polygon = list[Point]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class GeometryCache:
    """Sierpinski geometry computed up to ``target_depth``.

    Produced by :meth:`SierpinskiCairoSource.geometry_cache`. Used by GEAL
    to render the 8-layer expressive stack (§5 of the spec). Kept
    side-by-side with the legacy ``_cached_*`` fields on the source —
    GEAL is a parallel reader, not a rewrite of the existing render path.

    Fields
    ------
    all_triangles
        Every solid (non-void) sub-triangle from L0 through ``target_depth``.
        Count matches ``sum(3**i for i in range(target_depth+1))``.
    corner_slivers
        Per-corner list of 3 polygons: the L1 corner triangle minus its
        inscribed 16:9 rect, split into (apex, left, right) slivers. This
        is where GEAL renders the three grounding extrusions without
        occluding the YT video rects.
    center_void
        The L1 centre triangle (hosts the centre-void field in GEAL §5
        layer 4).
    vertex_halo_centers
        The 3 primary L0 apices. Canonical anchors for V2 voice halos
        and G6 gaze-hop markers.
    edge_polylines
        Mapping from path tag (e.g. ``"L0.top"``, ``"L1.0.left"``) to
        the 2-point polyline describing that edge. Populated for every
        level so G1 wavefronts can propagate along recursion-tree edges.
    inscribed_rects
        Axis-aligned 16:9 rects inscribed in each of the 3 L1 corners.
    target_depth
        The depth this cache was built for. L0 = root, L4 = max.
    """

    all_triangles: list[Polygon] = field(default_factory=list)
    corner_slivers: list[list[Polygon]] = field(default_factory=list)
    center_void: Polygon = field(default_factory=list)
    vertex_halo_centers: list[Point] = field(default_factory=list)
    edge_polylines: dict[str, list[Point]] = field(default_factory=dict)
    inscribed_rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    target_depth: int = 2


class SierpinskiCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource implementation for the Sierpinski overlay.

    Owns the YouTube frame cache, active-slot state, and audio energy
    snapshot. The runner calls ``render_content()`` once per tick on a
    background thread.
    """

    def __init__(self) -> None:
        super().__init__(source_id="sierpinski")
        self._frame_surfaces: dict[int, cairo.ImageSurface | None] = {}
        self._frame_mtimes: dict[int, float] = {}
        self._active_slot = 0
        self._audio_energy = 0.0
        self._audio_energy_smoothed = 0.0
        # Phase 2 yt-feature state — most-recent featured-yt-slot read.
        # Refreshed each tick from FEATURED_YT_SLOT_FILE; the value here
        # decays to "no feature" once its `ts` is older than
        # FEATURED_TTL_S so a stale write doesn't pin a slot forever.
        self._featured_slot_id: int | None = None
        self._featured_ts: float = 0.0
        self._featured_level: float = 0.0
        self._featured_file_mtime: float = 0.0
        # Drop #42 SIERP-1: cache triangle geometry + inscribed rects
        # keyed on canvas size. Triangle vertices and the 4 inscribed
        # rects (3 corners + 1 center void) are deterministic in
        # canvas_w/canvas_h, so we can compute them once per resize
        # and reuse across ticks. Saves ~0.2 ms/tick.
        self._geom_cache_size: tuple[int, int] | None = None
        self._cached_all_triangles: list[list[tuple[float, float]]] | None = None
        self._cached_corner_rects: list[tuple[float, float, float, float]] | None = None
        self._cached_center_rect: tuple[float, float, float, float] | None = None
        self._visual_pool_selector = LocalVisualPoolSelector()

    def set_active_slot(self, slot_id: int) -> None:
        self._active_slot = slot_id

    def set_audio_energy(self, energy: float) -> None:
        self._audio_energy = energy
        # Bounded-amplitude clamp on the line-width-modulating energy.
        # Per operator directive 2026-05-06 (audio reactivity MUST be
        # TIGHT), the prior asymmetric IIR was replaced with instant-
        # response amplitude clamped at SIERPINSKI_AUDIO_BURST_CLAMP so
        # the line doesn't whip on percussive ±1.0 transients but the
        # visual response to audio is single-frame tight. The waveform
        # draw still uses raw self._audio_energy — that surface IS the
        # audio. With both attack/release alphas defaulted to 1.0 the
        # smoother is effectively a per-frame bounded passthrough; the
        # alpha knobs stay in the API for any instance that wants
        # explicit smoothing.
        clamped = min(energy, SIERPINSKI_AUDIO_BURST_CLAMP)
        alpha = (
            SIERPINSKI_AUDIO_ATTACK_ALPHA
            if clamped > self._audio_energy_smoothed
            else SIERPINSKI_AUDIO_RELEASE_ALPHA
        )
        self._audio_energy_smoothed = self._audio_energy_smoothed * (1.0 - alpha) + clamped * alpha

    def _refresh_featured_yt_slot(self) -> None:
        """Phase 2 yt-feature: read FEATURED_YT_SLOT_FILE if it changed.

        mtime-gated so we re-parse JSON only when the file actually
        rolled over. Tolerates absent / malformed file (the feature
        flag stays cleared, slots fall back to the legacy
        active-slot-only highlight).
        """
        try:
            mtime = FEATURED_YT_SLOT_FILE.stat().st_mtime
        except (OSError, FileNotFoundError):
            return
        if mtime <= self._featured_file_mtime:
            return
        self._featured_file_mtime = mtime
        try:
            import json as _json

            data = _json.loads(FEATURED_YT_SLOT_FILE.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            self._featured_slot_id = None
            return
        try:
            self._featured_slot_id = int(data.get("slot_id"))
            self._featured_ts = float(data.get("ts", 0.0))
            self._featured_level = float(data.get("level", 1.0))
        except (TypeError, ValueError):
            self._featured_slot_id = None
            return

    def _slot_opacity(self, slot_id: int, *, now: float | None = None) -> float:
        """Resolve the per-slot opacity given current featured + active state.

        Precedence (highest first):
          1. **Featured + within TTL** — slot is the recently-featured one
             and the write is < FEATURED_TTL_S old. Returns
             FEATURED_OPACITY_BOOST scaled by the recruited level.
          2. **Active slot** — director's per-tick highlight (legacy
             behaviour, unchanged).
          3. **Idle** — non-active slot (legacy 0.4).

        The featured + active layers compose: featuring elevates ABOVE
        the active highlight; declining featured falls back to active or
        idle as appropriate.
        """
        if self._featured_slot_id is not None and slot_id == self._featured_slot_id:
            now = time.time() if now is None else now
            age = now - self._featured_ts
            if 0.0 <= age <= FEATURED_TTL_S:
                # Lerp inside the boost band: at level=1.0 -> full boost,
                # at level=0.0 -> active opacity (still visible).
                return FEATURED_FALLBACK_OPACITY + (
                    FEATURED_OPACITY_BOOST - FEATURED_FALLBACK_OPACITY
                ) * max(0.0, min(1.0, self._featured_level))
        if slot_id == self._active_slot:
            return FEATURED_FALLBACK_OPACITY
        return FEATURED_IDLE_OPACITY

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        # Drop #42 SIERP-1: recompute geometry only on canvas resize.
        if self._geom_cache_size != (canvas_w, canvas_h):
            self._rebuild_geometry_cache(canvas_w, canvas_h)

        assert self._cached_all_triangles is not None
        assert self._cached_corner_rects is not None
        assert self._cached_center_rect is not None

        # Phase 2 yt-feature: refresh featured-slot state once per tick
        # from the SHM file the reverie mixer writes when
        # content.yt.feature is recruited. The TTL guard inside makes a
        # stale write decay rather than pin the boost indefinitely.
        self._refresh_featured_yt_slot()

        # Load and draw video frames in corner triangles. Rects are
        # from the geometry cache; triangles are only needed for the
        # line work below, which reads them directly from
        # self._cached_all_triangles.
        for slot_id in range(3):
            frame_surface = self._load_frame(slot_id)
            opacity = self._slot_opacity(slot_id)
            rect = self._cached_corner_rects[slot_id]
            self._draw_video_in_triangle(cr, frame_surface, rect, opacity)

        # Waveform in center
        self._draw_waveform(cr, self._cached_center_rect, self._audio_energy, t)

        # Draw line work with audio-reactive width — smoothed so per-frame
        # transients don't whip the line thickness around. Waveform above
        # uses the raw value because the waveform IS the audio.
        line_w = self._audio_line_width()
        self._draw_triangle_lines(cr, self._cached_all_triangles, line_w, t)

        # GEAL §5.1 — publish video_attention every tick so GEAL and the
        # future WGSL parity node can scale their activation budgets.
        self._publish_video_attention()

    def _publish_video_attention(self, *, now: float | None = None) -> None:
        """Write the ``video_attention`` scalar to SHM (spec §5.1).

        ``video_attention = max(slot_opacity) * frame_freshness``. Slots
        with no cached frame surface contribute 0. Frames fresher than
        ``VIDEO_ATTENTION_FRESH_S`` plateau at freshness = 1.0, older
        frames decay exponentially with time constant
        ``VIDEO_ATTENTION_DECAY_TAU_S``.

        Atomic write (tmp + os.replace) so consumers never read a torn
        file. Best-effort — OSError is logged and swallowed; a missed
        publish just means GEAL falls back to its previous cached value.
        """
        now = time.time() if now is None else now
        max_attention = 0.0
        for slot_id in range(3):
            surface = self._frame_surfaces.get(slot_id)
            mtime = self._frame_mtimes.get(slot_id)
            if surface is None or mtime is None or mtime <= 0:
                continue
            age = now - mtime
            if age < VIDEO_ATTENTION_FRESH_S:
                freshness = 1.0
            else:
                freshness = math.exp(-(age - VIDEO_ATTENTION_FRESH_S) / VIDEO_ATTENTION_DECAY_TAU_S)
            attention = self._slot_opacity(slot_id, now=now) * freshness
            if attention > max_attention:
                max_attention = attention

        payload = struct.pack("<f", max_attention)
        try:
            VIDEO_ATTENTION_PATH.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(VIDEO_ATTENTION_PATH.parent),
                prefix=".video-attention.",
                suffix=".tmp",
                delete=False,
            ) as fh:
                fh.write(payload)
                tmp_path = fh.name
            os.replace(tmp_path, VIDEO_ATTENTION_PATH)
        except OSError:
            log.debug("video_attention publish failed", exc_info=True)

    def _rebuild_geometry_cache(self, canvas_w: int, canvas_h: int) -> None:
        """Recompute triangle vertices + inscribed rects for this canvas size.

        Called once per resize (and on first render). All downstream
        ticks reuse the cached geometry. Matches the drop #42 SIERP-1
        optimization.
        """
        fw = float(canvas_w)
        fh = float(canvas_h)

        # Main triangle (75% of height, slightly above center)
        tri = self._get_triangle(fw, fh, scale=0.75, y_offset=-0.02)

        # Level 1 subdivision: 3 corners + center void
        m01 = self._midpoint(tri[0], tri[1])
        m12 = self._midpoint(tri[1], tri[2])
        m02 = self._midpoint(tri[0], tri[2])

        corner_0 = [tri[0], m01, m02]  # top
        corner_1 = [m01, tri[1], m12]  # bottom-left
        corner_2 = [m02, m12, tri[2]]  # bottom-right
        center = [m01, m12, m02]  # center void

        # Level 2 subdivision lines (inside corners)
        all_triangles: list[list[tuple[float, float]]] = [tri, corner_0, corner_1, corner_2, center]
        for corner in (corner_0, corner_1, corner_2):
            cm01 = self._midpoint(corner[0], corner[1])
            cm12 = self._midpoint(corner[1], corner[2])
            cm02 = self._midpoint(corner[0], corner[2])
            all_triangles.extend(
                [
                    [corner[0], cm01, cm02],
                    [cm01, corner[1], cm12],
                    [cm02, cm12, corner[2]],
                    [cm01, cm12, cm02],
                ]
            )

        self._cached_all_triangles = all_triangles
        self._cached_corner_rects = [
            self._inscribed_rect(corner_0),
            self._inscribed_rect(corner_1),
            self._inscribed_rect(corner_2),
        ]
        self._cached_center_rect = self._inscribed_rect(center)
        self._geom_cache_size = (canvas_w, canvas_h)

    def geometry_cache(
        self,
        *,
        target_depth: int = 2,
        canvas_w: int = 1280,
        canvas_h: int = 720,
    ) -> GeometryCache:
        """Return the GEAL geometry cache for ``target_depth``.

        Memoised on ``(canvas_w, canvas_h, target_depth)`` — the same
        triple always returns the same content (tested by
        ``test_geometry_cache_deterministic``).

        ``target_depth`` must be in ``[0, 4]`` per spec §4.1 (L5 is the
        coherence cliff and is not reachable in v1). The returned
        :class:`GeometryCache` is a fresh object per call so callers can
        mutate without corrupting the cache.
        """
        if not 0 <= target_depth <= 4:
            raise ValueError(f"target_depth must be in [0, 4], got {target_depth}")

        key = (canvas_w, canvas_h, target_depth)
        cached = getattr(self, "_geal_geom_cache", {}).get(key)
        if cached is not None:
            # Return a shallow copy so callers can't mutate the cached payload.
            return GeometryCache(
                all_triangles=list(cached.all_triangles),
                corner_slivers=[list(triad) for triad in cached.corner_slivers],
                center_void=list(cached.center_void),
                vertex_halo_centers=list(cached.vertex_halo_centers),
                edge_polylines=dict(cached.edge_polylines),
                inscribed_rects=list(cached.inscribed_rects),
                target_depth=cached.target_depth,
            )

        geom = self._build_geometry_cache(canvas_w, canvas_h, target_depth)
        if not hasattr(self, "_geal_geom_cache"):
            self._geal_geom_cache: dict[tuple[int, int, int], GeometryCache] = {}
        self._geal_geom_cache[key] = geom
        return geom

    def _build_geometry_cache(
        self, canvas_w: int, canvas_h: int, target_depth: int
    ) -> GeometryCache:
        """Compute a fresh :class:`GeometryCache` — uncached."""
        fw = float(canvas_w)
        fh = float(canvas_h)
        root = self._get_triangle(fw, fh, scale=0.75, y_offset=-0.02)

        # Recurse: at each level, subdivide every solid (non-void) triangle
        # into 3 corner sub-triangles (void is tracked separately and not
        # recursed into — dyadic self-similarity preserves the centre void).
        levels: list[list[Polygon]] = [[list(root)]]
        for _ in range(target_depth):
            next_level: list[Polygon] = []
            for tri in levels[-1]:
                corners, _void = self._subdivide(tri)
                next_level.extend(corners)
            levels.append(next_level)

        all_triangles: list[Polygon] = []
        for level_tris in levels:
            all_triangles.extend(level_tris)

        # Corner slivers + center void + inscribed rects all come from the
        # L1 subdivision (the 3 L1 corners host the YT video rects; the L1
        # centre triangle hosts the centre-void field).
        l1_corners, l1_center = self._subdivide(list(root))
        inscribed_rects = [self._inscribed_rect(c) for c in l1_corners]
        corner_slivers = [
            self._corner_slivers(corner, rect)
            for corner, rect in zip(l1_corners, inscribed_rects, strict=True)
        ]

        # Edge polylines per level. Root edges use the canonical
        # "L0.<side>" names; deeper levels add a triangle index so each
        # edge has a unique key (used by G1 wavefront propagation).
        edge_polylines: dict[str, list[Point]] = {}
        _SIDES = ("top", "left", "right")
        for level_idx, level_tris in enumerate(levels):
            for tri_idx, tri in enumerate(level_tris):
                edges = [
                    [tri[0], tri[1]],  # top: apex → left-base
                    [tri[1], tri[2]],  # left: left-base → right-base
                    [tri[2], tri[0]],  # right: right-base → apex
                ]
                if level_idx == 0:
                    for side, edge in zip(_SIDES, edges, strict=True):
                        edge_polylines[f"L0.{side}"] = edge
                else:
                    for side, edge in zip(_SIDES, edges, strict=True):
                        edge_polylines[f"L{level_idx}.{tri_idx}.{side}"] = edge

        return GeometryCache(
            all_triangles=all_triangles,
            corner_slivers=corner_slivers,
            center_void=list(l1_center),
            vertex_halo_centers=[root[0], root[1], root[2]],
            edge_polylines=edge_polylines,
            inscribed_rects=inscribed_rects,
            target_depth=target_depth,
        )

    def _subdivide(self, tri: Polygon) -> tuple[list[Polygon], Polygon]:
        """Dyadic midpoint subdivision — returns (3 corner sub-triangles, centre void).

        Matches the existing ``_rebuild_geometry_cache`` logic but returned
        in a form the extended geometry cache can consume.
        """
        a, b, c = tri[0], tri[1], tri[2]
        m_ab = self._midpoint(a, b)
        m_bc = self._midpoint(b, c)
        m_ac = self._midpoint(a, c)
        corner_a: Polygon = [a, m_ab, m_ac]
        corner_b: Polygon = [m_ab, b, m_bc]
        corner_c: Polygon = [m_ac, m_bc, c]
        center: Polygon = [m_ab, m_bc, m_ac]
        return [corner_a, corner_b, corner_c], center

    def _corner_slivers(
        self,
        corner: Polygon,
        rect: tuple[float, float, float, float],
    ) -> list[Polygon]:
        """Decompose (corner minus inscribed rect) into apex/left/right slivers.

        The inscribed rect is axis-aligned. The three slivers are the
        regions of the corner triangle that fall outside the rect,
        approximated as three triangles anchored at each corner vertex of
        the triangle. This is a coarse topological decomposition
        sufficient for GEAL's clip-region use — the per-level stroke
        table (§4.2) clips L3/L4 edge work to these polygons so YT rects
        never get edge-muddied.
        """
        rx, ry, rw, rh = rect
        rect_tl: Point = (rx, ry)
        rect_tr: Point = (rx + rw, ry)
        rect_bl: Point = (rx, ry + rh)
        rect_br: Point = (rx + rw, ry + rh)

        # Identify apex (farthest from rect centre) and two base vertices.
        cx = rx + rw * 0.5
        cy = ry + rh * 0.5
        by_dist = sorted(
            corner,
            key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2,
            reverse=True,
        )
        apex = by_dist[0]
        # The remaining two are the base vertices; left/right by x.
        base = [by_dist[1], by_dist[2]]
        base.sort(key=lambda p: p[0])
        base_left, base_right = base[0], base[1]

        # Apex sliver: apex + the two rect corners closest to the apex
        # (top pair if apex is above rect, bottom pair otherwise).
        if apex[1] < cy:
            apex_sliver: Polygon = [apex, rect_tl, rect_tr]
        else:
            apex_sliver = [apex, rect_bl, rect_br]

        left_sliver: Polygon = [base_left, rect_tl, rect_bl]
        right_sliver: Polygon = [base_right, rect_tr, rect_br]
        return [apex_sliver, left_sliver, right_sliver]

    def _resolve_frame_path(self, slot_id: int) -> Path | None:
        """Return the selected local visual-pool frame for ``slot_id``."""
        asset = self._visual_pool_selector.select(slot_id)
        if asset is None:
            return None
        return asset.path

    def _load_frame(self, slot_id: int) -> cairo.ImageSurface | None:
        """Load a local visual-pool frame as a Cairo surface, with mtime caching."""
        path = self._resolve_frame_path(slot_id)
        if path is None or not path.exists():
            return self._frame_surfaces.get(slot_id)
        try:
            mtime = path.stat().st_mtime
            if mtime == self._frame_mtimes.get(slot_id, 0):
                return self._frame_surfaces.get(slot_id)
            surface = get_image_loader().load(path)
            if surface is None:
                return self._frame_surfaces.get(slot_id)
            self._frame_surfaces[slot_id] = surface
            self._frame_mtimes[slot_id] = mtime
            return surface
        except Exception:
            return self._frame_surfaces.get(slot_id)

    def _get_triangle(
        self, w: float, h: float, scale: float, y_offset: float
    ) -> list[tuple[float, float]]:
        """Compute main equilateral triangle vertices in pixel coords."""
        tri_h = scale * h * 0.866
        cx = w * 0.5
        cy = h * 0.5 + y_offset * h
        half_base = scale * h * 0.5
        return [
            (cx, cy - tri_h * 0.667),  # top
            (cx - half_base, cy + tri_h * 0.333),  # bottom-left
            (cx + half_base, cy + tri_h * 0.333),  # bottom-right
        ]

    def _midpoint(self, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    def _inscribed_rect(self, tri: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        """Compute the largest 16:9 rectangle inscribed in a triangle.

        Returns (x, y, width, height) of the rectangle centered in the triangle.
        The rectangle has one side parallel to the longest edge (base).
        """
        # Find the longest edge to use as the base
        edges = [
            (math.dist(tri[0], tri[1]), 0, 1, 2),
            (math.dist(tri[1], tri[2]), 1, 2, 0),
            (math.dist(tri[2], tri[0]), 2, 0, 1),
        ]
        edges.sort(key=lambda e: e[0], reverse=True)
        _, bi, bj, apex_idx = edges[0]

        base_a = tri[bi]
        base_b = tri[bj]
        apex = tri[apex_idx]

        # Base vector and perpendicular height
        bx = base_b[0] - base_a[0]
        by = base_b[1] - base_a[1]
        base_len = math.sqrt(bx * bx + by * by)
        if base_len < 1.0:
            return (0, 0, 0, 0)

        # Unit base direction and normal
        ux, uy = bx / base_len, by / base_len
        # Normal pointing toward apex
        nx, ny = -uy, ux
        apex_dot = (apex[0] - base_a[0]) * nx + (apex[1] - base_a[1]) * ny
        if apex_dot < 0:
            nx, ny = -nx, -ny
            apex_dot = -apex_dot
        tri_height = apex_dot

        # For a triangle, the largest rectangle with one side on the base:
        # optimal height = tri_height / 2, width = base_len / 2
        # But we want 16:9 aspect ratio, so constrain accordingly.
        aspect = 16.0 / 9.0
        # Max width at a given rect_h from base: w = base_len * (1 - rect_h / tri_height)
        # We want w / rect_h = aspect → base_len * (1 - rect_h/tri_height) = aspect * rect_h
        # → rect_h = base_len / (aspect + base_len / tri_height)
        rect_h = base_len / (aspect + base_len / tri_height)
        rect_w = aspect * rect_h

        # Clamp to triangle dimensions
        if rect_w > base_len * 0.95:
            rect_w = base_len * 0.95
            rect_h = rect_w / aspect
        if rect_h > tri_height * 0.95:
            rect_h = tri_height * 0.95
            rect_w = rect_h * aspect

        # Position: centered on base, offset inward by a small margin
        base_mid_x = (base_a[0] + base_b[0]) * 0.5
        base_mid_y = (base_a[1] + base_b[1]) * 0.5
        # Shift inward from base by a fraction of rect_h to center visually
        inward = rect_h * 0.35
        cx = base_mid_x + nx * inward
        cy = base_mid_y + ny * inward

        # Rectangle top-left corner (axis-aligned approximation)
        rx = cx - rect_w * 0.5
        ry = cy - rect_h * 0.5

        return (rx, ry, rect_w, rect_h)

    def _draw_video_in_triangle(
        self,
        cr: Any,
        surface: cairo.ImageSurface | None,
        rect: tuple[float, float, float, float],
        opacity: float,
    ) -> None:
        """Draw a video frame into a precomputed inscribed rectangle.

        Drop #42 SIERP-1: the inscribed rect is now precomputed at
        geometry-cache-build time (once per canvas resize) and passed
        in directly, rather than recomputed per tick per corner.
        """
        if surface is None or opacity < 0.01:
            return

        rx, ry, rw, rh = rect
        if rw < 1.0 or rh < 1.0:
            return

        cr.save()

        sw = surface.get_width()
        sh = surface.get_height()

        # Scale video to fill the inscribed rectangle (cover, maintain aspect)
        sx = rw / sw
        sy = rh / sh
        s = max(sx, sy)
        # Center within rectangle
        ox = rx + (rw - sw * s) * 0.5
        oy = ry + (rh - sh * s) * 0.5

        cr.rectangle(rx, ry, rw, rh)
        cr.clip()
        cr.translate(ox, oy)
        cr.scale(s, s)
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(opacity)

        cr.restore()

    def _draw_triangle_lines(
        self,
        cr: Any,
        triangles: list[list[tuple[float, float]]],
        line_width: float,
        t: float,
    ) -> None:
        """Draw triangle line work with synthwave colors, glow, and z-depth layers.

        Draws 3 passes at slightly different scales to create a parallax/
        depth effect — the Sierpinski appears to have multiple stacked
        transparent planes. Each pass uses a different color offset and
        decreasing alpha so the layers read as front-to-back depth.
        This makes the z-axis interdimensionality renderer-intrinsic
        rather than dependent on the active shader preset having a
        feedback/trail node.
        """
        _Z_LAYERS = 3
        _Z_SCALE_STEP = 0.012
        _Z_ALPHA_DECAY = 0.5

        for z in range(_Z_LAYERS):
            scale_offset = 1.0 + z * _Z_SCALE_STEP
            alpha_mult = _Z_ALPHA_DECAY**z
            color_shift = z * 2

            cr.save()
            cw = cr.get_target().get_width() if hasattr(cr.get_target(), "get_width") else 1280
            ch = cr.get_target().get_height() if hasattr(cr.get_target(), "get_height") else 720
            cx, cy = cw * 0.5, ch * 0.5
            cr.translate(cx, cy)
            cr.scale(scale_offset, scale_offset)
            cr.translate(-cx, -cy)

            for i, tri in enumerate(triangles):
                color_idx = (i + int(t * 0.5) + color_shift) % len(COLORS)
                r, g, b = COLORS[color_idx]

                # Glow (wider, semi-transparent)
                cr.set_line_width(line_width * 3.0)
                cr.set_source_rgba(r, g, b, 0.15 * alpha_mult)
                cr.move_to(*tri[0])
                cr.line_to(*tri[1])
                cr.line_to(*tri[2])
                cr.close_path()
                cr.stroke()

                # Core line
                cr.set_line_width(line_width)
                cr.set_source_rgba(r, g, b, 0.8 * alpha_mult)
                cr.move_to(*tri[0])
                cr.line_to(*tri[1])
                cr.line_to(*tri[2])
                cr.close_path()
                cr.stroke()

            cr.restore()

    def _audio_line_width(self) -> float:
        """Line width with bounded attack lift for percussive onsets.

        Smoothing stays in charge of the steady state, but rising raw
        energy can pull the line width partway forward. The old max
        width remains the ceiling, so this adds variance without growing
        the Sierpinski footprint or introducing an alpha flash.
        """
        raw = _clamp01(self._audio_energy)
        smoothed = _clamp01(self._audio_energy_smoothed)
        attack = max(0.0, raw - smoothed) * AUDIO_LINE_WIDTH_ATTACK_LIFT
        energy = min(1.0, smoothed + attack)
        line_width = AUDIO_LINE_WIDTH_BASE_PX + energy * AUDIO_LINE_WIDTH_SCALE_PX
        return min(AUDIO_LINE_WIDTH_MAX_PX, line_width)

    def _draw_waveform(
        self,
        cr: Any,
        rect: tuple[float, float, float, float],
        energy: float,
        t: float,
    ) -> None:
        """Draw waveform bars inside a precomputed inscribed rectangle.

        Drop #42 SIERP-1 + SIERP-3: rect is precomputed from the
        geometry cache. Phase argument is the ``t`` passed down from
        ``render()`` rather than a fresh ``time.monotonic()`` call,
        so the waveform phase stays consistent with the rest of the
        renderer's animation clock (correctness fix).
        """
        rx, ry, rw, rh = rect
        if rw < 1.0 or rh < 1.0:
            return

        cr.save()

        cy = ry + rh * 0.5

        # 8 bars spanning the full inscribed rectangle width
        bar_count = 8
        gap = rw * 0.03  # small gap between bars
        total_gap = gap * (bar_count - 1)
        bar_w = (rw - total_gap) / bar_count
        start_x = rx

        for i in range(bar_count):
            amp = (energy * 0.5 + 0.1) * (0.5 + 0.5 * math.sin(i * 0.8 + t * 2.0))
            bar_h = amp * rh * 0.85
            x = start_x + i * (bar_w + gap)
            y = cy - bar_h * 0.5

            cr.set_source_rgba(0.0, 0.9, 1.0, 0.9)  # cyan
            cr.rectangle(x, y, bar_w, bar_h)
            cr.fill()

        cr.restore()


class SierpinskiRenderer:
    """Compositor-side facade around the polymorphic Cairo source pipeline.

    Preserves the original public API (``start``/``stop``/``draw``/
    ``set_active_slot``/``set_audio_energy``) so existing call sites in
    ``fx_chain.py`` (instantiation) and ``overlay.py`` (synchronous draw
    callback) continue to work without changes.

    Internally:

    * Holds a :class:`SierpinskiCairoSource` for the per-frame draw logic
    * Holds a :class:`CairoSourceRunner` to drive it on a background
      thread at the configured FPS
    * Forwards ``draw()`` to the runner's cached output surface for the
      sub-millisecond GStreamer streaming-thread blit
    """

    def __init__(self, *, budget_tracker: BudgetTracker | None = None) -> None:
        # A+ Stage 2 audit B2 fix (2026-04-17): canvas dims pulled from
        # config module constants rather than hardcoded 1920x1080. When
        # the canvas drops to 720p, Sierpinski now allocates at the
        # matching resolution instead of rendering 1920x1080 and
        # downscaling — saves the pixel budget Stage 2 was meant to
        # recover.
        from .config import OUTPUT_HEIGHT, OUTPUT_WIDTH

        self._source = SierpinskiCairoSource()
        self._runner = CairoSourceRunner(
            source_id="sierpinski-lines",
            source=self._source,
            canvas_w=OUTPUT_WIDTH,
            canvas_h=OUTPUT_HEIGHT,
            target_fps=RENDER_FPS,
            budget_tracker=budget_tracker,
        )

    def start(self) -> None:
        """Start the background render thread."""
        self._runner.start()
        log.info("SierpinskiRenderer background thread started at %dfps", RENDER_FPS)

    def stop(self) -> None:
        """Stop the background render thread."""
        self._runner.stop()

    def set_active_slot(self, slot_id: int) -> None:
        self._source.set_active_slot(slot_id)

    def set_audio_energy(self, energy: float) -> None:
        self._source.set_audio_energy(energy)

    def draw(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        """Blit the pre-rendered output surface. Called from on_draw at 30fps.

        This method must be fast (<2ms) — it runs in the GStreamer streaming
        thread. All rendering happens in the background thread.
        """
        # Update canvas size for the runner — picked up on the next tick.
        self._runner.set_canvas_size(canvas_w, canvas_h)

        surface = self._runner.get_output_surface()
        if surface is not None:
            cr.set_source_surface(surface, 0, 0)
            cr.paint()
