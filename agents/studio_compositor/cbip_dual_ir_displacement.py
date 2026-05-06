"""CBIP dual-IR displacement Cairo source.

Consumes two near-time-synchronized Pi-NoIR state JSON streams and renders a
single displacement-oriented visual source for the compositor. The first Pi
daemon slice may land before frame bytes are persisted in the council-side JSON,
so this source accepts optional image fields when present and falls back to a
procedural dual-IR field derived from the telemetry.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import cairo
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .cairo_source import CairoSource

log = logging.getLogger(__name__)

EffectMode = Literal["chroma", "difference", "warp"]

_HAPAX_HOME: Final[Path] = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
_DEFAULT_STATE_DIR: Final[Path] = _HAPAX_HOME / "hapax-state" / "pi-noir"
DEFAULT_PRIMARY_STATE_PATH: Final[Path] = _DEFAULT_STATE_DIR / "cam_primary.json"
DEFAULT_SECONDARY_STATE_PATH: Final[Path] = _DEFAULT_STATE_DIR / "cam_secondary.json"

DEFAULT_SYNC_TOLERANCE_S: Final[float] = 0.100
DEFAULT_MAX_FRAME_AGE_S: Final[float] = 2.0
DEFAULT_EFFECT_MODE: Final[EffectMode] = "chroma"

_IMAGE_B64_KEYS: Final[tuple[str, ...]] = (
    "frame_b64",
    "frame_jpeg_b64",
    "grey_jpeg_b64",
    "image_b64",
    "jpeg_b64",
    "png_b64",
)
_IMAGE_PATH_KEYS: Final[tuple[str, ...]] = (
    "frame_path",
    "frame_file",
    "grey_frame_path",
    "image_path",
    "jpeg_path",
    "png_path",
)
_VALID_MODES: Final[set[str]] = {"chroma", "difference", "warp"}


@dataclass(slots=True)
class IrStreamSnapshot:
    """One decoded Pi-NoIR stream snapshot."""

    label: str
    path: Path
    payload: dict[str, Any]
    mtime: float
    fresh: bool
    reason: str
    image: Image.Image | None = None

    @property
    def motion_delta(self) -> float:
        return _coerce_float(self.payload.get("motion_delta"), default=0.0)

    @property
    def brightness(self) -> float:
        return _coerce_float(self.payload.get("ir_brightness"), default=0.0)


def _coerce_float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mode_from_env() -> EffectMode:
    raw = os.environ.get("HAPAX_CBIP_DUAL_IR_MODE", DEFAULT_EFFECT_MODE).strip().lower()
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    return DEFAULT_EFFECT_MODE


def _strip_data_uri(raw: str) -> str:
    if "," in raw and raw.lstrip().lower().startswith("data:"):
        return raw.split(",", 1)[1]
    return raw


def _image_from_bytes(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            return opened.convert("L")
    except (OSError, UnidentifiedImageError):
        return None


def _image_from_path(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as opened:
            return opened.convert("L")
    except (OSError, UnidentifiedImageError):
        return None


def _extract_image(payload: dict[str, Any], *, base_dir: Path) -> Image.Image | None:
    """Best-effort image extraction from future Pi-side JSON schemas.

    The dual-camera daemon task is separate and may choose base64 image fields
    or path-backed frame references. Accept both shapes so this source is ready
    for either producer without another council-side schema migration.
    """
    for key in _IMAGE_B64_KEYS:
        raw = payload.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            data = base64.b64decode(_strip_data_uri(raw), validate=True)
        except (binascii.Error, ValueError):
            continue
        image = _image_from_bytes(data)
        if image is not None:
            return image

    frame = payload.get("frame")
    if isinstance(frame, dict):
        for key in ("b64", "jpeg_b64", "png_b64"):
            raw = frame.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                data = base64.b64decode(_strip_data_uri(raw), validate=True)
            except (binascii.Error, ValueError):
                continue
            image = _image_from_bytes(data)
            if image is not None:
                return image

    for key in _IMAGE_PATH_KEYS:
        raw = payload.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        image = _image_from_path(path)
        if image is not None:
            return image
    return None


def _fit_luma(image: Image.Image, width: int, height: int) -> np.ndarray:
    fitted = ImageOps.fit(
        image.convert("L"),
        (width, height),
        method=Image.Resampling.BILINEAR,
        centering=(0.5, 0.5),
    )
    return np.asarray(fitted, dtype=np.uint8)


def _rgba_to_cairo_surface(rgba: np.ndarray) -> tuple[cairo.ImageSurface, np.ndarray]:
    """Create a Cairo ARGB32 surface from an RGBA uint8 array.

    Cairo's native little-endian ARGB32 memory layout is BGRA. The returned
    array is kept by the caller until after paint() so the surface's backing
    buffer stays alive.
    """
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected HxWx4 uint8 RGBA array")
    height, width, _ = rgba.shape
    bgra = np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]])
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, width)
    if stride != width * 4:
        padded = np.zeros((height, stride), dtype=np.uint8)
        padded[:, : width * 4] = bgra.reshape(height, width * 4)
        surface = cairo.ImageSurface.create_for_data(
            padded,
            cairo.FORMAT_ARGB32,
            width,
            height,
            stride,
        )
        return surface, padded
    surface = cairo.ImageSurface.create_for_data(
        bgra,
        cairo.FORMAT_ARGB32,
        width,
        height,
        stride,
    )
    return surface, bgra


def compose_displacement_rgba(
    primary: Image.Image,
    secondary: Image.Image,
    width: int,
    height: int,
    *,
    mode: EffectMode = DEFAULT_EFFECT_MODE,
    t: float = 0.0,
) -> np.ndarray:
    """Return the composed dual-IR effect as RGBA pixels."""
    a = _fit_luma(primary, width, height)
    b = _fit_luma(secondary, width, height)
    alpha = np.full((height, width), 255, dtype=np.uint8)

    if mode == "difference":
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.uint8)
        base = ((a.astype(np.uint16) + b.astype(np.uint16)) // 2).astype(np.uint8)
        red = np.maximum(diff, (base.astype(np.float32) * 0.35).astype(np.uint8))
        green = np.maximum(base, (diff.astype(np.float32) * 0.45).astype(np.uint8))
        blue = np.clip(255 - diff.astype(np.int16), 0, 255).astype(np.uint8)
        return np.dstack((red, green, blue, alpha))

    if mode == "warp":
        h_idx = np.arange(height)[:, None]
        x_idx = np.tile(np.arange(width), (height, 1))
        disparity = (a.astype(np.int16) - b.astype(np.int16)).astype(np.float32) / 255.0
        wave = np.sin((h_idx / max(1.0, height)) * math.tau * 3.0 + t * 0.55) * 3.0
        offset = np.rint(disparity * 10.0 + wave).astype(np.int16)
        warped_x = np.clip(x_idx + offset, 0, width - 1)
        warped = a[np.arange(height)[:, None], warped_x]
        red = warped
        green = np.maximum((b.astype(np.float32) * 0.88).astype(np.uint8), warped // 2)
        blue = np.roll(b, shift=max(1, width // 96), axis=1)
        return np.dstack((red, green, blue, alpha))

    shift = max(1, int(round(math.sin(t * 0.45) * 4.0)))
    red = np.roll(a, shift=shift, axis=1)
    gb = np.roll(b, shift=-shift, axis=1)
    blue = np.maximum((gb.astype(np.float32) * 0.82).astype(np.uint8), a // 4)
    return np.dstack((red, gb, blue, alpha))


class CBIPDualIrDisplacementCairoSource(CairoSource):
    """Render a dual-Pi-NoIR displacement source for the CBIP platter."""

    def __init__(
        self,
        *,
        primary_path: Path | None = None,
        secondary_path: Path | None = None,
        mode: EffectMode | None = None,
        sync_tolerance_s: float = DEFAULT_SYNC_TOLERANCE_S,
        max_frame_age_s: float = DEFAULT_MAX_FRAME_AGE_S,
    ) -> None:
        self.primary_path = primary_path or Path(
            os.environ.get("HAPAX_CBIP_DUAL_IR_PRIMARY_PATH", str(DEFAULT_PRIMARY_STATE_PATH))
        )
        self.secondary_path = secondary_path or Path(
            os.environ.get("HAPAX_CBIP_DUAL_IR_SECONDARY_PATH", str(DEFAULT_SECONDARY_STATE_PATH))
        )
        self.mode: EffectMode = mode or _mode_from_env()
        self.sync_tolerance_s = sync_tolerance_s
        self.max_frame_age_s = max_frame_age_s
        self.last_status: dict[str, Any] = {}

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del state
        now = time.time()
        primary = self._read_snapshot(self.primary_path, label="primary", now=now)
        secondary = self._read_snapshot(self.secondary_path, label="secondary", now=now)
        synced = self._synced_pair(primary, secondary)

        self._paint_backdrop(cr, canvas_w, canvas_h, t)
        if synced and primary.image is not None and secondary.image is not None:
            self._paint_image_pair(cr, primary.image, secondary.image, canvas_w, canvas_h, t)
            status = "paired"
        elif synced:
            self._paint_procedural_pair(cr, primary, secondary, canvas_w, canvas_h, t)
            status = "paired_telemetry"
        elif primary.fresh or secondary.fresh:
            live = primary if primary.fresh else secondary
            self._paint_single_fallback(cr, live, canvas_w, canvas_h, t)
            status = "single_fallback"
        else:
            self._paint_offline(cr, canvas_w, canvas_h)
            status = "offline"

        self.last_status = {
            "status": status,
            "mode": self.mode,
            "primary": primary.reason,
            "secondary": secondary.reason,
            "mtime_delta_s": (
                round(abs(primary.mtime - secondary.mtime), 3)
                if primary.fresh and secondary.fresh
                else None
            ),
        }
        self._paint_status_line(cr, canvas_w, canvas_h, primary, secondary, status)

    def _read_snapshot(self, path: Path, *, label: str, now: float) -> IrStreamSnapshot:
        try:
            stat = path.stat()
        except OSError:
            return IrStreamSnapshot(label, path, {}, 0.0, False, "missing")

        age = max(0.0, now - stat.st_mtime)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return IrStreamSnapshot(label, path, {}, stat.st_mtime, False, "malformed")
        if not isinstance(payload, dict):
            return IrStreamSnapshot(label, path, {}, stat.st_mtime, False, "malformed")
        if age > self.max_frame_age_s:
            return IrStreamSnapshot(label, path, payload, stat.st_mtime, False, "stale")

        image = _extract_image(payload, base_dir=path.parent)
        return IrStreamSnapshot(
            label=label,
            path=path,
            payload=payload,
            mtime=stat.st_mtime,
            fresh=True,
            reason="fresh_image" if image is not None else "fresh_telemetry",
            image=image,
        )

    def _synced_pair(self, primary: IrStreamSnapshot, secondary: IrStreamSnapshot) -> bool:
        if not primary.fresh or not secondary.fresh:
            return False
        return abs(primary.mtime - secondary.mtime) <= self.sync_tolerance_s

    def _paint_image_pair(
        self,
        cr: cairo.Context,
        primary: Image.Image,
        secondary: Image.Image,
        canvas_w: int,
        canvas_h: int,
        t: float,
    ) -> None:
        rgba = compose_displacement_rgba(
            primary,
            secondary,
            canvas_w,
            canvas_h,
            mode=self.mode,
            t=t,
        )
        surface, _owner = _rgba_to_cairo_surface(rgba)
        cr.save()
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(0.92)
        cr.restore()

    def _paint_backdrop(self, cr: cairo.Context, canvas_w: int, canvas_h: int, t: float) -> None:
        cr.save()
        cr.set_source_rgb(0.015, 0.018, 0.02)
        cr.paint()
        line_opacity = 0.045
        for i in range(0, canvas_w, max(12, canvas_w // 40)):
            cr.set_source_rgba(0.1, 0.55, 0.62, line_opacity)
            cr.rectangle(i, 0, 1, canvas_h)
            cr.fill()
        cr.restore()

    def _paint_procedural_pair(
        self,
        cr: cairo.Context,
        primary: IrStreamSnapshot,
        secondary: IrStreamSnapshot,
        canvas_w: int,
        canvas_h: int,
        t: float,
    ) -> None:
        motion = max(primary.motion_delta, secondary.motion_delta)
        brightness_a = min(1.0, primary.brightness / 255.0)
        brightness_b = min(1.0, secondary.brightness / 255.0)
        disparity = max(-1.0, min(1.0, brightness_a - brightness_b))
        rows = 18
        cols = 28
        cell_w = canvas_w / cols
        cell_h = canvas_h / rows
        warp = disparity * cell_w * 0.75
        for row in range(rows):
            y = row * cell_h
            for col in range(cols):
                x = col * cell_w
                drift = math.sin(t * 0.4 + row * 0.55 + col * 0.12) * warp
                pulse = 0.16 + 0.28 * min(1.0, motion * 12.0)
                cr.set_source_rgba(0.85, 0.12, 0.08, pulse * (0.45 + brightness_a * 0.55))
                cr.rectangle(x + drift, y, cell_w * 0.46, cell_h * 0.76)
                cr.fill()
                cr.set_source_rgba(0.04, 0.78, 0.72, pulse * (0.45 + brightness_b * 0.55))
                cr.rectangle(
                    x - drift + cell_w * 0.36, y + cell_h * 0.16, cell_w * 0.46, cell_h * 0.76
                )
                cr.fill()

    def _paint_single_fallback(
        self,
        cr: cairo.Context,
        snapshot: IrStreamSnapshot,
        canvas_w: int,
        canvas_h: int,
        t: float,
    ) -> None:
        if snapshot.image is not None:
            rgba = compose_displacement_rgba(
                snapshot.image,
                snapshot.image,
                canvas_w,
                canvas_h,
                mode="chroma",
                t=t,
            )
            surface, _owner = _rgba_to_cairo_surface(rgba)
            cr.set_source_surface(surface, 0, 0)
            cr.paint_with_alpha(0.70)
        else:
            self._paint_procedural_pair(cr, snapshot, snapshot, canvas_w, canvas_h, t)
        cr.save()
        cr.set_source_rgba(0.95, 0.72, 0.18, 0.18)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.restore()

    def _paint_offline(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> None:
        cr.save()
        cr.set_source_rgba(0.20, 0.24, 0.25, 0.30)
        for y in range(0, canvas_h, max(18, canvas_h // 18)):
            cr.rectangle(0, y, canvas_w, 1)
            cr.fill()
        cr.restore()

    def _paint_status_line(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        primary: IrStreamSnapshot,
        secondary: IrStreamSnapshot,
        status: str,
    ) -> None:
        delta = abs(primary.mtime - secondary.mtime) if primary.fresh and secondary.fresh else None
        sync = f"{delta * 1000:.0f}ms" if delta is not None else "--"
        text = (
            f"CBIP DUAL IR  {status.upper()}  {self.mode.upper()}  "
            f"P:{primary.reason} S:{secondary.reason} SYNC:{sync}"
        )
        cr.save()
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(max(10.0, min(16.0, canvas_h * 0.035)))
        xb, yb, tw, th, _, _ = cr.text_extents(text)
        pad = 6.0
        x = 8.0
        y = canvas_h - 10.0
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.48)
        cr.rectangle(x - pad, y - th - pad + yb, min(tw + pad * 2, canvas_w - 16), th + pad * 2)
        cr.fill()
        cr.set_source_rgba(0.72, 0.92, 0.88, 0.92)
        cr.move_to(x, y)
        cr.show_text(text[:140])
        cr.restore()


__all__ = [
    "CBIPDualIrDisplacementCairoSource",
    "DEFAULT_PRIMARY_STATE_PATH",
    "DEFAULT_SECONDARY_STATE_PATH",
    "DEFAULT_SYNC_TOLERANCE_S",
    "compose_displacement_rgba",
]
