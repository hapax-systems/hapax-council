"""ir_album.py — Detect and extract vinyl album cover from IR overhead frame.

Uses adaptive thresholding + contour detection to find the largest
quadrilateral in the frame (the album sleeve). Returns a perspective-
corrected square crop of just the cover.

Works under 850nm IR illumination where the white/light album cover
contrasts strongly with the dark desk surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class PlatterObject:
    """Geometry for one bounded object on the fixed CBIP/platter surface."""

    bbox: list[int]
    center: list[int]
    rotation: float
    corners: list[list[int]]
    area_pct: float
    stable_id: str
    confidence: float
    size: list[int]
    aspect_ratio: float
    position_index: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for council POST/report callers."""
        return asdict(self)


def detect_album_cover(
    grey_frame: np.ndarray,
    min_area_pct: float = 0.05,
    max_area_pct: float = 0.85,
) -> dict | None:
    """Detect a vinyl album cover in an overhead IR frame.

    Returns dict with:
        bbox: [x1, y1, x2, y2] bounding box
        center: [cx, cy] center point
        rotation: float degrees
        corners: [[x,y], ...] 4 corner points of the detected quad
        area_pct: float fraction of frame area
    Returns None if no album detected.
    """
    h, w = grey_frame.shape[:2]
    frame_area = h * w

    # Blur + edge detection
    blurred = cv2.GaussianBlur(grey_frame, (5, 5), 0)

    # Canny edge detection
    median = int(np.median(blurred))
    lo = max(0, int(median * 0.5))
    hi = min(255, int(median * 1.2))
    edges = cv2.Canny(blurred, lo, hi)

    # Dilate to close gaps in edges
    kernel = np.ones((5, 5), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=2)
    edges = cv2.erode(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_score = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area_pct * frame_area:
            continue
        if area > max_area_pct * frame_area:
            continue

        # Get rotated bounding rect
        rect = cv2.minAreaRect(cnt)
        rect_w, rect_h = rect[1]
        if rect_w == 0 or rect_h == 0:
            continue

        # Album covers are square — aspect ratio should be close to 1.0
        aspect = min(rect_w, rect_h) / max(rect_w, rect_h)

        # Score: prefer large, square contours
        score = area * aspect

        if score > best_score:
            best = rect
            best_score = score
            best_cnt = cnt

    if best is None:
        return None

    center, (rect_w, rect_h), angle = best
    box_pts = cv2.boxPoints(best)

    x, y, bw, bh = cv2.boundingRect(best_cnt)
    area_pct = (rect_w * rect_h) / frame_area

    return {
        "bbox": [x, y, x + bw, y + bh],
        "center": [int(center[0]), int(center[1])],
        "rotation": float(angle),
        "size": [int(max(rect_w, rect_h)), int(min(rect_w, rect_h))],
        "corners": box_pts.astype(int).tolist(),
        "area_pct": round(area_pct, 3),
    }


def detect_platter_objects(
    grey_frame: np.ndarray,
    min_area_pct: float = 0.002,
    max_area_pct: float = 0.85,
    *,
    min_aspect_ratio: float = 0.45,
    max_objects: int = 24,
    slot_rows: int = 2,
    slot_cols: int = 3,
) -> list[PlatterObject]:
    """Detect one or more bounded objects on the CBIP/platter surface.

    IDs are based on fixed row/column slots, not detection rank. That keeps
    existing cards' ``stable_id`` values steady when another slot is empty.
    """
    if slot_rows <= 0 or slot_cols <= 0:
        raise ValueError("slot_rows and slot_cols must be positive")

    h, w = grey_frame.shape[:2]
    frame_area = h * w
    if frame_area <= 0:
        return []

    contours = _find_bounded_object_contours(grey_frame)
    candidates: list[tuple[int, int, PlatterObject]] = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        area_pct = area / frame_area
        if area_pct < min_area_pct or area_pct > max_area_pct:
            continue

        rect = cv2.minAreaRect(cnt)
        center, (rect_w, rect_h), angle = rect
        if rect_w <= 0 or rect_h <= 0:
            continue

        aspect_ratio = min(rect_w, rect_h) / max(rect_w, rect_h)
        if aspect_ratio < min_aspect_ratio:
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        row, col = _slot_for_center(center[0], center[1], w, h, slot_rows, slot_cols)
        corners = cv2.boxPoints(rect).astype(int).tolist()
        confidence = _object_confidence(area_pct, aspect_ratio, area, rect_w * rect_h)

        candidates.append(
            (
                row,
                col,
                PlatterObject(
                    bbox=[int(x), int(y), int(x + bw), int(y + bh)],
                    center=[int(round(center[0])), int(round(center[1]))],
                    rotation=float(angle),
                    corners=corners,
                    area_pct=round(float(area_pct), 4),
                    stable_id=f"row{row}-col{col}",
                    confidence=confidence,
                    size=[int(round(max(rect_w, rect_h))), int(round(min(rect_w, rect_h)))],
                    aspect_ratio=round(float(aspect_ratio), 4),
                    position_index=0,
                ),
            )
        )

    candidates.sort(key=lambda item: (item[0], item[1], item[2].center[1], item[2].center[0]))
    bounded = candidates[: max(0, max_objects)]
    seen: dict[str, int] = {}
    objects: list[PlatterObject] = []
    for index, (_, _, obj) in enumerate(bounded, start=1):
        seen[obj.stable_id] = seen.get(obj.stable_id, 0) + 1
        stable_id = obj.stable_id
        if seen[obj.stable_id] > 1:
            stable_id = f"{obj.stable_id}-{seen[obj.stable_id]}"
        objects.append(
            PlatterObject(
                bbox=obj.bbox,
                center=obj.center,
                rotation=obj.rotation,
                corners=obj.corners,
                area_pct=obj.area_pct,
                stable_id=stable_id,
                confidence=obj.confidence,
                size=obj.size,
                aspect_ratio=obj.aspect_ratio,
                position_index=index,
            )
        )
    return objects


def platter_objects_payload(objects: list[PlatterObject]) -> list[dict[str, Any]]:
    """Convert detector output into the JSON array expected by report writers."""
    return [obj.to_dict() for obj in objects]


def _find_bounded_object_contours(grey_frame: np.ndarray) -> list[np.ndarray]:
    blurred = cv2.GaussianBlur(grey_frame, (5, 5), 0)
    median = int(np.median(blurred))
    lo = max(0, int(median * 0.45))
    hi = min(255, max(lo + 1, int(median * 1.25)))
    edges = cv2.Canny(blurred, lo, hi)

    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return list(contours)


def _slot_for_center(
    cx: float,
    cy: float,
    frame_w: int,
    frame_h: int,
    slot_rows: int,
    slot_cols: int,
) -> tuple[int, int]:
    col = min(slot_cols, max(1, int((cx / max(frame_w, 1)) * slot_cols) + 1))
    row = min(slot_rows, max(1, int((cy / max(frame_h, 1)) * slot_rows) + 1))
    return row, col


def _object_confidence(
    area_pct: float,
    aspect_ratio: float,
    contour_area: float,
    rect_area: float,
) -> float:
    extent = contour_area / rect_area if rect_area > 0 else 0.0
    aspect_score = max(0.0, min(1.0, aspect_ratio / 0.6))
    area_score = max(0.0, min(1.0, area_pct / 0.02))
    extent_score = max(0.0, min(1.0, extent))
    return round(0.2 + (0.35 * aspect_score) + (0.25 * area_score) + (0.2 * extent_score), 3)


def extract_album_crop(
    frame: np.ndarray,
    detection: dict,
    output_size: int = 640,
) -> np.ndarray | None:
    """Perspective-transform the detected album cover to a square image.

    Args:
        frame: Full resolution frame (color or greyscale)
        detection: Result from detect_album_cover()
        output_size: Output square dimension in pixels

    Returns:
        Square numpy array of the straightened album cover, or None
    """
    corners = np.array(detection["corners"], dtype=np.float32)

    # Sort corners: top-left, top-right, bottom-right, bottom-left
    s = corners.sum(axis=1)
    d = np.diff(corners, axis=1).flatten()
    tl = corners[np.argmin(s)]
    br = corners[np.argmax(s)]
    tr = corners[np.argmin(d)]
    bl = corners[np.argmax(d)]

    src = np.array([tl, tr, br, bl], dtype=np.float32)
    dst = np.array(
        [[0, 0], [output_size, 0], [output_size, output_size], [0, output_size]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(frame, M, (output_size, output_size))
    return warped
