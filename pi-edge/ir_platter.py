"""NIR interpretative-platter object detection for the Pi overhead frame.

The detector finds bright bounded objects on the fixed overhead surface and
returns deterministic, position-ordered object records. It intentionally does
not infer content identity; downstream consumers bind meaning from receipts
and context, not from this contour pass.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import cv2
import numpy as np


class PlatterObject(dict):
    """Dict-compatible platter object with attribute access for legacy callers."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def to_dict(self) -> dict[str, Any]:
        """Return a plain JSON-serializable dictionary."""
        return dict(self)


def detect_platter_objects(
    grey_frame: np.ndarray,
    min_area_pct: float = 0.003,
    max_area_pct: float = 0.85,
    *,
    max_objects: int = 24,
    min_aspect: float | None = None,
    min_aspect_ratio: float | None = None,
    slot_rows: int = 2,
    slot_cols: int = 3,
) -> list[PlatterObject]:
    """Detect bounded platter objects in an overhead IR frame.

    Returns a position-ordered list of object dictionaries. Each dictionary
    carries a stable per-position ``object_id`` for the current frame, bounding
    geometry, corner points, and contour-quality fields. Returns an empty list
    when no object passes the contour gates.
    """
    grey = _as_greyscale(grey_frame)
    h, w = grey.shape[:2]
    if h <= 0 or w <= 0:
        return []
    if slot_rows <= 0 or slot_cols <= 0:
        raise ValueError("slot_rows and slot_cols must be positive")
    frame_area = float(h * w)
    aspect_floor = (
        min_aspect
        if min_aspect is not None
        else min_aspect_ratio
        if min_aspect_ratio is not None
        else 0.15
    )

    blurred = cv2.GaussianBlur(grey, (5, 5), 0)
    median = int(np.median(blurred))
    lo = max(0, int(median * 0.45))
    hi = min(255, max(lo + 1, int(median * 1.25)))
    edges = cv2.Canny(blurred, lo, hi)

    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detections: list[dict] = []
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        area_pct = area / frame_area
        if area_pct < min_area_pct or area_pct > max_area_pct:
            continue

        rect = cv2.minAreaRect(cnt)
        rect_w, rect_h = rect[1]
        if rect_w <= 0 or rect_h <= 0:
            continue
        aspect_ratio = min(rect_w, rect_h) / max(rect_w, rect_h)
        if aspect_ratio < aspect_floor:
            continue

        rect_area = float(rect_w * rect_h)
        extent = area / rect_area if rect_area > 0 else 0.0
        if extent < 0.35:
            continue

        center, _, angle = rect
        x, y, bw, bh = cv2.boundingRect(cnt)
        corners = cv2.boxPoints(rect).astype(int).tolist()
        row, col = _slot_for_center(center[0], center[1], w, h, slot_rows, slot_cols)
        confidence = _object_confidence(area_pct, aspect_ratio, area, rect_area)

        detections.append(
            {
                "bbox": [int(x), int(y), int(x + bw), int(y + bh)],
                "center": [int(round(center[0])), int(round(center[1]))],
                "rotation": float(angle),
                "size": [int(round(max(rect_w, rect_h))), int(round(min(rect_w, rect_h)))],
                "corners": corners,
                "area_pct": round(area_pct, 4),
                "contour_area": round(area, 2),
                "aspect_ratio": round(float(aspect_ratio), 4),
                "extent": round(float(extent), 4),
                "sort_key": [round(float(center[1]) / h, 4), round(float(center[0]) / w, 4)],
                "stable_id": f"row{row}-col{col}",
                "confidence": confidence,
            }
        )

    detections.sort(key=lambda d: (d["sort_key"][0], d["sort_key"][1], -d["area_pct"]))
    bounded = detections[: max(0, max_objects)]
    seen_stable_ids: dict[str, int] = {}
    objects: list[PlatterObject] = []
    for index, detection in enumerate(bounded, start=1):
        stable_id = str(detection["stable_id"])
        seen_stable_ids[stable_id] = seen_stable_ids.get(stable_id, 0) + 1
        if seen_stable_ids[stable_id] > 1:
            detection["stable_id"] = f"{stable_id}-{seen_stable_ids[stable_id]}"
        detection["object_id"] = f"platter-{index:02d}"
        detection["position_index"] = index
        objects.append(PlatterObject(detection))
    return objects


def detect_album_cover(
    grey_frame: np.ndarray,
    min_area_pct: float = 0.05,
    max_area_pct: float = 0.85,
) -> dict | None:
    """Return the largest detected platter object for legacy callers."""
    objects = detect_platter_objects(
        grey_frame,
        min_area_pct=min_area_pct,
        max_area_pct=max_area_pct,
        max_objects=24,
        min_aspect=0.15,
    )
    if not objects:
        return None
    return max(objects, key=lambda d: d["area_pct"])


def extract_platter_crop(
    frame: np.ndarray,
    detection: dict,
    output_size: int | tuple[int, int] = 640,
) -> np.ndarray | None:
    """Perspective-transform a detected platter object to a rectangular crop."""
    try:
        corners = np.array(detection["corners"], dtype=np.float32)
    except (KeyError, TypeError, ValueError):
        return None
    if corners.shape != (4, 2):
        return None

    out_w, out_h = _coerce_output_size(output_size)
    if out_w <= 0 or out_h <= 0:
        return None

    src = _ordered_corners(corners)
    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, matrix, (out_w, out_h))


def extract_album_crop(
    frame: np.ndarray,
    detection: dict,
    output_size: int = 640,
) -> np.ndarray | None:
    """Square-crop wrapper for legacy callers."""
    return extract_platter_crop(frame, detection, output_size=output_size)


def platter_objects_payload(objects: list[PlatterObject]) -> list[dict[str, Any]]:
    """Convert detector output into the JSON array expected by report writers."""
    return [obj.to_dict() for obj in objects]


def _as_greyscale(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    raise ValueError("frame must be greyscale or BGR")


def _ordered_corners(corners: np.ndarray) -> np.ndarray:
    """Return corners in top-left, top-right, bottom-right, bottom-left order."""
    s = corners.sum(axis=1)
    d = np.diff(corners, axis=1).flatten()
    tl = corners[np.argmin(s)]
    br = corners[np.argmax(s)]
    tr = corners[np.argmin(d)]
    bl = corners[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _coerce_output_size(output_size: int | tuple[int, int] | Iterable[int]) -> tuple[int, int]:
    if isinstance(output_size, int):
        return output_size, output_size
    width, height = tuple(output_size)
    return int(width), int(height)


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


__all__ = [
    "PlatterObject",
    "detect_album_cover",
    "detect_platter_objects",
    "extract_album_crop",
    "extract_platter_crop",
    "platter_objects_payload",
]
