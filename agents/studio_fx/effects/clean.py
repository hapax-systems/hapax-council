"""Clean effect — professional enhanced passthrough.

DISTINCT 1: Invisible processing — looks better than raw but you can't tell why
DISTINCT 2: Adaptive to room conditions (shadow recovery, not color correction)

DOMINANT 1: Professional broadcast quality
DOMINANT 2: Subtle film character — gentle S-curve, minimal grain

The evening warm/orange ambient is INTENTIONAL — clean preserves it.
Only enhances shadow detail and adds subtle cinematic character.
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class CleanEffect(BaseEffect):
    name = "clean"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        pass

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        out = frame.copy()

        # === Gentle CLAHE on luminance only — recover shadow detail ===
        lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = self._clahe.apply(lab[:, :, 0])
        out = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        # === Subtle contrast lift (film-like S-curve) ===
        # Lift blacks slightly, hold midtones, gentle highlight roll
        lut = np.zeros(256, dtype=np.uint8)
        for i in range(256):
            normalized = i / 255.0
            # Mild S-curve
            curved = normalized * (1.0 + 0.08 * (0.5 - abs(normalized - 0.5)))
            # Lift black point by 5 (never pure black)
            lut[i] = min(255, max(0, int(curved * 250 + 5)))
        out = cv2.LUT(out, lut)

        # === Very subtle saturation boost (keep the warmth, make it richer) ===
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(np.float32) * 1.06, 0, 255).astype(
            np.uint8
        )
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        return out
