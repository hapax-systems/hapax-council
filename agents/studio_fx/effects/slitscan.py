"""Slit-scan effect — each column comes from a different moment in time.

DISTINCT 1: Spatial position encodes time — left=past, right=present
DISTINCT 2: Moving objects become stretched/warped by their velocity

DOMINANT 1: Psychedelic / otherworldly (2001 stargate)
DOMINANT 2: Every frame is unique — depends on motion history

Technique: Deep ring buffer (90+ frames = 6s). Each output column pulls
from a different buffer index. A moving scan line sweeps across the image
to make the temporal gradient visible even on static scenes.

Perception:
  - time_depth ← flow_score (more flow = deeper buffer)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class SlitscanEffect(BaseEffect):
    name = "slitscan"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._buffer: list[np.ndarray] = []
        self._max_buf = 90
        self._tick = 0

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        self._buffer = [cv2.resize(f, (width, height)) for f in self._buffer]

    def reset(self) -> None:
        self._buffer.clear()
        self._tick = 0

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        self._tick += 1

        depth = int(40 + p.flow_score * 50)
        depth = max(20, min(self._max_buf, depth))

        self._buffer.append(frame.copy())
        while len(self._buffer) > depth:
            self._buffer.pop(0)

        n = len(self._buffer)
        if n < 5:
            return frame

        # Build column-to-buffer-index mapping (vectorized)
        col_indices = np.linspace(0, n - 1, w).astype(int)
        col_indices = np.clip(col_indices, 0, n - 1)

        # Stack buffer into array for fast indexing
        # At preview res (480p) this is ~480*854*3*N bytes — manageable
        buf_arr = np.array(self._buffer)  # shape (N, H, W, 3)

        # Build output: each column from its mapped buffer frame
        out = np.empty_like(frame)
        for col in range(w):
            out[:, col] = buf_arr[col_indices[col], :, col]

        # Add a sweeping scan line to make the temporal gradient visible
        scan_x = int((self._tick * 3) % w)
        scan_width = max(2, w // 100)
        x0 = max(0, scan_x - scan_width)
        x1 = min(w, scan_x + scan_width)
        # Bright scan line from the current (newest) frame
        out[:, x0:x1] = frame[:, x0:x1]
        # Add a bright border to the scan line
        if x0 > 0:
            out[:, x0 - 1 : x0] = np.clip(out[:, x0 - 1 : x0].astype(np.int16) + 60, 0, 255).astype(
                np.uint8
            )
        if x1 < w:
            out[:, x1 : x1 + 1] = np.clip(out[:, x1 : x1 + 1].astype(np.int16) + 60, 0, 255).astype(
                np.uint8
            )

        # Slight desaturation for the ethereal/otherworldly quality
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = (hsv[:, :, 1].astype(np.float32) * 0.7).astype(np.uint8)
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        return out
