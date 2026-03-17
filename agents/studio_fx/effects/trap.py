"""Trap effect — dark, atmospheric, cinematic.

DISTINCT 1: Crushed blacks with teal-in-shadows / orange-in-highlights split-tone
DISTINCT 2: Simulated atmospheric haze / particulate

DOMINANT 1: Cinematic weight
DOMINANT 2: Subject isolation via vignette

Perception:
  - haze_density ← audio_energy
  - vignette opens on beats
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class TrapEffect(BaseEffect):
    name = "trap"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        pass

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        energy = min(1.0, p.audio_energy * 10)
        f = frame.astype(np.float32)

        # === 1. SPLIT-TONE: teal shadows / warm highlights ===
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        shadow_mask = np.clip(1.0 - gray * 1.8, 0, 1)
        highlight_mask = np.clip(gray * 1.8 - 0.8, 0, 1)

        # Teal into shadows
        f[:, :, 0] += shadow_mask * 50  # B
        f[:, :, 1] += shadow_mask * 25  # G
        f[:, :, 2] -= shadow_mask * 15  # R

        # Warm into highlights
        f[:, :, 2] += highlight_mask * 30  # R
        f[:, :, 1] += highlight_mask * 6  # G

        # === 2. DESATURATE (moderate, not total) ===
        out = np.clip(f, 0, 255).astype(np.uint8)
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = (hsv[:, :, 1].astype(np.float32) * 0.35).astype(np.uint8)
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        # === 3. DARKEN (gentle) ===
        out = (out.astype(np.float32) * 0.60).astype(np.uint8)

        # === 4. ATMOSPHERIC HAZE ===
        haze_amount = 0.12 + energy * 0.15
        haze = cv2.GaussianBlur(out, (25 | 1, 25 | 1), 12)
        haze_light = np.clip(haze.astype(np.float32) * 1.3 + 20, 0, 255).astype(np.uint8)
        out = cv2.addWeighted(out, 1.0 - haze_amount, haze_light, haze_amount, 0)

        # === 5. VIGNETTE ===
        vstr = 0.55 - energy * 0.15
        x = np.linspace(-1, 1, w, dtype=np.float32)
        y = np.linspace(-1, 1, h, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        dist = np.sqrt(xx**2 + yy**2)
        vig = np.clip(1.0 - dist * vstr, 0.15, 1.0)  # floor at 0.15 — never total black
        out_f = out.astype(np.float32) * vig[:, :, np.newaxis]

        return np.clip(out_f, 0, 255).astype(np.uint8)
