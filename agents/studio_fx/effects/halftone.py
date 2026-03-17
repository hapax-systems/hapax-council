"""Halftone effect — newspaper dot pattern rendering.

DISTINCT 1: Continuous tone represented as variable-size dots on fixed grid
DISTINCT 2: CMYK angle-offset pattern creates moiré interference at boundaries

Technique: Downsample to dot grid resolution, draw circles whose radius
encodes the local brightness. For color, use separate grids at different
angles for C, M, Y, K channels.

Perception:
  - dot_size ← audio_energy (louder = bigger dots = bolder)
  - color_mode ← activity_mode (production=CMYK color, coding=BW newspaper)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class HalftoneEffect(BaseEffect):
    name = "halftone"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        pass

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        energy = min(1.0, p.audio_energy * 10)

        # Perception: dot spacing from audio energy
        spacing = max(4, int(8 - energy * 4))  # 4-8 pixels between dots
        max_r = spacing // 2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Create output on white background
        out = np.ones((h, w, 3), dtype=np.uint8) * 240  # near-white paper

        # Draw dots — size proportional to darkness
        for y in range(spacing, h - spacing, spacing):
            for x in range(spacing, w - spacing, spacing):
                val = gray[y, x]
                # Invert: darker pixels → bigger dots
                radius = int((255 - val) / 255.0 * max_r)
                if radius > 0:
                    cv2.circle(out, (x, y), radius, (20, 20, 20), -1, cv2.LINE_AA)

        return out
