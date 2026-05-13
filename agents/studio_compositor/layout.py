"""Tile layout computation for the compositor canvas.

Layout modes:
- "balanced" (default): grid layout, all cameras equal-sized, honoring any hero flag
- "hero/{role}": one camera takes left 2/3 (or 1/2 if many cameras), others stack right
- "sierpinski": 3 specific cameras fitted to the inscribed rectangles of a Sierpinski
  triangle's 3 corners; other cameras hidden (width=0, height=0, off-canvas).
"""

from __future__ import annotations

import math

from .config import OUTPUT_HEIGHT, OUTPUT_WIDTH
from .models import CameraSpec, TileRect


def _fit_16x9(w: int, h: int) -> tuple[int, int, int, int]:
    """Compute largest 16:9 rect fitting in w x h, return (x_off, y_off, fit_w, fit_h)."""
    target_ratio = 16 / 9
    if w / h > target_ratio:
        fit_h = h
        fit_w = int(h * target_ratio)
    else:
        fit_w = w
        fit_h = int(w / target_ratio)
    x_off = (w - fit_w) // 2
    y_off = (h - fit_h) // 2
    return x_off, y_off, fit_w, fit_h


def _hidden_tile() -> TileRect:
    """Tile rect for a camera that should not appear in the output.

    Width 1 + negative x position — GStreamer compositor accepts this and
    effectively removes the camera from view without triggering pad
    renegotiation.
    """
    return TileRect(x=-10, y=-10, w=1, h=1)


