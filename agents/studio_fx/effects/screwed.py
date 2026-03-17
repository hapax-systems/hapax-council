"""Screwed effect — chopped & screwed temporal distortion.

DISTINCT 1: Purple-tinted syrupy temporal smear (not just slow-mo — specific purple/magenta
            color shift that references Houston lean/purple drank aesthetic)
DISTINCT 2: Choppy repetition / stutter within the slowdown (freeze + replay state machine)

DOMINANT 1: Deep cultural specificity — DJ Screw, Swishahouse, Houston
DOMINANT 2: Meditative/hypnotic quality — trance-like visual state

Technique: Heavy temporal accumulation (0.85+ blend factor) for syrupy trails.
Purple color grading via channel manipulation. Freeze/replay state machine
for the "chopped" stutter. Heavy blur + vignette for underwater feel.
Horizontal slice displacement for liquid warp.

Perception:
  - temporal_slowdown ← audio_energy inverted (quieter = slower/more screwed)
  - purple_intensity ← flow_score (deeper flow = deeper purple)
  - freeze_probability ← 1 - interruptibility (focused = more chop)
"""

from __future__ import annotations

import enum

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot


class _Phase(enum.Enum):
    NORMAL = "normal"
    FREEZE = "freeze"
    REPLAY = "replay"


class ScrewedEffect(BaseEffect):
    name = "screwed"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)
        self._trail: np.ndarray | None = None
        self._rng = np.random.default_rng(77)
        self._phase = _Phase.NORMAL
        self._phase_counter = 0
        self._freeze_duration = 0
        self._frozen_frame: np.ndarray | None = None
        self._replay_buffer: list[np.ndarray] = []
        self._replay_idx = 0
        self._frame_count = 0

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)
        if self._trail is not None:
            self._trail = cv2.resize(self._trail, (width, height)).astype(np.float32)
        if self._frozen_frame is not None:
            self._frozen_frame = cv2.resize(self._frozen_frame, (width, height))
        self._replay_buffer = [cv2.resize(f, (width, height)) for f in self._replay_buffer]

    def reset(self) -> None:
        self._trail = None
        self._phase = _Phase.NORMAL
        self._phase_counter = 0
        self._frozen_frame = None
        self._replay_buffer.clear()
        self._replay_idx = 0
        self._frame_count = 0

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        self._frame_count += 1

        # --- Perception ---
        # Trail persistence: higher flow = more syrupy (blend 0.85-0.93)
        trail_alpha = 0.85 + p.flow_score * 0.08

        # Purple intensity: deeper flow = deeper purple
        purple_strength = 0.3 + p.flow_score * 0.4

        # No stutter/freeze — pure syrupy temporal smear only

        # --- Heavy temporal accumulation (syrupy trails) ---
        if self._trail is None or self._trail.shape[:2] != (h, w):
            self._trail = frame.astype(np.float32)
        else:
            self._trail = self._trail * trail_alpha + frame.astype(np.float32) * (1.0 - trail_alpha)

        out = self._trail.copy()

        # --- PURPLE COLOR GRADING (DISTINCT) ---
        # Push into purple: boost blue + red, crush green
        # Stronger purple in shadows, subtler in highlights
        luma = out[:, :, 0] * 0.114 + out[:, :, 1] * 0.587 + out[:, :, 2] * 0.299
        shadow_mask = 1.0 - (luma / 255.0)  # stronger in darks

        out[:, :, 0] = np.clip(out[:, :, 0] + shadow_mask * 40 * purple_strength, 0, 255)  # B hard
        out[:, :, 1] = np.clip(
            out[:, :, 1] * (1.0 - 0.35 * purple_strength), 0, 255
        )  # G crush hard
        out[:, :, 2] = np.clip(out[:, :, 2] + shadow_mask * 18 * purple_strength, 0, 255)  # R

        # Desaturate slightly for that drugged-out, faded quality
        out_u8 = np.clip(out, 0, 255).astype(np.uint8)
        hsv = cv2.cvtColor(out_u8, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = (hsv[:, :, 1].astype(np.float32) * 0.65).astype(np.uint8)
        # Reduce brightness for the dark, underwater feel
        hsv[:, :, 2] = (hsv[:, :, 2].astype(np.float32) * 0.75).astype(np.uint8)
        result = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

        # --- Horizontal slice displacement (liquid warp) ---
        n_slices = self._rng.integers(4, 10)
        for _ in range(n_slices):
            y = self._rng.integers(0, max(1, h - 4))
            sh = self._rng.integers(2, max(3, min(12, h // 25)))
            y1 = min(h, y + sh)
            shift = self._rng.integers(-5, 6)
            if shift != 0:
                result[y:y1] = np.roll(result[y:y1], shift, axis=1)

        # --- Heavy blur for syrupy/underwater feel ---
        result = cv2.GaussianBlur(result, (7, 7), 2.5)

        # --- Vignette (tunnel vision) ---
        vy, vx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = w / 2, h / 2
        dist = np.sqrt((vx - cx) ** 2 + (vy - cy) ** 2)
        max_dist = np.sqrt(cx**2 + cy**2)
        vignette = 1.0 - (dist / max_dist) ** 1.5 * 0.5
        for c in range(3):
            result[:, :, c] = (result[:, :, c].astype(np.float32) * vignette).astype(np.uint8)

        return result
