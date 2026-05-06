"""Packed-cameras Cairo source — renders camera frames flush along Sierpinski edges.

Camera frames tile the LEFT and RIGHT edges of the Sierpinski triangle,
rotated to match the edge angle so they sit perfectly flush.  Hero camera
stays on ``cudacompositor`` (upper-left corner, axis-aligned).

Layout (1920×1080 authored coords):

    ┌──────────────────────────────────────────┐
    │ ┌HERO┐        ╱╲                         │
    │ └────┘      ╱    ╲                        │
    │          ▐3▌╱      ╲▐4▌                    │
    │        ▐2▌╱  SIERP  ╲▐5▌                   │
    │      ▐1▌╱              ╲                   │
    │        ╱────────────────╲                  │
    └──────────────────────────────────────────┘

Frames 1-3 tile the left edge, frames 4-5 tile the right edge.
Each frame is rotated to match the edge slope (~60°/~120°).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import cairo

from .cairo_source import CairoSource

log = logging.getLogger(__name__)

# Camera roles — hero is excluded; these tile the triangle edges.
# Left edge (2 cameras, at bottom of edge — opens upper-left for hero):
_LEFT_ROLES = ["c920-desk", "c920-overhead"]
# Right edge (3 cameras, at bottom of edge):
_RIGHT_ROLES = ["brio-room", "c920-room", "brio-synths"]

_HERO_ROLE = "brio-operator"


@dataclass
class PackedSlot:
    """A camera slot flush against a triangle edge."""

    role: str
    cx: float  # center x (canvas coords)
    cy: float  # center y (canvas coords)
    w: float  # frame width (long axis, along edge)
    h: float  # frame height (short axis, perpendicular)
    rotation: float  # radians


def _compute_packed_slots(canvas_w: int, canvas_h: int) -> list[PackedSlot]:
    """Compute camera slots flush along the Sierpinski triangle's side edges.

    Geometry matches sierpinski_renderer (scale=0.75, y_offset=-0.02).
    """
    fw, fh = float(canvas_w), float(canvas_h)

    # Triangle vertices
    scale = 0.75
    y_offset = -0.02
    tri_h = scale * fh * 0.866
    cx = fw * 0.5
    cy = fh * 0.5 + y_offset * fh
    half_base = scale * fh * 0.5

    # Triangle vertices — MUST match sierpinski_renderer._get_triangle exactly
    apex = (cx, cy - tri_h * 0.667)
    bl = (cx - half_base, cy + tri_h * 0.333)
    br = (cx + half_base, cy + tri_h * 0.333)

    # Edge vectors and length
    left_dx, left_dy = bl[0] - apex[0], bl[1] - apex[1]
    right_dx, right_dy = br[0] - apex[0], br[1] - apex[1]
    edge_len = math.hypot(left_dx, left_dy)

    # Unit vectors along edges
    left_ux, left_uy = left_dx / edge_len, left_dy / edge_len
    right_ux, right_uy = right_dx / edge_len, right_dy / edge_len

    # Outward normals (perpendicular, pointing AWAY from triangle interior)
    # Used for POSITION offset so frames sit outside the edges.
    # Left edge: rotate edge direction +90° (CCW) to face outward
    left_nx, left_ny = -left_uy, left_ux
    # Right edge: rotate edge direction -90° (CW) to face outward
    right_nx, right_ny = right_uy, -right_ux

    # Edge angles for frame rotation — add π so content faces INWARD
    # (position is outward, but the rendered image points toward center)
    left_angle = math.atan2(left_dy, left_dx) + math.pi
    right_angle = math.atan2(right_dy, right_dx) + math.pi

    # Frame sizing: uniform (edge_len/3), same on both sides
    n_left = len(_LEFT_ROLES)  # 2
    n_right = len(_RIGHT_ROLES)  # 3
    n_max = max(n_left, n_right)  # 3

    frame_w = edge_len / n_max  # long axis
    frame_h = frame_w * 9.0 / 16.0  # short axis (16:9)

    slots: list[PackedSlot] = []

    # Left edge: tile from bottom-left vertex upward (opens upper-left for hero)
    for k in range(n_left):
        # t=1.0 is bottom-left vertex, t=0 is apex
        t = 1.0 - (frame_w / 2.0 + k * frame_w) / edge_len
        px = apex[0] + t * left_dx
        py = apex[1] + t * left_dy
        offset = frame_h / 2.0
        slot_cx = px + left_nx * offset
        slot_cy = py + left_ny * offset
        slots.append(
            PackedSlot(
                role=_LEFT_ROLES[k],
                cx=slot_cx,
                cy=slot_cy,
                w=frame_w,
                h=frame_h,
                rotation=left_angle,
            )
        )

    # Right edge: tile from bottom-right vertex upward
    for k in range(n_right):
        t = 1.0 - (frame_w / 2.0 + k * frame_w) / edge_len
        px = apex[0] + t * right_dx
        py = apex[1] + t * right_dy
        offset = frame_h / 2.0
        slot_cx = px + right_nx * offset
        slot_cy = py + right_ny * offset
        slots.append(
            PackedSlot(
                role=_RIGHT_ROLES[k],
                cx=slot_cx,
                cy=slot_cy,
                w=frame_w,
                h=frame_h,
                rotation=right_angle,
            )
        )

    return slots


class PackedCamerasCairoSource(CairoSource):
    """Renders non-hero camera frames flush along the Sierpinski triangle edges.

    Reads NV12 frames from :mod:`frame_cache`, converts to Cairo surfaces,
    and draws them rotated to match the triangle edge slope.
    """

    def __init__(self) -> None:
        self._slots: list[PackedSlot] | None = None
        self._cache_size: tuple[int, int] | None = None
        self._surfaces: dict[str, cairo.ImageSurface | None] = {}
        self._surface_ids: dict[str, int] = {}

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        # Rebuild slot geometry on canvas resize
        if self._cache_size != (canvas_w, canvas_h):
            self._slots = _compute_packed_slots(canvas_w, canvas_h)
            self._cache_size = (canvas_w, canvas_h)

        assert self._slots is not None

        # Ensure we start with a transparent canvas (OPERATOR_OVER default
        # is correct — we only ADD pixels, never overwrite the background).
        from . import frame_cache

        for slot in self._slots:
            frame = frame_cache.get(slot.role)
            if frame is None:
                continue

            surface = self._get_or_convert_surface(slot.role, frame)
            if surface is None:
                continue

            self._draw_rotated_frame(cr, surface, slot)

    def _get_or_convert_surface(self, role: str, frame: Any) -> cairo.ImageSurface | None:
        """Convert frame_cache data to a Cairo ImageSurface (cached)."""
        cached = self._surfaces.get(role)
        if cached is not None and id(frame.data) == self._surface_ids.get(role, 0):
            return cached

        try:
            import numpy as np

            w, h = frame.width, frame.height

            if frame.format == "NV12":
                expected = w * h * 3 // 2
                if len(frame.data) < expected:
                    return cached
                y = np.frombuffer(frame.data, np.uint8, count=w * h).reshape(h, w)
                uv = np.frombuffer(frame.data, np.uint8, offset=w * h, count=w * h // 2).reshape(
                    h // 2, w
                )

                bgra = np.zeros((h, w, 4), np.uint8)
                yi = y.astype(np.int16)
                ui = np.repeat(np.repeat(uv[:, 0::2].astype(np.int16) - 128, 2, axis=1), 2, axis=0)[
                    :h, :w
                ]
                vi = np.repeat(np.repeat(uv[:, 1::2].astype(np.int16) - 128, 2, axis=1), 2, axis=0)[
                    :h, :w
                ]
                bgra[:, :, 0] = np.clip(yi + 1.772 * ui, 0, 255).astype(np.uint8)
                bgra[:, :, 1] = np.clip(yi - 0.344 * ui - 0.714 * vi, 0, 255).astype(np.uint8)
                bgra[:, :, 2] = np.clip(yi + 1.402 * vi, 0, 255).astype(np.uint8)
                bgra[:, :, 3] = 255
            elif frame.format == "BGRA":
                bgra = np.frombuffer(frame.data, np.uint8).reshape(h, w, 4).copy()
            else:
                return cached

            stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
            if stride == w * 4:
                surface = cairo.ImageSurface.create_for_data(
                    bgra, cairo.FORMAT_ARGB32, w, h, stride
                )
            else:
                padded = np.zeros((h, stride), np.uint8)
                padded[:, : w * 4] = bgra.reshape(h, w * 4)
                surface = cairo.ImageSurface.create_for_data(
                    padded, cairo.FORMAT_ARGB32, w, h, stride
                )

            self._surfaces[role] = surface
            self._surface_ids[role] = id(frame.data)
            return surface
        except Exception:
            log.debug("packed_cameras: conversion failed for %s", role, exc_info=True)
            return cached

    def _draw_rotated_frame(
        self,
        cr: cairo.Context,
        surface: cairo.ImageSurface,
        slot: PackedSlot,
    ) -> None:
        """Draw a camera frame at the slot position, rotated to match edge."""
        cr.save()

        sw = surface.get_width()
        sh = surface.get_height()

        # Scale to fit the slot dimensions (maintain aspect)
        sx = slot.w / sw
        sy = slot.h / sh
        s = min(sx, sy)
        frame_w = sw * s
        frame_h = sh * s

        # Move to slot center, rotate to match edge angle
        cr.translate(slot.cx, slot.cy)
        cr.rotate(slot.rotation)

        # Thin border glow
        cr.rectangle(-frame_w / 2 - 1, -frame_h / 2 - 1, frame_w + 2, frame_h + 2)
        cr.set_source_rgba(0.0, 0.9, 1.0, 0.15)
        cr.fill()

        # Clip and draw
        cr.rectangle(-frame_w / 2, -frame_h / 2, frame_w, frame_h)
        cr.clip()
        cr.translate(-frame_w / 2, -frame_h / 2)
        cr.scale(s, s)
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(0.9)

        cr.restore()
