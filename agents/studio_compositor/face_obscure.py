"""Pixel-level facial obscuring stage (task #129 — HARD privacy requirement).

Applies a solid Gruvbox-dark rectangle plus a large-block pixelation veneer
over detected face bboxes. Runs per-camera at capture time, before the JPEG
hits `/dev/shm`, so all downstream tees (compositor, Reverie, director LLM
snapshots, OBS V4L2 loopback, RTMP, HLS, recordings) inherit the protection.

The obscure technique is **not reversible**. Gaussian blur is excluded because
it is reversible under known-PSF attack; solid mask + block pixelation is not.

Spec: `docs/superpowers/specs/2026-04-18-facial-obscuring-hard-req-design.md`
§3.3 (obscuring technique) and §6 (file-level plan).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2

if TYPE_CHECKING:
    import numpy as np
else:
    import numpy as np  # noqa: TC002 — needed at runtime for cv2 ops

log = logging.getLogger(__name__)


# Gruvbox-hard-dark background color `#282828` (40, 40, 40) in BGR and RGB.
# Spec §3.3 names this the package-sourced color from `HomagePackage`. We keep
# a literal constant here so the obscure stage has no soft dependency on the
# homage package loading correctly — privacy must not depend on cosmetics.
GRUVBOX_DARK_BGR: tuple[int, int, int] = (40, 40, 40)
GRUVBOX_DARK_RGB: tuple[int, int, int] = (40, 40, 40)

# 20% bbox expansion per side to absorb SCRFD/YOLO jitter between detections.
DEFAULT_MARGIN: float = 0.20

# 16-pixel square blocks for the pixelation veneer over the solid rect.
DEFAULT_BLOCK_SIZE: int = 16


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in pixel coordinates.

    Accepts floats (SCRFD returns float bboxes); the obscurer rounds and
    clamps internally. `x1, y1` is the top-left corner; `x2, y2` the
    bottom-right (exclusive).
    """

    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_xyxy(cls, coords: tuple[float, float, float, float]) -> BBox:
        return cls(coords[0], coords[1], coords[2], coords[3])


def _expand_bbox(
    bbox: BBox,
    frame_w: int,
    frame_h: int,
    margin: float,
) -> tuple[int, int, int, int]:
    """Expand a bbox by `margin` fraction on each side, clamped to the frame.

    Returns integer (x1, y1, x2, y2) suitable for numpy slicing.
    """
    w = bbox.x2 - bbox.x1
    h = bbox.y2 - bbox.y1
    dx = w * margin
    dy = h * margin
    x1 = int(round(bbox.x1 - dx))
    y1 = int(round(bbox.y1 - dy))
    x2 = int(round(bbox.x2 + dx))
    y2 = int(round(bbox.y2 + dy))
    # Clamp to frame bounds (x2/y2 are exclusive, so capped at frame_w/frame_h).
    x1 = max(0, min(x1, frame_w))
    y1 = max(0, min(y1, frame_h))
    x2 = max(0, min(x2, frame_w))
    y2 = max(0, min(y2, frame_h))
    return x1, y1, x2, y2


def _pixelate_region(
    region: np.ndarray,
    block_size: int,
) -> np.ndarray:
    """Apply block-mean pixelation by downscale + nearest-neighbor upscale.

    For very small regions (smaller than one block), returns the region
    unchanged — the solid rect underneath still holds.
    """
    h, w = region.shape[:2]
    if h < 1 or w < 1:
        return region
    # Target mosaic dimensions: at least 1 px.
    tw = max(1, w // block_size)
    th = max(1, h // block_size)
    small = cv2.resize(region, (tw, th), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


class FaceObscurer:
    """Applies the privacy obscure mask to detected face regions.

    The obscure is deliberately simple and irreversible:

    1. Expand each bbox by `margin` (default 20%) to absorb detection jitter.
    2. Paint a solid Gruvbox-dark rect over the expanded region.
    3. Pixelate the rect with block-mean downscale (default 16 px blocks).
       The pixelation acts as a low-amplitude veneer on top of the solid fill
       so the mask reads as a deliberate artifact rather than a crash bar.

    The returned frame is a new array; the input frame is not mutated. Callers
    get byte-identical pass-through when `bboxes` is empty — see §11 of the
    spec (rollback plan requires pass-through to be a no-op).
    """

    def __init__(
        self,
        margin: float = DEFAULT_MARGIN,
        block_size: int = DEFAULT_BLOCK_SIZE,
        color_bgr: tuple[int, int, int] = GRUVBOX_DARK_BGR,
    ) -> None:
        if margin < 0:
            raise ValueError(f"margin must be >= 0, got {margin}")
        if block_size < 1:
            raise ValueError(f"block_size must be >= 1, got {block_size}")
        self._margin = margin
        self._block_size = block_size
        self._color_bgr = color_bgr

    @property
    def margin(self) -> float:
        return self._margin

    @property
    def block_size(self) -> int:
        return self._block_size

    @property
    def color_bgr(self) -> tuple[int, int, int]:
        return self._color_bgr

    def obscure(
        self,
        frame: np.ndarray,
        bboxes: list[BBox] | list[tuple[float, float, float, float]],
    ) -> np.ndarray:
        """Obscure every bbox in `bboxes` on a copy of `frame`.

        Args:
            frame: HxWxC uint8 image in BGR order (the compositor pipeline's
                native layout). Must be contiguous.
            bboxes: List of `BBox` instances or `(x1, y1, x2, y2)` tuples.
                Empty list → frame returned unchanged (pass-through).

        Returns:
            A new ndarray with each bbox region obscured. The input frame is
            not mutated.
        """
        if not bboxes:
            # Pass-through: no allocation, no mutation. Matches the §11
            # rollback contract — flag-off frames are byte-identical to
            # pre-feature behavior.
            return frame

        if frame.ndim != 3 or frame.shape[2] not in (3, 4):
            raise ValueError(f"frame must be HxWx3 or HxWx4, got shape {frame.shape}")

        out = frame.copy()
        frame_h, frame_w = out.shape[:2]

        for raw in bboxes:
            bbox = raw if isinstance(raw, BBox) else BBox.from_xyxy(raw)
            x1, y1, x2, y2 = _expand_bbox(bbox, frame_w, frame_h, self._margin)
            if x2 <= x1 or y2 <= y1:
                # Degenerate bbox (off-frame or zero-area) — nothing to paint.
                continue

            # Step 1: solid Gruvbox-dark fill (the privacy floor).
            # Handles 3- and 4-channel frames: slice color to match channels.
            num_channels = out.shape[2]
            fill_color = self._color_bgr[:num_channels]
            out[y1:y2, x1:x2] = fill_color

            # Step 2: pixelate the solid region. On a solid fill this is a
            # no-op visually, but when the caller later composites the mask
            # over the original (e.g. translucent overlay modes) the block
            # structure reads as a deliberate artifact. Kept here to keep the
            # obscure self-contained.
            region = out[y1:y2, x1:x2]
            out[y1:y2, x1:x2] = _pixelate_region(region, self._block_size)

        return out
