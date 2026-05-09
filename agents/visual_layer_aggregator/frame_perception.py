"""Rendered-frame formal property analysis for perceptual stimmung feedback.

Reads the post-FX compositor snapshot, evaluates formal visual properties
(brightness, contrast, color entropy, saturation), and returns a composite
score measuring deviation from aesthetic balance. 0.0 = balanced, 1.0 = extreme.

Closes the visual feedback loop: GPU render -> formal analysis -> stimmung
dimension -> shader modulation.
"""

from __future__ import annotations

import colorsys
import logging
import math
import time
from pathlib import Path
from typing import NamedTuple

log = logging.getLogger(__name__)

FX_SNAPSHOT_PATH = Path("/dev/shm/hapax-compositor/fx-snapshot.jpg")
_ANALYSIS_SIZE = 64
_STALE_S = 10.0


class FrameProperties(NamedTuple):
    brightness_extremity: float
    contrast_extremity: float
    entropy_deficit: float
    saturation_extremity: float
    composite: float


def analyze_frame(path: Path = FX_SNAPSHOT_PATH) -> FrameProperties | None:
    """Analyze formal properties of the current rendered frame.

    Returns None if the frame is unavailable, stale, or PIL is missing.
    """
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > _STALE_S:
            return None

        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB").resize(
                (_ANALYSIS_SIZE, _ANALYSIS_SIZE), Image.Resampling.LANCZOS
            )
            pixels = list(img.getdata())

        if not pixels:
            return None

        n = len(pixels)
        lumas: list[float] = []
        hues: list[float] = []
        sats: list[float] = []

        for r, g, b in pixels:
            lumas.append((0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0)
            h, s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            hues.append(h)
            sats.append(s)

        mean_luma = sum(lumas) / n
        variance = sum((lum - mean_luma) ** 2 for lum in lumas) / n
        stddev = variance**0.5
        mean_sat = sum(sats) / n

        # Brightness: ideal ~0.35 for dark ambient renders
        brightness_extremity = min(1.0, abs(mean_luma - 0.35) / 0.35)

        # Contrast: ideal stddev ~0.15
        contrast_extremity = min(1.0, abs(stddev - 0.15) / 0.15)

        # Color entropy: Shannon entropy of 12-bin hue histogram
        hue_bins = [0] * 12
        for h in hues:
            hue_bins[min(11, int(h * 12))] += 1
        max_entropy = math.log2(12)
        entropy = 0.0
        for count in hue_bins:
            if count > 0:
                p = count / n
                entropy -= p * math.log2(p)
        entropy_deficit = max(0.0, 1.0 - entropy / max_entropy)

        # Saturation: ideal ~0.4
        saturation_extremity = min(1.0, abs(mean_sat - 0.4) / 0.4)

        composite = (
            0.3 * brightness_extremity
            + 0.3 * contrast_extremity
            + 0.2 * entropy_deficit
            + 0.2 * saturation_extremity
        )

        return FrameProperties(
            brightness_extremity=round(brightness_extremity, 3),
            contrast_extremity=round(contrast_extremity, 3),
            entropy_deficit=round(entropy_deficit, 3),
            saturation_extremity=round(saturation_extremity, 3),
            composite=round(composite, 3),
        )
    except Exception:
        log.debug("Frame perception analysis failed", exc_info=True)
        return None
