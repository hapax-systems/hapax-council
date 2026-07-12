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
from .homage import get_active_package

log = logging.getLogger(__name__)

EffectMode = Literal["chroma", "difference", "warp"]

_HAPAX_HOME: Final[Path] = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
_DEFAULT_STATE_DIR: Final[Path] = _HAPAX_HOME / "hapax-state" / "pi-noir"
DEFAULT_PRIMARY_STATE_PATH: Final[Path] = _DEFAULT_STATE_DIR / "cam_primary.json"
DEFAULT_SECONDARY_STATE_PATH: Final[Path] = _DEFAULT_STATE_DIR / "cam_secondary.json"
DEFAULT_BRIO_IR_FRAME_SOURCES: Final[tuple[dict[str, object], ...]] = (
    {
        "label": "brio-operator-ir",
        "path": "/dev/shm/hapax-compositor/quake-live-ir-brio-operator.raw.bgra",
        "width": 340,
        "height": 340,
    },
    {
        "label": "brio-room-ir",
        "path": "/dev/shm/hapax-compositor/quake-live-ir-brio-room.raw.bgra",
        "width": 340,
        "height": 340,
    },
    {
        "label": "brio-synths-ir",
        "path": "/dev/shm/hapax-compositor/quake-live-ir-brio-synths.raw.bgra",
        "width": 340,
        "height": 340,
    },
)

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


@dataclass(frozen=True, slots=True)
class IrFrameSource:
    """Raw BGRA frame source produced by a local BRIO IR service."""

    label: str
    path: Path
    width: int
    height: int


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


def _image_from_bgra_path(path: Path, *, width: int, height: int) -> Image.Image | None:
    expected = width * height * 4
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < expected:
        return None
    try:
        frame = np.frombuffer(data[:expected], dtype=np.uint8).reshape((height, width, 4))
    except ValueError:
        return None
    # The DarkPlaces live-texture producer ABI is BGRA. For GREY v4l2 inputs
    # FFmpeg expands identical RGB channels, but use true luma so the reader is
    # also correct if a future IR producer uses a tinted diagnostic overlay.
    luma = (
        frame[:, :, 0].astype(np.float32) * 0.114
        + frame[:, :, 1].astype(np.float32) * 0.587
        + frame[:, :, 2].astype(np.float32) * 0.299
    ).astype(np.uint8)
    return Image.fromarray(luma)


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


