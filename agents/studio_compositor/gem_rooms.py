"""GEM nested CP437 box-draw rooms — Candidate C Phase 2 (Layer 2).

Three depth levels of CP437-grammar "rooms" composited between the
Gray-Scott substrate (Layer 1, Phase 1) and the text mural (existing v1
behavior). The geometry is the structural analog of Sierpinski's L1/L2
corner subdivisions, translated into a text-grid: a single L1 room
encloses the canvas; L2 splits the L1 interior into 4 quadrant rooms;
L3 further subdivides each L2 cell into 2 horizontal sub-rooms.

Per the brainstorm doc (`docs/research/2026-04-22-gem-rendering-redesign-brainstorm.md`)
each room carries an independent intensity signal that modulates its
brightness over time. Phase 2 ships a deterministic per-room sine
oscillator with phase-staggered offsets so every room breathes at a
slightly different rhythm — enough motion to read as Sierpinski-class
recursive depth without yet wiring producer signal bindings (those
arrive with the schema-v2 / fragment punch-in work in Phase 3).

Anti-pattern guards: the rooms are line-art only; no faces, no eyes, no
expressions. The HARDM principle (`feedback_no_blinking_homage_wards`)
applies — brightness modulation uses smooth ease envelopes, not blinks.
The room brightness is hard-clamped to ROOM_BRIGHTNESS_CEILING so the
room layer never out-shines the text layer either.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# CP437 box-draw vocabulary. The double-line set (╔═╗║╚╝) is reserved
# for the outermost (L1) room; nested levels use single-line (┌─┐│└┘)
# and dotted-line (╌╎) so depth reads visually without anti-aliasing.
ROOM_GLYPHS_DOUBLE = {
    "tl": "╔",
    "tr": "╗",
    "bl": "╚",
    "br": "╝",
    "h": "═",
    "v": "║",
}
ROOM_GLYPHS_SINGLE = {
    "tl": "┌",
    "tr": "┐",
    "bl": "└",
    "br": "┘",
    "h": "─",
    "v": "│",
}
ROOM_GLYPHS_DOTTED = {
    "tl": "┌",
    "tr": "┐",
    "bl": "└",
    "br": "┘",
    "h": "╌",
    "v": "╎",
}

# Brightness ceiling for the room layer. Same logic as the substrate's
# ceiling: text alpha ≥ 0.95 so room brightness ≤ 0.55 leaves ≥0.40
# contrast headroom. The room layer can be brighter than the substrate
# (which sits at 0.35) because rooms are line-art, not field-fill — they
# occupy fewer pixels and therefore carry more visual weight per pixel.
ROOM_BRIGHTNESS_CEILING = 0.55

# Number of rooms at each level. L1 is always 1; L2 is 4 quadrants;
# L3 is 2 horizontal sub-rooms per L2, so 8 total.
LEVEL_CHILD_COUNT = (1, 4, 2)


@dataclass(frozen=True)
class RoomRect:
    """A room's geometry in canvas pixels and its modulation phase.

    The phase is a static per-room float in `[0, 2π)` used to stagger
    the brightness oscillation across rooms so they breathe out of
    sync with each other (no synchronized blinking — see
    `feedback_no_blinking_homage_wards`).
    """

    level: int
    index_in_level: int
    x: int
    y: int
    w: int
    h: int
    phase_offset: float
    glyphs: dict[str, str]


@dataclass(frozen=True)
class RoomTree:
    """Flat list of all rooms across all levels — render order is L1→L3."""

    rooms: tuple[RoomRect, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.rooms)

    def __iter__(self):
        return iter(self.rooms)


def compute_room_tree(canvas_w: int, canvas_h: int, *, margin: int = 4) -> RoomTree:
    """Build the 3-level nested room geometry for a canvas.

    Phase offsets are deterministic (function of room index) so the
    tree is identical across renders for a given canvas size. This
    lets tests pin specific brightness expectations without flake.
    """
    if canvas_w <= 0 or canvas_h <= 0:
        raise ValueError(f"canvas dimensions must be positive, got {canvas_w}x{canvas_h}")
    if margin < 0:
        raise ValueError(f"margin must be non-negative, got {margin}")

    rooms: list[RoomRect] = []

    # L1 — single outer room enclosing the canvas (with margin).
    l1 = RoomRect(
        level=1,
        index_in_level=0,
        x=margin,
        y=margin,
        w=canvas_w - 2 * margin,
        h=canvas_h - 2 * margin,
        phase_offset=0.0,
        glyphs=ROOM_GLYPHS_DOUBLE,
    )
    rooms.append(l1)

    # L2 — 4 quadrants inside L1, with their own internal margin.
    inner_margin = max(2, margin // 2)
    l2_x0 = l1.x + inner_margin
    l2_y0 = l1.y + inner_margin
    l2_w = (l1.w - 3 * inner_margin) // 2
    l2_h = (l1.h - 3 * inner_margin) // 2
    for q_index in range(LEVEL_CHILD_COUNT[1]):
        col = q_index % 2
        row = q_index // 2
        x = l2_x0 + col * (l2_w + inner_margin)
        y = l2_y0 + row * (l2_h + inner_margin)
        # Stagger phases evenly around the unit circle.
        phase = (q_index / LEVEL_CHILD_COUNT[1]) * 2.0 * math.pi
        rooms.append(
            RoomRect(
                level=2,
                index_in_level=q_index,
                x=x,
                y=y,
                w=l2_w,
                h=l2_h,
                phase_offset=phase,
                glyphs=ROOM_GLYPHS_SINGLE,
            )
        )

    # L3 — 2 horizontal sub-rooms inside each L2.
    l3_inner_margin = max(1, inner_margin // 2)
    l3_index = 0
    for parent_idx in range(LEVEL_CHILD_COUNT[1]):
        parent = rooms[1 + parent_idx]  # rooms[0] is L1; L2 starts at index 1
        sub_w = (parent.w - 3 * l3_inner_margin) // 2
        sub_h = parent.h - 2 * l3_inner_margin
        for sub_index in range(LEVEL_CHILD_COUNT[2]):
            x = parent.x + l3_inner_margin + sub_index * (sub_w + l3_inner_margin)
            y = parent.y + l3_inner_margin
            # Continue staggering around the unit circle, offset from L2.
            phase = (l3_index / (LEVEL_CHILD_COUNT[1] * LEVEL_CHILD_COUNT[2])) * 2.0 * math.pi
            phase += math.pi  # half-cycle offset so L3 anti-phases L2
            rooms.append(
                RoomRect(
                    level=3,
                    index_in_level=l3_index,
                    x=x,
                    y=y,
                    w=sub_w,
                    h=sub_h,
                    phase_offset=phase,
                    glyphs=ROOM_GLYPHS_DOTTED,
                )
            )
            l3_index += 1

    return RoomTree(rooms=tuple(rooms))


def room_brightness(room: RoomRect, t: float, *, hz: float = 0.15) -> float:
    """Smooth-envelope brightness in `[0, ROOM_BRIGHTNESS_CEILING]`.

    Uses cosine for the smooth ease curve required by HARDM ("no
    blinking, no flash"), with `hz` low enough that the breathing is
    visible but never reads as a flash (15 cycles per 100s = period
    of ~6.7s per cycle).
    """
    angle = 2.0 * math.pi * hz * t + room.phase_offset
    # cos(angle) ranges [-1, 1]; lift to [0.3, 1.0] so even at the
    # darkest point the room is visible — full darkness reads as a flash
    # to the eye when it returns.
    raw = (math.cos(angle) + 1.0) * 0.5  # [0, 1]
    eased = 0.3 + 0.7 * raw  # [0.3, 1.0]
    return eased * ROOM_BRIGHTNESS_CEILING


def is_within_text_priority(room_max: float, text_alpha: float) -> bool:
    """Verify the room layer cannot out-shine the text layer."""
    return room_max <= text_alpha


__all__ = [
    "LEVEL_CHILD_COUNT",
    "ROOM_BRIGHTNESS_CEILING",
    "ROOM_GLYPHS_DOTTED",
    "ROOM_GLYPHS_DOUBLE",
    "ROOM_GLYPHS_SINGLE",
    "RoomRect",
    "RoomTree",
    "compute_room_tree",
    "is_within_text_priority",
    "room_brightness",
]
