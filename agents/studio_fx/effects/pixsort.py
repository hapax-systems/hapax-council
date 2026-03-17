"""Pixel sort effect — brightness-threshold row sorting with visible streaking.

DISTINCT 1: Directional streaking from sorted pixel intervals (dripping/smeared look)
DISTINCT 2: Threshold boundary between photographic (unsorted) and abstract (sorted)

DOMINANT 1: Algorithmic aesthetic — unmistakably computational
DOMINANT 2: High visual contrast between sorted and unsorted regions

Technique: Boost contrast first to ensure visible brightness variation,
then sort pixel rows by brightness within threshold bands. Wider band =
more pixels sorted = more abstract.

Perception:
  - sort_intensity ← audio_energy (louder = more rows sorted)
  - sort_direction ← gaze_direction
  - threshold_width ← flow_score (more flow = wider band = more destruction)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


def _sort_row(row: np.ndarray, brightness: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Sort pixels within contiguous threshold bands by brightness."""
    out = row.copy()
    mask = (brightness >= lo) & (brightness <= hi)
    n = len(brightness)

    changes = np.diff(mask.astype(np.int8))
    starts = np.where(changes == 1)[0] + 1
    ends = np.where(changes == -1)[0] + 1

    if mask[0]:
        starts = np.concatenate(([0], starts))
    if mask[-1]:
        ends = np.concatenate((ends, [n]))

    for s, e in zip(starts, ends, strict=False):
        if e - s > 3:
            seg_bright = brightness[s:e]
            indices = np.argsort(seg_bright)
            out[s:e] = row[s:e][indices]

    return out


class PixsortEffect(BaseEffect):
    name = "pixsort"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._rng = np.random.default_rng(99)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        self._rng = np.random.default_rng(99)

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        energy = min(1.0, p.audio_energy * 10)

        # === Boost contrast BEFORE sorting so thresholds work on dark frames ===
        f = frame.astype(np.float32)
        mean = f.mean()
        f = (f - mean) * 1.8 + mean  # strong contrast boost
        boosted = np.clip(f, 0, 255).astype(np.uint8)

        out = boosted.copy()
        gray = cv2.cvtColor(boosted, cv2.COLOR_BGR2GRAY)

        # Perception: how many rows to sort — AGGRESSIVE baseline
        # Sort 60-100% of rows depending on energy
        frac = 0.6 + energy * 0.4
        num_sort = int(h * frac)

        # Perception: threshold band — wide enough to catch most pixels
        band_lo = max(5, int(20 - p.flow_score * 15))
        band_hi = min(250, int(220 + p.flow_score * 30))

        # Perception: direction from gaze
        vertical = p.gaze_direction in ("up", "down", "away")

        if vertical:
            out_t = out.transpose(1, 0, 2).copy()
            gray_t = gray.T.copy()
            cols = self._rng.choice(w, size=min(num_sort, w), replace=False)
            for c in cols:
                out_t[c] = _sort_row(out_t[c], gray_t[c], band_lo, band_hi)
            out = out_t.transpose(1, 0, 2)
        else:
            rows = self._rng.choice(h, size=min(num_sort, h), replace=False)
            for r in rows:
                out[r] = _sort_row(out[r], gray[r], band_lo, band_hi)

        # Slight desaturation for that glitch-art gallery look
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = (hsv[:, :, 1].astype(np.float32) * 0.7).astype(np.uint8)
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        return out
