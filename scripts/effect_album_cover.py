#!/usr/bin/env python3
"""Pass the album cover through a full-strength CRT/glow effects chain.

Loads ~/gdrive-drop/oudepode-cover-3000.png (the BitchX-in-Moksha render
from scripts/render_album_cover.py) and applies the chain to make it pop:

    0. PRE-POP — saturation + contrast lift (so colors survive bloom)
    1. Chromatic aberration — R/B channel split, ±6px (CRT edge fringe)
    2. Bloom — high-threshold mask, additive screen (no wash)
    3. Scanlines — 4px-thick bands at 30% opacity (8px cycle)
    4. Vignette — restrained 0.35 corner falloff
    5. Film grain — 5.0 amplitude analog tooth
    6. POST-POP — final contrast + saturation (recover punch)

Output: ~/gdrive-drop/oudepode-cover-3000-fx.png
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

INPUT = Path.home() / "gdrive-drop" / "oudepode-cover-3000.png"
OUTPUT = Path.home() / "gdrive-drop" / "oudepode-cover-3000-fx.png"


# ── Effects ─────────────────────────────────────────────────────────


def pre_pop(img: Image.Image, *, sat: float = 1.45, contrast: float = 1.18) -> Image.Image:
    """Boost saturation + contrast BEFORE effects so bloom doesn't wash out."""
    img = ImageEnhance.Color(img).enhance(sat)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    return img


def chromatic_aberration(arr: np.ndarray, shift: int = 6) -> np.ndarray:
    """Split R/B channels horizontally for CRT-edge fringe."""
    out = arr.copy()
    out[:, :, 0] = np.roll(arr[:, :, 0], shift, axis=1)
    out[:, :, 2] = np.roll(arr[:, :, 2], -shift, axis=1)
    return out


def bloom_additive(
    img: Image.Image, *, threshold: int = 210, blur_radius: int = 36, gain: float = 0.55
) -> Image.Image:
    """High-threshold bloom blended ADDITIVELY (np.minimum cap), not as alpha-blend.

    Alpha blend with bright source desaturates everything. Additive
    screen keeps the source colors fully present and only lifts the
    bright pixels — the 'pop' the operator asked for.
    """
    arr = np.array(img.convert("RGB")).astype(np.float32)
    luma = arr.mean(axis=2)
    mask = (luma > threshold).astype(np.float32)[..., None]
    bright = (arr * mask).clip(0, 255).astype(np.uint8)
    bright_blurred = np.array(
        Image.fromarray(bright).filter(ImageFilter.GaussianBlur(radius=blur_radius))
    ).astype(np.float32)
    out = np.minimum(arr + bright_blurred * gain, 255.0)
    return Image.fromarray(out.astype(np.uint8))


def scanlines_banded(
    arr: np.ndarray, *, band: int = 4, cycle: int = 8, opacity: float = 0.30
) -> np.ndarray:
    """Darken `band`-pixel-thick rows every `cycle` pixels.

    Single-pixel scanlines on a 3000-tall canvas average out to a
    uniform darken. Thicker bands read as actual scanlines.
    """
    h = arr.shape[0]
    mask = np.ones((h, 1, 1), dtype=np.float32)
    for y in range(0, h, cycle):
        mask[y : y + band, :, :] = 1.0 - opacity
    return (arr.astype(np.float32) * mask).clip(0, 255).astype(np.uint8)


def vignette(arr: np.ndarray, strength: float = 0.35) -> np.ndarray:
    """Radial darken from corners — restrained so it doesn't crush detail."""
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r_max = float(np.sqrt(cx**2 + cy**2))
    falloff = 1.0 - (r / r_max) ** 2 * strength
    falloff = falloff.clip(0.0, 1.0)[..., None]
    return (arr.astype(np.float32) * falloff).clip(0, 255).astype(np.uint8)


def film_grain(arr: np.ndarray, *, amplitude: float = 5.0, seed: int = 42) -> np.ndarray:
    """Low-amplitude gaussian noise — analog film tooth."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, amplitude, arr.shape[:2]).astype(np.float32)[..., None]
    return (arr.astype(np.float32) + noise).clip(0, 255).astype(np.uint8)


def post_pop(img: Image.Image, *, contrast: float = 1.15, sat: float = 1.20) -> Image.Image:
    """Final contrast + saturation lift to recover punch after the chain."""
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Color(img).enhance(sat)
    return img


# ── Pipeline ────────────────────────────────────────────────────────


def render_fx() -> Path:
    if not INPUT.exists():
        raise FileNotFoundError(f"{INPUT} missing — run scripts/render_album_cover.py first")

    img = Image.open(INPUT).convert("RGB")

    # 0. Pre-pop
    img = pre_pop(img)
    arr = np.array(img)

    # 1. Chromatic aberration
    arr = chromatic_aberration(arr, shift=6)

    # 2. Bloom (additive, doesn't wash out)
    img = bloom_additive(Image.fromarray(arr))
    arr = np.array(img)

    # 3. Scanlines (banded)
    arr = scanlines_banded(arr, band=4, cycle=8, opacity=0.30)

    # 4. Vignette
    arr = vignette(arr, strength=0.35)

    # 5. Film grain
    arr = film_grain(arr, amplitude=5.0)

    # 6. Post-pop (final lift)
    img = post_pop(Image.fromarray(arr))
    img.save(OUTPUT, "PNG")
    return OUTPUT


if __name__ == "__main__":
    out = render_fx()
    print(f"wrote {out}")
