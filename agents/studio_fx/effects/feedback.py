"""Feedback effect — recursive Droste / infinite tunnel.

DISTINCT 1: Frame contains a smaller version of itself (recursive self-similarity)
DISTINCT 2: Emergent fractal patterns from slight rotation + scale per recursion

Technique: Shrink current output, paste it into the center of the accumulator,
apply slight rotation and color shift. The accumulator persists between frames,
creating the infinite tunnel.

Perception:
  - rotation_speed ← audio_energy (louder = spiraling tunnel)
  - zoom_speed ← flow_score (high flow = slower zoom, more stable tunnel)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class FeedbackEffect(BaseEffect):
    name = "feedback"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._accum: np.ndarray | None = None
        self._tick = 0

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        if self._accum is not None:
            self._accum = cv2.resize(self._accum, (width, height))

    def reset(self) -> None:
        self._accum = None
        self._tick = 0

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        self._tick += 1

        if self._accum is None or self._accum.shape[:2] != (h, w):
            self._accum = frame.copy()
            return frame

        # Perception: rotation from audio energy
        rotation_deg = 0.5 + p.audio_energy * 3.0

        # Perception: scale factor — high flow = larger inner (slower zoom)
        scale = 0.82 + p.flow_score * 0.08  # 0.82 to 0.90

        # Rotate and scale the accumulator
        cx, cy = w / 2, h / 2
        angle = self._tick * rotation_deg
        m = cv2.getRotationMatrix2D((cx, cy), angle, scale)
        warped = cv2.warpAffine(self._accum, m, (w, h), borderMode=cv2.BORDER_REFLECT)

        # Slight color shift per recursion (hue rotate)
        hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV).astype(np.int16)
        hsv[:, :, 0] = (hsv[:, :, 0] + 1) % 180  # slow hue drift
        warped = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        # Slight decay to prevent blowout
        warped = (warped.astype(np.float32) * 0.96).astype(np.uint8)

        # Blend: current frame dominates center, tunnel visible around edges
        # Create a center mask — current frame fades outward
        mask = np.zeros((h, w), dtype=np.float32)
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        dist = np.sqrt(((x - cx) / cx) ** 2 + ((y - cy) / cy) ** 2)
        mask = np.clip(1.0 - dist * 1.2, 0.2, 0.9)  # center=0.9, edge=0.2

        # Composite
        m3 = mask[:, :, np.newaxis]
        out = frame.astype(np.float32) * m3 + warped.astype(np.float32) * (1.0 - m3)
        out = np.clip(out, 0, 255).astype(np.uint8)

        self._accum = out.copy()
        return out
