"""Tile layout computation for the compositor canvas."""

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


def compute_tile_layout(
    cameras: list[CameraSpec],
    canvas_w: int = OUTPUT_WIDTH,
    canvas_h: int = OUTPUT_HEIGHT,
) -> dict[str, TileRect]:
    """Compute tile positions for each camera on the output canvas.

    Hero camera (if any) gets the left portion, others stack vertically on the right.
    All tiles are 16:9 fitted and centered within their allocated slots.
    """
    n = len(cameras)
    if n == 0:
        return {}

    heroes = [c for c in cameras if c.hero]
    others = [c for c in cameras if not c.hero]

    layout: dict[str, TileRect] = {}

    if heroes and len(others) >= 1:
        hero = heroes[0]
        if len(others) <= 4:
            hero_slot_w = (canvas_w * 2) // 3
        else:
            hero_slot_w = canvas_w // 2
        hero_slot_h = canvas_h

        hx, hy, hw, hh = _fit_16x9(hero_slot_w, hero_slot_h)
        layout[hero.role] = TileRect(x=hx, y=hy, w=hw, h=hh)

        right_x = hero_slot_w
        right_w = canvas_w - hero_slot_w
        slot_h = canvas_h // len(others)

        for i, cam in enumerate(others):
            sx, sy, sw, sh = _fit_16x9(right_w, slot_h)
            layout[cam.role] = TileRect(
                x=right_x + sx,
                y=i * slot_h + sy,
                w=sw,
                h=sh,
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
            layout[cam.role] = TileRect(
                x=col * slot_w + sx,
                y=row * slot_h + sy,
                w=sw,
                h=sh,
            )

    return layout
