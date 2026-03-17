"""Ghost effect — temporal persistence via accumulation with exponential decay.

DISTINCT 1: Temporal layering — past frames persist as translucent echoes
DISTINCT 2: Exponential decay envelope — organic fading tail

DOMINANT 1: Motion becomes visible as luminous trails
DOMINANT 2: Dreamlike/ethereal, desaturated atmosphere

Technique: accumulateWeighted with very slow alpha creates a persistent
buffer that holds past frames. Output is a blend where the accumulator
is DOMINANT (60-80%) and current frame is secondary. This ensures past
positions are always visibly ghosting even with minor movement.

Perception:
  - decay_rate ← flow_score
  - trail_opacity ← audio_energy
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class GhostEffect(BaseEffect):
    name = "ghost"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._accum: np.ndarray | None = None
        self._tick = 0

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        if self._accum is not None:
            self._accum = cv2.resize(self._accum, (width, height)).astype(np.float64)

    def reset(self) -> None:
        self._accum = None
        self._tick = 0

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        self._tick += 1

        if self._accum is None or self._accum.shape[:2] != (h, w):
            self._accum = frame.astype(np.float64)
            return frame

        # Perception: decay rate (slow alpha = long trails)
        # flow 0 → alpha 0.08 (moderate trails), flow 1 → alpha 0.02 (very long)
        alpha = 0.08 - p.flow_score * 0.06
        alpha = max(0.02, min(0.12, alpha))

        # Accumulate
        cv2.accumulateWeighted(frame, self._accum, alpha)

        # Spatial drift — slow circular motion so even static scenes show ghosting
        drift_angle = self._tick * 0.04
        dx = round(2.0 * np.cos(drift_angle))
        dy = round(2.0 * np.sin(drift_angle))
        if dx != 0 or dy != 0:
            m = np.float32([[1, 0, dx], [0, 1, dy]])
            self._accum = cv2.warpAffine(self._accum, m, (w, h), borderMode=cv2.BORDER_REFLECT)

        accum_u8 = np.clip(self._accum, 0, 255).astype(np.uint8)

        # Output: accumulator is DOMINANT, current frame is secondary
        # This is the key — the ghost/trail IS the image, current frame just updates it
        trail_weight = 0.70  # accumulator dominates
        current_weight = 0.30
        out_f = (
            accum_u8.astype(np.float32) * trail_weight + frame.astype(np.float32) * current_weight
        )

        # Desaturate for ethereal/spectral quality
        out = np.clip(out_f, 0, 255).astype(np.uint8)
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = (hsv[:, :, 1].astype(np.float32) * 0.45).astype(np.uint8)
        # Cool shift: reduce red channel for spectral blue-grey
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        out[:, :, 2] = (out[:, :, 2].astype(np.float32) * 0.82).astype(np.uint8)

        # Subtle brightness boost to counteract desaturation darkening
        out = cv2.convertScaleAbs(out, alpha=1.1, beta=5)

        return out