def _balanced_layout(
    cameras: list[CameraSpec], canvas_w: int, canvas_h: int
) -> dict[str, TileRect]:
    """Grid layout with optional hero (honors CameraSpec.hero flag)."""
    n = len(cameras)
    if n == 0:
        return {}

    heroes = [c for c in cameras if c.hero]
    others = [c for c in cameras if not c.hero]

    layout: dict[str, TileRect] = {}

    if heroes and len(others) >= 1:
        hero = heroes[0]
        hero_slot_w = (canvas_w * 2) // 3 if len(others) <= 4 else canvas_w // 2
        hero_slot_h = canvas_h

        hx, hy, hw, hh = _fit_16x9(hero_slot_w, hero_slot_h)
        layout[hero.role] = TileRect(x=hx, y=hy, w=hw, h=hh)

        right_x = hero_slot_w
        right_w = canvas_w - hero_slot_w
        slot_h = canvas_h // len(others)

        for i, cam in enumerate(others):
            sx, sy, sw, sh = _fit_16x9(right_w, slot_h)
            layout[cam.role] = TileRect(x=right_x + sx, y=i * slot_h + sy, w=sw, h=sh)

        # Virtual tile (underscore prefix → no GStreamer pad). HeroSmallOverlay
        # draws the raw hero JPEG snapshot here as a PIP "raw monitor" inset
        # in the bottom-right of the hero rect. ~25% of hero width.
        small_w = hw // 4
        small_h = int(small_w * 9 / 16)
        margin = max(8, hw // 80)
        layout["_hero_small"] = TileRect(
            x=hx + hw - small_w - margin,
            y=hy + hh - small_h - margin,
            w=small_w,
            h=small_h,
        )
    else:
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        slot_w = canvas_w // cols
        slot_h = canvas_h // rows
        for i, cam in enumerate(cameras):
            col = i % cols
            row = i // cols
            sx, sy, sw, sh = _fit_16x9(slot_w, slot_h)
            layout[cam.role] = TileRect(x=col * slot_w + sx, y=row * slot_h + sy, w=sw, h=sh)

    return layout


def _hero_layout(
    cameras: list[CameraSpec], hero_role: str, canvas_w: int, canvas_h: int
) -> dict[str, TileRect]:
    """One named camera takes the left 2/3; others stack on the right."""
    hero = next((c for c in cameras if c.role == hero_role), None)
    others = [c for c in cameras if c.role != hero_role]
    if hero is None or not others:
        # Fallback to balanced if the requested hero is missing
        return _balanced_layout(cameras, canvas_w, canvas_h)

    layout: dict[str, TileRect] = {}
    hero_slot_w = (canvas_w * 2) // 3 if len(others) <= 4 else canvas_w // 2

    hx, hy, hw, hh = _fit_16x9(hero_slot_w, canvas_h)
    layout[hero.role] = TileRect(x=hx, y=hy, w=hw, h=hh)

    right_x = hero_slot_w
    right_w = canvas_w - hero_slot_w
    slot_h = canvas_h // len(others)
    for i, cam in enumerate(others):
        sx, sy, sw, sh = _fit_16x9(right_w, slot_h)
        layout[cam.role] = TileRect(x=right_x + sx, y=i * slot_h + sy, w=sw, h=sh)

    return layout


def _follow_layout(
    cameras: list[CameraSpec], hero_role: str, canvas_w: int, canvas_h: int
) -> dict[str, TileRect]:
    """Bounded follow-mode salience layout.

    Follow mode is a live director move, not permission to expose every
    camera branch. The earlier implementation repinned the balanced layout,
    which made all cameras visible and repeatedly pushed egress below the
    frame floor. This layout keeps the selected role large, preserves a
    small two-camera context stack, and hides the rest.
    """
    if not cameras:
        return {}
    hero = next((c for c in cameras if c.role == hero_role), None)
    if hero is None:
        hero = next((c for c in cameras if c.hero), cameras[0])
    context = [c for c in cameras if c.role != hero.role][:2]

    layout = {cam.role: _hidden_tile() for cam in cameras}
    hero_slot_w = int(canvas_w * 0.62)
    hx, hy, hw, hh = _fit_16x9(hero_slot_w, canvas_h)
    layout[hero.role] = TileRect(x=hx, y=hy, w=hw, h=hh)

    if context:
        right_x = hero_slot_w
        right_w = canvas_w - hero_slot_w
        gap = max(8, canvas_w // 160)
        slot_h = (canvas_h - gap * (len(context) + 1)) // len(context)
        for i, cam in enumerate(context):
            sx, sy, sw, sh = _fit_16x9(right_w, slot_h)
            y = gap + i * (slot_h + gap) + sy
            layout[cam.role] = TileRect(x=right_x + sx, y=y, w=sw, h=sh)

    small_w = hw // 4
    small_h = int(small_w * 9 / 16)
    margin = max(8, hw // 80)
    layout["_hero_small"] = TileRect(
        x=hx + hw - small_w - margin,
        y=hy + hh - small_h - margin,
        w=small_w,
        h=small_h,
    )
    return layout


def _sierpinski_layout(
    cameras: list[CameraSpec], canvas_w: int, canvas_h: int
) -> dict[str, TileRect]:
    """Three cameras fitted into the 3 corner inscribed rectangles.

    Uses the same geometry as SierpinskiRenderer._inscribed_rect(). Cameras
    beyond the first 3 are hidden. The triangle scale is 0.75 of canvas
    height, centered slightly above center (same as the renderer).
    """
    layout: dict[str, TileRect] = {}
    if not cameras:
        return layout

    # Triangle vertices (matches sierpinski_renderer._get_triangle(scale=0.75, y_off=-0.02))
    scale = 0.75
    y_offset = -0.02
    tri_h = scale * canvas_h * 0.866
    cx = canvas_w * 0.5
    cy = canvas_h * 0.5 + y_offset * canvas_h
    half_base = scale * canvas_h * 0.5
    tri = [
        (cx, cy - tri_h * 0.667),  # top
        (cx - half_base, cy + tri_h * 0.333),  # bottom-left
        (cx + half_base, cy + tri_h * 0.333),  # bottom-right
    ]

    def midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    m01 = midpoint(tri[0], tri[1])
    m12 = midpoint(tri[1], tri[2])
    m02 = midpoint(tri[0], tri[2])

    corners = [
        [tri[0], m01, m02],  # top
        [m01, tri[1], m12],  # bottom-left
        [m02, m12, tri[2]],  # bottom-right
    ]

    def inscribed_rect(
        tri_pts: list[tuple[float, float]],
    ) -> tuple[int, int, int, int]:
        """Largest 16:9 rect inscribed in the triangle (same math as renderer)."""
        edges = [
            (math.dist(tri_pts[0], tri_pts[1]), 0, 1, 2),
            (math.dist(tri_pts[1], tri_pts[2]), 1, 2, 0),
            (math.dist(tri_pts[2], tri_pts[0]), 2, 0, 1),
        ]
        edges.sort(key=lambda e: e[0], reverse=True)
        _, bi, bj, apex_idx = edges[0]
        base_a = tri_pts[bi]
        base_b = tri_pts[bj]
        apex = tri_pts[apex_idx]

        bx = base_b[0] - base_a[0]
        by = base_b[1] - base_a[1]
        base_len = math.sqrt(bx * bx + by * by)
        if base_len < 1.0:
            return (0, 0, 0, 0)

        ux, uy = bx / base_len, by / base_len
        nx, ny = -uy, ux
        apex_dot = (apex[0] - base_a[0]) * nx + (apex[1] - base_a[1]) * ny
        if apex_dot < 0:
            nx, ny = -nx, -ny
            apex_dot = -apex_dot
        tri_height = apex_dot

        aspect = 16.0 / 9.0
        rect_h = base_len / (aspect + base_len / tri_height)
        rect_w = aspect * rect_h

        if rect_w > base_len * 0.95:
            rect_w = base_len * 0.95
            rect_h = rect_w / aspect
        if rect_h > tri_height * 0.95:
            rect_h = tri_height * 0.95
            rect_w = rect_h * aspect

        base_mid_x = (base_a[0] + base_b[0]) * 0.5
        base_mid_y = (base_a[1] + base_b[1]) * 0.5
        inward = rect_h * 0.35
        center_x = base_mid_x + nx * inward
        center_y = base_mid_y + ny * inward
        rx = center_x - rect_w * 0.5
        ry = center_y - rect_h * 0.5
        return (int(rx), int(ry), int(rect_w), int(rect_h))

    # First 3 cameras → 3 corners. Remaining → hidden.
    for i, cam in enumerate(cameras):
        if i < 3:
            x, y, w, h = inscribed_rect(corners[i])
            layout[cam.role] = TileRect(x=x, y=y, w=w, h=h)
        else:
            layout[cam.role] = _hidden_tile()

    return layout


def _packed_layout(cameras: list[CameraSpec], canvas_w: int, canvas_h: int) -> dict[str, TileRect]:
    """Compositor-native camera packing — all cameras on cudacompositor.

    Hero upper-left (~30% width). 4 non-hero cameras in 2x2 grid below
    hero. Remaining cameras stacked right of hero. All non-hero tiles
    same size. Virtual `_hero_small` PIP slot in the right column for
    HeroSmallOverlay.
    """
    layout: dict[str, TileRect] = {}
    if not cameras:
        return layout

    heroes = [c for c in cameras if c.hero]
    hero = heroes[0] if heroes else cameras[0]
    others = [c for c in cameras if c.role != hero.role]

    margin = 10
    gap = 4
    hero_w = int(canvas_w * 0.30)
    hero_h = int(hero_w * 9 / 16)
    layout[hero.role] = TileRect(x=margin, y=margin, w=hero_w, h=hero_h)

    tile_w = (hero_w - gap) // 2
    tile_h = int(tile_w * 9 / 16)

    grid_y = margin + hero_h + gap
    grid_cameras = others[:4]
    for i, cam in enumerate(grid_cameras):
        col = i % 2
        row = i // 2
        tx = margin + col * (tile_w + gap)
        ty = grid_y + row * (tile_h + gap)
        layout[cam.role] = TileRect(x=tx, y=ty, w=tile_w, h=tile_h)

    right_x = margin + hero_w + gap
    right_idx = 0
    for cam in others[4:]:
        ty = margin + right_idx * (tile_h + gap)
        layout[cam.role] = TileRect(x=right_x, y=ty, w=tile_w, h=tile_h)
        right_idx += 1

    hero_small_y = margin + right_idx * (tile_h + gap)
    layout["_hero_small"] = TileRect(x=right_x, y=hero_small_y, w=tile_w, h=tile_h)

    return layout


_FORCEFIELD_POSITIONS: list[tuple[float, float]] = [
    (0.047, 0.083),
    (0.813, 0.067),
    (0.047, 0.750),
    (0.813, 0.792),
    (0.344, 0.403),
    (0.602, 0.556),
]

_SEMANTIC_PRIORITY_ORDER: list[str] = [
    "turntables",
    "room-wide",
    "operator-face",
    "operator-hands",
    "operator-desk-topdown",
    "outboard-gear",
]


def _forcefield_layout(
    cameras: list[CameraSpec], canvas_w: int, canvas_h: int
) -> dict[str, TileRect]:
    """Arnheim force-field layout — cameras as distributed mass-points.

    All cameras equal-sized. Placed at 6 structural tension points that
    create cross-canvas perceptual forces (3 semantic axes: watching,
    activity, equipment). Sierpinski center remains open. No hero.
    """
    layout: dict[str, TileRect] = {}
    if not cameras:
        return layout

    n = len(cameras)
    tile_w = max(120, int(canvas_w * 0.156))
    tile_h = int(tile_w * 9 / 16)

    by_role: dict[str, CameraSpec] = {c.semantic_role: c for c in cameras}
    ordered: list[CameraSpec] = []
    used: set[str] = set()
    for sr in _SEMANTIC_PRIORITY_ORDER:
        if sr in by_role and by_role[sr].role not in used:
            ordered.append(by_role[sr])
            used.add(by_role[sr].role)
    for c in cameras:
        if c.role not in used:
            ordered.append(c)
            used.add(c.role)

    positions = _FORCEFIELD_POSITIONS[:n]
    if n > len(_FORCEFIELD_POSITIONS):
        extra = n - len(_FORCEFIELD_POSITIONS)
        for i in range(extra):
            t = (i + 1) / (extra + 1)
            px = 0.15 + 0.7 * t
            py = 0.2 + 0.15 * math.sin(t * math.pi)
            positions.append((px, py))

    for cam, (fx, fy) in zip(ordered, positions, strict=False):
        x = int(fx * canvas_w)
        y = int(fy * canvas_h)
        x = max(0, min(x, canvas_w - tile_w))
        y = max(0, min(y, canvas_h - tile_h))
        layout[cam.role] = TileRect(x=x, y=y, w=tile_w, h=tile_h)

    return layout


def compute_tile_layout(
    cameras: list[CameraSpec],
    canvas_w: int = OUTPUT_WIDTH,
    canvas_h: int = OUTPUT_HEIGHT,
    mode: str = "balanced",
) -> dict[str, TileRect]:
    """Compute tile positions for each camera on the output canvas.

    Args:
        cameras: Camera specs to lay out.
        canvas_w, canvas_h: Output canvas dimensions.
        mode: Layout mode. One of:
            - "balanced" — grid layout, honors CameraSpec.hero flag (default)
            - "hero/{role}" — named camera dominant, others stacked right
            - "packed/{role}" — named camera as hero in packed constellation
            - "follow/{role}" — named camera as salience inside balanced posture
            - "sierpinski" — 3 cameras in triangle corners, rest hidden
            - "packed" — hero upper-left + 2x2 grid + stacked right column
            - "forcefield" — Arnheim force-field, cameras as mass-points
    """
    if mode == "forcefield":
        return _forcefield_layout(cameras, canvas_w, canvas_h)
    if mode == "packed":
        return _packed_layout(cameras, canvas_w, canvas_h)
    if mode.startswith("packed/"):
        hero_role = mode[len("packed/") :]
        repinned = [c.model_copy(update={"hero": (c.role == hero_role)}) for c in cameras]
        return _packed_layout(repinned, canvas_w, canvas_h)
    if mode.startswith("follow/"):
        hero_role = mode[len("follow/") :]
        return _follow_layout(cameras, hero_role, canvas_w, canvas_h)
    if mode == "sierpinski":
        return _sierpinski_layout(cameras, canvas_w, canvas_h)
    if mode.startswith("hero/"):
        hero_role = mode[len("hero/") :]
        return _hero_layout(cameras, hero_role, canvas_w, canvas_h)
    # Default: balanced
    return _balanced_layout(cameras, canvas_w, canvas_h)


def compute_safe_tile_layout(
    cameras: list[CameraSpec],
    canvas_w: int = OUTPUT_WIDTH,
    canvas_h: int = OUTPUT_HEIGHT,
    mode: str = "balanced",
) -> dict[str, TileRect]:
    """Compute a selectable tile layout and enforce the live safety contract."""

    from .layout_safety import require_safe_tile_layout, validate_tile_layout

    layout = compute_tile_layout(cameras, canvas_w, canvas_h, mode=mode)
    report = validate_tile_layout(
        cameras,
        layout,
        mode=mode,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
    )
    require_safe_tile_layout(report)
    return layout
