"""Thermal effect — false-color thermal camera simulation.

DISTINCT 1: Luminance-to-color remapping via thermal palette (black→blue→red→yellow→white)
DISTINCT 2: Body heat emphasis — skin/warm objects map to hot colors

Technique: Convert to grayscale, apply OpenCV colormap (INFERNO or JET).

Perception:
  - palette ← activity_mode (production=INFERNO, coding=VIRIDIS)
  - contrast ← ambient_brightness (darker room = boost contrast)
"""

from __future__ import annotations

import cv2
import numpy as np  # noqa: TC002

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot

_PALETTE_MAP = {
    "production": cv2.COLORMAP_INFERNO,
    "coding": cv2.COLORMAP_VIRIDIS,
    "idle": cv2.COLORMAP_JET,
}


class ThermalEffect(BaseEffect):
    name = "thermal"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        pass

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Boost contrast to differentiate thermal zones
        clip = 2.5 + (1.0 - p.ambient_brightness) * 2.0
        self._clahe.setClipLimit(clip)
        gray = self._clahe.apply(gray)

        # Invert so bright (warm) areas map to hot colors
        gray = cv2.bitwise_not(gray)

        # Apply thermal colormap
        cmap = _PALETTE_MAP.get(p.activity_mode, cv2.COLORMAP_INFERNO)
        colored = cv2.applyColorMap(gray, cmap)

        # Slight blur for thermal camera softness
        colored = cv2.GaussianBlur(colored, (3, 3), 0.8)

        return colored
