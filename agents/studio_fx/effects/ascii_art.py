"""ASCII art effect — real-time text character rendering.

DISTINCT 1: Image represented entirely as text characters (brightness→character density)
DISTINCT 2: Fixed grid quantization — coarser than any other effect

Technique: Downsample to character grid, map each cell's brightness to an
ASCII character from a density ramp, render characters onto black canvas.

Perception:
  - grid_resolution ← audio_energy (louder = finer grid = more detail)
  - character_color ← top_emotion (green=neutral/matrix, amber=warm, cyan=cool)
"""

from __future__ import annotations

import cv2
import numpy as np

from agents.studio_fx.base import BaseEffect
from agents.studio_fx.perception import PerceptionSnapshot

# ASCII density ramp — darkest to brightest
_RAMP = " .:-=+*#%@"

_EMOTION_COLOR: dict[str, tuple[int, int, int]] = {
    "happy": (50, 200, 255),  # warm amber
    "excited": (30, 150, 255),  # orange
    "neutral": (50, 255, 50),  # matrix green
    "sad": (255, 150, 50),  # cool blue
    "angry": (50, 50, 255),  # red
}
_DEFAULT_COLOR = (50, 255, 50)  # green


class AsciiEffect(BaseEffect):
    name = "ascii"

    def __init__(self, width: int, height: int) -> None:
        super().__init__(width, height)

    def resize(self, width: int, height: int) -> None:
        super().resize(width, height)

    def reset(self) -> None:
        pass

    def process(self, frame: np.ndarray, p: PerceptionSnapshot, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        energy = min(1.0, p.audio_energy * 10)

        # Character cell size — smaller = more detail
        cell_w = max(4, int(10 - energy * 5))
        cell_h = cell_w * 2  # characters are ~2:1 aspect

        cols = w // cell_w
        rows = h // cell_h

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Downsample to grid
        small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA)

        # Color from emotion
        color = _EMOTION_COLOR.get(p.top_emotion, _DEFAULT_COLOR)

        # Render onto black canvas
        out = np.zeros((h, w, 3), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = cell_w / 12.0
        thickness = 1

        ramp_len = len(_RAMP) - 1
        for r in range(rows):
            for c in range(cols):
                val = small[r, c]
                char_idx = int(val / 255.0 * ramp_len)
                char = _RAMP[char_idx]
                if char == " ":
                    continue
                x = c * cell_w
                y = r * cell_h + cell_h
                cv2.putText(out, char, (x, y), font, font_scale, color, thickness, cv2.LINE_AA)

        return out