def _parse_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _parse_dimension(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_ir_frame_sources(raw: object) -> tuple[IrFrameSource, ...]:
    entries = DEFAULT_BRIO_IR_FRAME_SOURCES if raw in (None, "") else raw
    if not isinstance(entries, (list, tuple)):
        return ()
    parsed: list[IrFrameSource] = []
    for index, entry in enumerate(entries, start=1):
        if isinstance(entry, str):
            path = _parse_path(entry)
            label = Path(entry).stem if path is not None else f"ir-{index}"
            width = 340
            height = 340
        elif isinstance(entry, dict):
            path = _parse_path(entry.get("path", entry.get("frame_path")))
            label = str(entry.get("label", entry.get("role", f"ir-{index}")))
            width = _parse_dimension(entry.get("width", entry.get("w")), default=340)
            height = _parse_dimension(entry.get("height", entry.get("h")), default=340)
        else:
            continue
        if path is None:
            continue
        parsed.append(IrFrameSource(label=label, path=path, width=width, height=height))
    return tuple(parsed)


def _fit_luma(image: Image.Image, width: int, height: int) -> np.ndarray:
    fitted = ImageOps.fit(
        image.convert("L"),
        (width, height),
        method=Image.Resampling.BILINEAR,
        centering=(0.5, 0.5),
    )
    return np.asarray(ImageOps.autocontrast(fitted, cutoff=1), dtype=np.uint8)


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


def _cbip_palette() -> dict[str, tuple[float, float, float, float]] | None:
    """Resolve CBIP-relevant palette roles from the active HOMAGE package.

    Returns None when no package is active (callers fall back to hardcoded values).
    """
    pkg = get_active_package()
    if pkg is None:
        return None
    return {
        "background": pkg.resolve_colour("background"),
        "accent_cyan": pkg.resolve_colour("accent_cyan"),
        "accent_red": pkg.resolve_colour("accent_red"),
        "accent_yellow": pkg.resolve_colour("accent_yellow"),
        "muted": pkg.resolve_colour("muted"),
        "bright": pkg.resolve_colour("bright"),
    }


class CBIPDualIrDisplacementCairoSource(CairoSource):
    """Render a dual-Pi-NoIR displacement source for the CBIP platter."""

    def __init__(
        self,
        *,
        primary_path: Path | None = None,
        secondary_path: Path | None = None,
        ir_frame_sources: object = None,
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
        self.ir_frame_sources = _parse_ir_frame_sources(ir_frame_sources)
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
        frame_snapshots = [
            self._read_frame_source(source, now=now) for source in self.ir_frame_sources
        ]
        live_frames = [
            snapshot
            for snapshot in frame_snapshots
            if snapshot.fresh and snapshot.image is not None
        ]
        if len(live_frames) >= 2:
            primary = live_frames[0]
            secondary = live_frames[1]
            self._paint_backdrop(cr, canvas_w, canvas_h, t)
            self._paint_image_pair(primary.image, secondary.image, cr, canvas_w, canvas_h, t)
            self._paint_frame_strip(cr, canvas_w, canvas_h, frame_snapshots)
            status = "paired_live_ir"
            self.last_status = self._status_payload(
                status=status,
                primary=primary,
                secondary=secondary,
                frame_snapshots=frame_snapshots,
            )
            self._paint_status_line(cr, canvas_w, canvas_h, primary, secondary, status)
            return
        if live_frames:
            live = live_frames[0]
            missing = next((snapshot for snapshot in frame_snapshots if not snapshot.fresh), live)
            self._paint_backdrop(cr, canvas_w, canvas_h, t)
            self._paint_single_fallback(cr, live, canvas_w, canvas_h, t)
            self._paint_frame_strip(cr, canvas_w, canvas_h, frame_snapshots)
            status = "single_live_ir_fallback"
            self.last_status = self._status_payload(
                status=status,
                primary=live,
                secondary=missing,
                frame_snapshots=frame_snapshots,
            )
            self._paint_status_line(cr, canvas_w, canvas_h, live, missing, status)
            return

        primary = self._read_snapshot(self.primary_path, label="primary", now=now)
        secondary = self._read_snapshot(self.secondary_path, label="secondary", now=now)
        synced = self._synced_pair(primary, secondary)

        self._paint_backdrop(cr, canvas_w, canvas_h, t)
        if synced and primary.image is not None and secondary.image is not None:
            self._paint_image_pair(primary.image, secondary.image, cr, canvas_w, canvas_h, t)
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

        self.last_status = self._status_payload(
            status=status,
            primary=primary,
            secondary=secondary,
            frame_snapshots=frame_snapshots,
        )
        self._paint_status_line(cr, canvas_w, canvas_h, primary, secondary, status)

    def _status_payload(
        self,
        *,
        status: str,
        primary: IrStreamSnapshot,
        secondary: IrStreamSnapshot,
        frame_snapshots: list[IrStreamSnapshot],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "mode": self.mode,
            "primary": primary.reason,
            "secondary": secondary.reason,
            "mtime_delta_s": (
                round(abs(primary.mtime - secondary.mtime), 3)
                if primary.fresh and secondary.fresh
                else None
            ),
            "ir_frames": {snapshot.label: snapshot.reason for snapshot in frame_snapshots},
            "live_frame_roles": [
                snapshot.label
                for snapshot in frame_snapshots
                if snapshot.fresh and snapshot.image is not None
            ],
        }

    def _read_frame_source(self, source: IrFrameSource, *, now: float) -> IrStreamSnapshot:
        try:
            stat = source.path.stat()
        except OSError:
            return IrStreamSnapshot(source.label, source.path, {}, 0.0, False, "missing_frame")

        age = max(0.0, now - stat.st_mtime)
        payload: dict[str, Any] = {
            "role": source.label,
            "frame_path": str(source.path),
            "width": source.width,
            "height": source.height,
        }
        if age > self.max_frame_age_s:
            return IrStreamSnapshot(
                source.label,
                source.path,
                payload,
                stat.st_mtime,
                False,
                "stale_frame",
            )

        image = _image_from_bgra_path(source.path, width=source.width, height=source.height)
        if image is None:
            return IrStreamSnapshot(
                source.label,
                source.path,
                payload,
                stat.st_mtime,
                False,
                "malformed_frame",
            )
        payload["ir_brightness"] = float(np.asarray(image, dtype=np.uint8).mean())
        return IrStreamSnapshot(
            source.label,
            source.path,
            payload,
            stat.st_mtime,
            True,
            "fresh_frame",
            image=image,
        )

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
        primary: Image.Image,
        secondary: Image.Image,
        cr: cairo.Context,
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

    def _paint_frame_strip(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        snapshots: list[IrStreamSnapshot],
    ) -> None:
        fresh = [
            snapshot for snapshot in snapshots if snapshot.fresh and snapshot.image is not None
        ]
        if not fresh:
            return
        pad = max(6, canvas_h // 70)
        preview_h = max(28, min(72, canvas_h // 5))
        preview_w = preview_h
        total_w = len(fresh) * preview_w + max(0, len(fresh) - 1) * pad
        x = max(pad, canvas_w - total_w - pad)
        y = pad
        cr.save()
        for snapshot in fresh:
            assert snapshot.image is not None
            luma = _fit_luma(snapshot.image, preview_w, preview_h)
            alpha = np.full((preview_h, preview_w), 255, dtype=np.uint8)
            rgba = np.dstack((luma, luma, luma, alpha))
            surface, _owner = _rgba_to_cairo_surface(rgba)
            cr.set_source_surface(surface, x, y)
            cr.paint_with_alpha(0.86)
            cr.set_source_rgba(0.27, 0.90, 1.0, 0.72)
            cr.rectangle(x + 0.5, y + 0.5, preview_w - 1, preview_h - 1)
            cr.stroke()
            x += preview_w + pad
        cr.restore()

    def _paint_backdrop(self, cr: cairo.Context, canvas_w: int, canvas_h: int, t: float) -> None:
        del cr, canvas_w, canvas_h, t

    def _paint_procedural_pair(
        self,
        cr: cairo.Context,
        primary: IrStreamSnapshot,
        secondary: IrStreamSnapshot,
        canvas_w: int,
        canvas_h: int,
        t: float,
    ) -> None:
        pal = _cbip_palette()
        motion = max(primary.motion_delta, secondary.motion_delta)
        brightness_a = min(1.0, primary.brightness / 255.0)
        brightness_b = min(1.0, secondary.brightness / 255.0)
        disparity = max(-1.0, min(1.0, brightness_a - brightness_b))
        rows = 18
        cols = 28
        cell_w = canvas_w / cols
        cell_h = canvas_h / rows
        warp = disparity * cell_w * 0.75
        if pal:
            pr_r, pr_g, pr_b, _pr_a = pal["accent_red"]
            sc_r, sc_g, sc_b, _sc_a = pal["accent_cyan"]
        else:
            pr_r, pr_g, pr_b = 0.85, 0.12, 0.08
            sc_r, sc_g, sc_b = 0.04, 0.78, 0.72
        for row in range(rows):
            y = row * cell_h
            for col in range(cols):
                x = col * cell_w
                drift = math.sin(t * 0.4 + row * 0.55 + col * 0.12) * warp
                pulse = 0.16 + 0.28 * min(1.0, motion * 12.0)
                cr.set_source_rgba(pr_r, pr_g, pr_b, pulse * (0.45 + brightness_a * 0.55))
                cr.rectangle(x + drift, y, cell_w * 0.46, cell_h * 0.76)
                cr.fill()
                cr.set_source_rgba(sc_r, sc_g, sc_b, pulse * (0.45 + brightness_b * 0.55))
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

    def _paint_offline(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> None:
        del cr, canvas_w, canvas_h

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
        pal = _cbip_palette()
        cr.save()
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(max(10.0, min(16.0, canvas_h * 0.035)))
        xb, yb, tw, th, _, _ = cr.text_extents(text)
        pad = 6.0
        x = 8.0
        y = canvas_h - 10.0
        if pal:
            sbg_r, sbg_g, sbg_b, _sbg_a = pal["background"]
        else:
            sbg_r, sbg_g, sbg_b = 0.0, 0.0, 0.0
        cr.set_source_rgba(sbg_r, sbg_g, sbg_b, 0.48)
        cr.rectangle(x - pad, y - th - pad + yb, min(tw + pad * 2, canvas_w - 16), th + pad * 2)
        cr.fill()
        if pal:
            st_r, st_g, st_b, _st_a = pal["bright"]
        else:
            st_r, st_g, st_b = 0.72, 0.92, 0.88
        cr.set_source_rgba(st_r, st_g, st_b, 0.92)
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
