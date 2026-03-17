"""Neon effect — edge detection with colored glow on black background.

DISTINCT 1: Bright edges on dark/black background (inverted normal relationship)
DISTINCT 2: Bloom/glow bleed around edge lines (neon tube halation)

DOMINANT 1: Dramatic scene simplification to pure structure
DOMINANT 2: Strong color potential (edge color mapped to perception)

Technique: Canny edge detection → dilate for line thickness → Gaussian blur
for glow bloom → composite glow + edges over heavily darkened original.
Edge color derived from emotion.

Perception:
  - edge_color ← top_emotion (happy=pink/orange, neutral=cyan, angry=red, sad=blue)
  - glow_intensity ← audio_energy (louder = brighter bloom that pulses with music)
  - edge_sensitivity ← activity_mode (production=more edges, idle=fewer)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot

# Synthwave neon palette (BGR) — full spectrum
_SYNTHWAVE_PALETTE = [
    (255, 50, 200),  # hot pink / magenta
    (255, 100, 255),  # pink-purple
    (200, 50, 255),  # purple
    (255, 50, 100),  # blue-purple
    (255, 200, 50),  # cyan
    (200, 255, 50),  # teal-cyan
    (100, 255, 100),  # green
    (50, 255, 200),  # yellow-green
    (50, 200, 255),  # orange
    (80, 100, 255),  # hot orange
    (50, 50, 255),  # red
    (150, 50, 255),  # red-pink
]

# Emotion → palette index offset (shifts the cycle start point)
_EMOTION_HUE_OFFSET: dict[str, int] = {
    "happy": 8,  # warm orange start
    "excited": 10,  # hot red start
    "neutral": 4,  # cool cyan start
    "sad": 3,  # blue-purple start
    "angry": 10,  # red start
    "fear": 2,  # purple start
    "surprise": 6,  # green start
}


class NeonEffect(BaseEffect):
    name = "neon"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        pass

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        from agents.studio_fx.gpu import GpuAccel

        if not hasattr(self, "_gpu"):
            self._gpu = GpuAccel()

        h, w = frame.shape[:2]
        gpu_frame = self._gpu.upload(frame)
        gpu_gray = self._gpu.cvt_color(gpu_frame, cv2.COLOR_BGR2GRAY)

        # --- Perception: edge sensitivity ---
        if p.activity_mode in ("production", "coding"):
            low_thresh, high_thresh = 40, 100
        else:
            low_thresh, high_thresh = 60, 140

        # Edge detection (GPU-accelerated)
        gpu_edges = self._gpu.canny(gpu_gray, low_thresh, high_thresh)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
        gpu_edges_thick = self._gpu.dilate(gpu_edges, kernel, iterations=1)
        edges_thick = self._gpu.download(gpu_edges_thick)

        # --- Glow bloom ---
        glow_strength = 0.6 + p.audio_energy * 2.0
        glow_strength = min(2.0, glow_strength)

        blur_size = max(15, min(51, int(w * 0.03))) | 1
        glow = cv2.GaussianBlur(edges_thick.astype(np.float32), (blur_size, blur_size), 0)
        glow2 = cv2.GaussianBlur(glow, (blur_size * 2 + 1, blur_size * 2 + 1), 0)
        glow_combined = glow * 0.6 + glow2 * 0.4
        glow_max = glow_combined.max()
        glow_norm = glow_combined / (glow_max + 1e-6)

        # --- Synthwave progressive color ---
        # Color varies across the image width — creates rainbow neon gradient
        palette = _SYNTHWAVE_PALETTE
        n_colors = len(palette)
        offset = _EMOTION_HUE_OFFSET.get(p.top_emotion, 4)
        # Time-based slow cycle
        time_offset = t * 0.3

        # Build per-column color array (progressive synthwave spread)
        edge_colored = np.zeros((h, w, 3), dtype=np.float32)
        glow_colored = np.zeros((h, w, 3), dtype=np.float32)
        edge_mask = edges_thick.astype(np.float32) / 255.0

        # Divide frame into color bands
        band_width = max(1, w // n_colors)
        for i in range(n_colors):
            x0 = i * band_width
            x1 = min(w, (i + 1) * band_width) if i < n_colors - 1 else w
            ci = (i + offset + int(time_offset)) % n_colors
            color_f = np.array(palette[ci], dtype=np.float32) / 255.0
            for c in range(3):
                edge_colored[:, x0:x1, c] = edge_mask[:, x0:x1] * color_f[c]
                glow_colored[:, x0:x1, c] = glow_norm[:, x0:x1] * color_f[c] * glow_strength

        # --- Very dark base ---
        dark_base = frame.astype(np.float32) / 255.0 * 0.12

        # --- Composite ---
        out = dark_base + glow_colored * 0.7 + edge_colored * 1.0
        out = np.clip(out * 255, 0, 255).astype(np.uint8)

        return out
