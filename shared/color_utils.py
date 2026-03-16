"""shared/color_utils.py — Color normalization utilities.

Extracted from face_detector.py for shared use by face detection
and HSEmotion facial expression analysis.
"""

from __future__ import annotations

import numpy as np


def normalize_color(image: np.ndarray) -> np.ndarray:
    """Gray world color normalization for tinted lighting (e.g. red studio LEDs).

    Adjusts per-channel means to match the overall mean, compensating for
    colored ambient lighting that would otherwise confuse face detection
    and emotion recognition models.
    """
    avg = image.mean(axis=(0, 1))
    overall = avg.mean()
    if overall < 1.0:
        return image
    scale = overall / np.clip(avg, 1.0, None)
    return np.clip(image * scale, 0, 255).astype(np.uint8)
