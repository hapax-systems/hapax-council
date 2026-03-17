"""Datamosh effect — optical flow pixel displacement with I-frame starvation.

DISTINCT 1: Motion-vector displacement — pixels physically migrate according to flow
DISTINCT 2: Referential instability — the image "forgets" what it should look like

DOMINANT 1: Organic, liquid quality — flow-driven displacement feels biological
DOMINANT 2: Unpredictability — slight motion changes produce wildly different results

Technique: Hold a reference frame, compute dense optical flow between consecutive
frames, accumulate the flow field aggressively, remap the reference through the
accumulated flow. Per-channel flow offset creates chromatic smearing. Periodic
reference reset creates glitch boundaries.

Perception:
  - displacement_strength ← audio_energy (heavy bass = heavy displacement)
  - flow_persistence ← flow_score (high flow = let mosh evolve longer before reset)
  - When silent + idle, mosh decays (calm = less chaos)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class DatamoshEffect(BaseEffect):
    name = "datamosh"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._ref_frame: np.ndarray | None = None
        self._prev_gray: np.ndarray | None = None
        self._accum_flow: np.ndarray | None = None
        self._frame_count = 0
        self._last_reset = 0

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        self.reset()

    def reset(self) -> None:
        self._ref_frame = None
        self._prev_gray = None
        self._accum_flow = None
        self._frame_count = 0
        self._last_reset = 0

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._frame_count += 1

        # --- Perception-driven parameters ---
        energy = min(1.0, p.audio_energy * 10)

        # Reset interval: more energy/flow = longer between resets (wilder mosh)
        # Long base interval so flow accumulates visibly even at idle
        base_interval = 60  # ~4s at 15fps
        reset_interval = int(base_interval * (1.0 + energy * 3.0 + p.flow_score * 2.0))
        reset_interval = max(30, min(180, reset_interval))

        # Flow intensity: higher base so mosh is always visible
        intensity = 1.5 + energy * 2.5

        # --- Initialize or periodic reset ---
        frames_since_reset = self._frame_count - self._last_reset
        needs_reset = self._ref_frame is None or frames_since_reset >= reset_interval

        if needs_reset:
            self._ref_frame = frame.copy()
            self._prev_gray = gray.copy()
            self._accum_flow = np.zeros((h, w, 2), dtype=np.float32)
            self._last_reset = self._frame_count
            return frame

        # --- Compute optical flow (GPU-accelerated if available) ---
        from agents.studio_fx.gpu import GpuAccel

        if not hasattr(self, "_gpu"):
            self._gpu = GpuAccel()
        flow = self._gpu.optical_flow_farneback(self._prev_gray, gray)

        # Accumulate flow aggressively
        if self._accum_flow is None:
            self._accum_flow = np.zeros((h, w, 2), dtype=np.float32)
        self._accum_flow += flow * intensity

        # --- Remap reference through accumulated flow ---
        map_y, map_x = np.mgrid[0:h, 0:w].astype(np.float32)

        # Per-channel flow offset for chromatic smearing (DISTINCT look)
        # Red channel gets slightly more displacement, blue slightly less
        offsets = [0.85, 1.0, 1.15]  # B, G, R multipliers
        channels = []
        assert self._ref_frame is not None  # guaranteed by needs_reset check above
        for c in range(3):
            mx = map_x + self._accum_flow[:, :, 0] * offsets[c]
            my = map_y + self._accum_flow[:, :, 1] * offsets[c]
            ch = cv2.remap(
                self._ref_frame[:, :, c],
                mx,
                my,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            channels.append(ch)
        moshed = np.stack(channels, axis=2)

        # --- Contrast boost to make corruption visible ---
        # Increase contrast to emphasize the displacement artifacts
        moshed_f = moshed.astype(np.float32)
        mean = moshed_f.mean()
        moshed_f = (moshed_f - mean) * 1.4 + mean
        moshed = np.clip(moshed_f, 0, 255).astype(np.uint8)

        # Slight saturation boost for vivid color smearing
        hsv = cv2.cvtColor(moshed, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(np.float32) * 1.3, 0, 255).astype(np.uint8)
        moshed = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        # Blend: heavy mosh with slight current bleed-through for orientation
        out = cv2.addWeighted(moshed, 0.88, frame, 0.12, 0)

        self._prev_gray = gray.copy()
        return out
