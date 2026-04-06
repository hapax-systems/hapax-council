"""ir_album.py — Detect and extract vinyl album cover from IR overhead frame.

Uses adaptive thresholding + contour detection to find the largest
quadrilateral in the frame (the album sleeve). Returns a perspective-
corrected square crop of just the cover.

Works under 850nm IR illumination where the white/light album cover
contrasts strongly with the dark desk surface.
"""

from __future__ import annotations

import cv2
import numpy as np


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
