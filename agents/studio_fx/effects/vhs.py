"""VHS effect — authentic analog tape degradation simulation.

DISTINCT 1: Chroma bandwidth limiting — luma sharp, chroma blurred (VHS = 240 line chroma)
DISTINCT 2: Head-switching noise bar at frame bottom (physical artifact of head toggle)

DOMINANT 1: Nostalgic warmth and imperfection
DOMINANT 2: Cultural resonance in hip hop (Kanye "Fade", Tyler "IFHY", DJ Screw tapes)

Technique: Convert to YCrCb, blur chroma channels heavily (bandwidth limit),
add scanlines, tracking error bands, head-switch noise bar, tape noise,
warm sepia tint, slight softness.

Perception:
  - tracking_error ← audio_energy (bass vibrates the VCR, causes tracking problems)
  - head_switch_height ← 1 - flow_score (low engagement = worse playback quality)
  - noise ← !operator_present (empty room = tape hiss increases)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class VhsEffect(BaseEffect):
    name = "vhs"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._scanlines = _make_scanlines(width, height)
        self._rng = np.random.default_rng(42)
        self._tick = 0

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        self._scanlines = _make_scanlines(width, height)

    def reset(self) -> None:
        self._rng = np.random.default_rng(42)
        self._tick = 0

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        self._tick += 1
        energy = min(1.0, p.audio_energy * 10)

        # === 1. CHROMA BANDWIDTH LIMITING (DISTINCT) ===
        # VHS stores chroma at ~240 lines vs 480 luma — blur chroma channels heavily
        ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        # Blur chroma (Cr, Cb) with large horizontal kernel — VHS chroma smears horizontally
        chroma_blur = max(7, (w // 60) | 1)
        ycrcb[:, :, 1] = cv2.GaussianBlur(ycrcb[:, :, 1], (chroma_blur, 3), 0)
        ycrcb[:, :, 2] = cv2.GaussianBlur(ycrcb[:, :, 2], (chroma_blur, 3), 0)
        out = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)

        # === 2. CHROMA CHANNEL OFFSET (color bleeding) ===
        shift = max(2, int(3 + energy * 3))
        out[:, :, 0] = np.roll(out[:, :, 0], shift, axis=1)
        out[:, :, 2] = np.roll(out[:, :, 2], -shift, axis=1)

        # === 3. TRACKING ERROR BANDS ===
        # Perception: severity from audio energy
        band_chance = 0.08 + energy * 0.35
        max_shift = int(3 + energy * 25)
        if self._rng.random() < band_chance:
            n_bands = self._rng.integers(1, max(2, int(3 + energy * 5)))
            for _ in range(n_bands):
                y0 = self._rng.integers(0, max(1, h - 8))
                bh = self._rng.integers(2, max(3, min(16, h // 15)))
                y1 = min(h, y0 + bh)
                s = self._rng.integers(-max_shift, max_shift + 1)
                if s != 0:
                    out[y0:y1] = np.roll(out[y0:y1], s, axis=1)

        # === 4. HEAD-SWITCHING NOISE BAR (DISTINCT) ===
        # Perception: height from inverse flow score
        bar_h = max(4, int((8 + (1 - p.flow_score) * 16) * h / 480))
        bar_y = h - bar_h
        # Randomized horizontal shift + noise in the bar
        bar_shift = self._rng.integers(-w // 4, w // 4)
        out[bar_y:] = np.roll(out[bar_y:], bar_shift, axis=1)
        # Add heavy noise to the bar
        bar_noise = self._rng.integers(0, 180, size=(bar_h, w, 3), dtype=np.uint8)
        out[bar_y:] = cv2.addWeighted(out[bar_y:], 0.3, bar_noise[:, :w], 0.7, 0)

        # === 5. SCANLINES ===
        if self._scanlines.shape[:2] != (h, w):
            self._scanlines = _make_scanlines(w, h)
        out = cv2.addWeighted(out, 0.82, self._scanlines[:h, :w], 0.18, 0)

        # === 6. TAPE NOISE ===
        noise_strength = 0.06 if p.operator_present else 0.12
        noise = self._rng.integers(
            0, max(1, int(180 * noise_strength)), size=(h, w), dtype=np.uint8
        )
        noise_bgr = cv2.cvtColor(noise, cv2.COLOR_GRAY2BGR)
        out = cv2.addWeighted(out, 0.93, noise_bgr, 0.07, 0)

        # === 7. ANALOG SOFTNESS ===
        out = cv2.GaussianBlur(out, (3, 3), 0.7)

        # === 8. WARM SEPIA TINT ===
        sepia_kernel = np.array(
            [[0.272, 0.534, 0.131], [0.349, 0.686, 0.168], [0.393, 0.769, 0.189]],
            dtype=np.float32,
        )
        sepia = np.clip(cv2.transform(out, sepia_kernel), 0, 255).astype(np.uint8)
        out = cv2.addWeighted(out, 0.70, sepia, 0.30, 0)

        # === 9. SLIGHT BRIGHTNESS REDUCTION (worn tape) ===
        out = (out.astype(np.float32) * 0.90).astype(np.uint8)

        return out


def _make_scanlines(width: int, height: int) -> np.ndarray:
    """Pre-compute scanline overlay — every other row darkened."""
    mask = np.zeros((height, width, 3), dtype=np.uint8)
    mask[::2, :] = 55  # stronger scanlines for more clarity
    return mask
