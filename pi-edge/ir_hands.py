"""ir_hands.py — NIR adaptive thresholding for hand and screen detection."""

from __future__ import annotations

import cv2
import numpy as np  # noqa: TC002 — Pi-side code, no TYPE_CHECKING guard needed


def detect_hands_nir(
    grey_frame: np.ndarray, min_area: int = 2000, max_area_pct: float = 0.25
) -> list[dict]:
    """Detect hands on instrument surfaces using NIR skin/plastic contrast.

    In NIR, skin has lower reflectance than most plastics. Adaptive
    thresholding segments skin regions, filtered by area and shape.
    """
    blurred = cv2.GaussianBlur(grey_frame, (11, 11), 0)
    thresh = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = grey_frame.shape[:2]
    frame_area = h * w
    hands = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        if area > max_area_pct * frame_area:
            continue

        x, y, cw, ch = cv2.boundingRect(contour)
        aspect = cw / ch if ch > 0 else 0
        if aspect < 0.3 or aspect > 3.0:
            continue

        cx = (x + cw / 2) / w
        cy = (y + ch / 2) / h
        zone = _classify_zone(cx, cy)
        activity = _classify_activity(contour, area)

        hands.append(
            {
                "zone": zone,
                "bbox": [x, y, x + cw, y + ch],
                "activity": activity,
            }
        )

    return hands[:4]


def _classify_zone(cx: float, cy: float) -> str:
    """Classify hand zone from normalized center position."""
    if cx < 0.33:
        return "synth-left"
    elif cx < 0.66:
        return "mpc-pads" if cy < 0.5 else "desk-center"
    else:
        return "turntable"


def _classify_activity(contour: np.ndarray, area: int) -> str:
    """Classify hand activity from contour solidity."""
    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    solidity = area / hull_area if hull_area > 0 else 0

    if solidity > 0.85:
        return "resting"
    elif solidity > 0.7:
        return "sliding"
    else:
        return "tapping"


def detect_screens_nir(grey_frame: np.ndarray, min_area_pct: float = 0.02) -> list[dict]:
    """Detect screens as low-NIR-intensity rectangles.

    LCD/OLED screens emit no NIR, appearing as dark rectangles relative
    to the IR-illuminated scene. Threshold adapts to scene brightness.
    """
    h, w = grey_frame.shape[:2]
    total_area = h * w

    mean_brightness = float(np.mean(grey_frame))
    dark_threshold = max(10, int(mean_brightness * 0.3))

    _, dark_mask = cv2.threshold(grey_frame, dark_threshold, 255, cv2.THRESH_BINARY_INV)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    dark_mask = cv2.morphologyEx(dark_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    screens = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area / total_area < min_area_pct:
            continue

        x, y, cw, ch = cv2.boundingRect(contour)
        rect_area = cw * ch
        if rect_area > 0 and area / rect_area > 0.7:
            screens.append(
                {
                    "bbox": [x, y, x + cw, y + ch],
                    "area_pct": round(area / total_area, 3),
                }
            )

    return screens[:5]
