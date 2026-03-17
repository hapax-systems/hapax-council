"""Diff effect — frame difference, monochrome, high contrast.

Pure algorithmic — no perception modulation needed.
Computes cv2.absdiff between current and previous frame, converts to
monochrome, and applies contrast stretch.
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class DiffEffect(BaseEffect):
    name = "diff"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._prev: np.ndarray | None = None

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        if self._prev is not None:
            self._prev = cv2.resize(self._prev, (width, height), interpolation=cv2.INTER_AREA)

    def reset(self) -> None:
        self._prev = None

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self._prev is None:
            self._prev = gray
            return np.zeros_like(frame)

        # Absolute difference
        diff = cv2.absdiff(gray, self._prev)
        self._prev = gray.copy()

        # High-contrast stretch
        diff = cv2.convertScaleAbs(diff, alpha=3.0, beta=10)

        # Back to BGR (monochrome)
        return cv2.cvtColor(diff, cv2.COLOR_GRAY2BGR)
