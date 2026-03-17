"""Glitch blocks effect — JPEG/MPEG macroblocking simulation.

DISTINCT 1: Rectangular block displacement — 8x8/16x16 blocks displaced/duplicated
DISTINCT 2: DCT-like color quantization within blocks (reduced color precision)

Technique: Divide frame into blocks, randomly displace some, quantize colors
in others, duplicate random blocks to other positions.

Perception:
  - block_rate ← audio_energy (louder = more blocks displaced per frame)
  - block_size ← activity_mode (production=larger, coding=smaller)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class GlitchblocksEffect(BaseEffect):
    name = "glitchblocks"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._rng = np.random.default_rng(55)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        self._rng = np.random.default_rng(55)

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        energy = min(1.0, p.audio_energy * 10)
        out = frame.copy()

        # Large blocks for visible glitch — scale with frame size
        bs = max(24, h // 12)  # ~40px at 480p, ~90px at 1080p

        # Many blocks for always-visible corruption
        n_blocks = int(40 + energy * 80)

        for _ in range(n_blocks):
            action = self._rng.integers(0, 3)
            bx = self._rng.integers(0, max(1, w - bs))
            by = self._rng.integers(0, max(1, h - bs))

            if action == 0:
                # Displace: copy block from random source position
                sx = self._rng.integers(0, max(1, w - bs))
                sy = self._rng.integers(0, max(1, h - bs))
                out[by : by + bs, bx : bx + bs] = frame[sy : sy + bs, sx : sx + bs]

            elif action == 1:
                # Color quantize: reduce color depth within block
                block = out[by : by + bs, bx : bx + bs].astype(np.float32)
                levels = self._rng.integers(2, 6)
                step = 256.0 / levels
                block = (np.floor(block / step) * step).astype(np.uint8)
                out[by : by + bs, bx : bx + bs] = block

            elif action == 2:
                # Horizontal shift: shift block contents sideways
                shift = self._rng.integers(-bs, bs + 1)
                out[by : by + bs, bx : bx + bs] = np.roll(
                    out[by : by + bs, bx : bx + bs], shift, axis=1
                )

        # Channel offset on bands of rows (visible corruption)
        n_bands = int(5 + energy * 15)
        for _ in range(n_bands):
            y = self._rng.integers(0, max(1, h - 4))
            band_h = self._rng.integers(1, max(2, min(6, h // 40)))
            y1 = min(h, y + band_h)
            ch = self._rng.integers(0, 3)
            shift = self._rng.integers(-30, 31)
            out[y:y1, :, ch] = np.roll(out[y:y1, :, ch], shift, axis=1)

        # Slight contrast boost to make blocks visible
        out = cv2.convertScaleAbs(out, alpha=1.15, beta=-8)

        return out
