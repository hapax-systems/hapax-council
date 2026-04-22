from __future__ import annotations

import math

from agents.studio_compositor.gem_rooms import (
    ROOM_BRIGHTNESS_CEILING,
    compute_room_tree,
    is_within_text_priority,
    room_brightness,
)


def test_compute_room_tree_geometry():
    # A simple 100x100 canvas with margin 4
    tree = compute_room_tree(100, 100, margin=4)
    # L1 (1) + L2 (4) + L3 (8) = 13 rooms
    assert len(tree) == 13

    # L1 room
    l1 = tree.rooms[0]
    assert l1.level == 1
    assert l1.x == 4
    assert l1.y == 4
    assert l1.w == 92
    assert l1.h == 92
    assert l1.phase_offset == 0.0

    # L2 rooms
    l2_rooms = [r for r in tree if r.level == 2]
    assert len(l2_rooms) == 4
    # Inner margin is 2 (margin 4 // 2)
    assert l2_rooms[0].x == l1.x + 2
    assert l2_rooms[0].y == l1.y + 2
    # L2 width = (92 - 6) // 2 = 43
    assert l2_rooms[0].w == 43
    assert l2_rooms[0].h == 43

    # L3 rooms
    l3_rooms = [r for r in tree if r.level == 3]
    assert len(l3_rooms) == 8


def test_room_brightness_envelope():
    tree = compute_room_tree(100, 100)
    l1 = tree.rooms[0]

    # At t=0, angle=0 -> cos(0)=1 -> raw=1.0 -> eased=1.0
    # brightness = 1.0 * ROOM_BRIGHTNESS_CEILING
    b_max = room_brightness(l1, 0.0)
    assert math.isclose(b_max, ROOM_BRIGHTNESS_CEILING, rel_tol=1e-5)

    # At angle=pi -> cos(pi)=-1 -> raw=0.0 -> eased=0.3
    # t = pi / (2 * pi * 0.15) = 1 / 0.3 = 3.333...
    b_min = room_brightness(l1, 1.0 / 0.3)
    assert math.isclose(b_min, 0.3 * ROOM_BRIGHTNESS_CEILING, rel_tol=1e-5)


def test_is_within_text_priority():
    assert is_within_text_priority(0.5, 0.95)
    assert not is_within_text_priority(1.0, 0.95)
    assert is_within_text_priority(ROOM_BRIGHTNESS_CEILING, 0.95)
