"""AoA/OARB geometry state ward for the Screwm ward atlas."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_PATH = REPO_ROOT / "config" / "screwm-quake-media-mounts.json"


@dataclass(frozen=True)
class AoaOarbContract:
    """Small render-facing projection of the Screwm media mount contract."""

    status: str
    reason: str
    geometry_revision: str
    fit_contract: str
    enclosure_clearance_ratio: float
    inner_void_radius_fill_ratio: float
    physical_radius: float
    leaf_face_edge_units: float
    aoa_parent_edge_units: float
    fractal_face_count: int
    texture_size: tuple[int, int]
    sphere_source_id: str
    atlas_source_id: str


def _mount_by_id(payload: dict[str, Any], mount_id: str) -> dict[str, Any]:
    mounts = payload.get("mounts")
    if not isinstance(mounts, list):
        raise ValueError("media mount contract has no mounts list")
    for mount in mounts:
        if isinstance(mount, dict) and mount.get("id") == mount_id:
            return mount
    raise ValueError(f"media mount contract missing {mount_id}")


def _float_value(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"media mount contract missing {key}")
    return float(value)


def _int_value(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"media mount contract missing {key}")
    return int(value)


def _texture_size(payload: dict[str, Any]) -> tuple[int, int]:
    raw = payload.get("texture_size")
    if not isinstance(raw, list | tuple) or len(raw) != 2:
        raise ValueError("media mount contract missing texture_size")
    return int(raw[0]), int(raw[1])


def load_aoa_oarb_contract(path: Path = DEFAULT_CONTRACT_PATH) -> AoaOarbContract:
    """Load the AoA/OARB values the ward is meant to make visible."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("media mount contract root is not an object")
    sphere = _mount_by_id(payload, "aoa-media-sphere")
    atlas = _mount_by_id(payload, "aoa-fractal-face-atlas")
    return AoaOarbContract(
        status="loaded",
        reason="contract loaded",
        geometry_revision=str(atlas.get("geometry_revision") or ""),
        fit_contract=str(sphere.get("fit_contract") or atlas.get("fit_contract") or ""),
        enclosure_clearance_ratio=_float_value(sphere, "enclosure_clearance_ratio"),
        inner_void_radius_fill_ratio=_float_value(sphere, "inner_void_radius_fill_ratio"),
        physical_radius=_float_value(sphere, "physical_radius"),
        leaf_face_edge_units=_float_value(atlas, "leaf_face_edge_units"),
        aoa_parent_edge_units=_float_value(atlas, "aoa_parent_edge_units"),
        fractal_face_count=_int_value(atlas, "fractal_face_count"),
        texture_size=_texture_size(sphere),
        sphere_source_id=str(sphere.get("source_id") or ""),
        atlas_source_id=str(atlas.get("source_id") or ""),
    )


def _degraded_contract(reason: str) -> AoaOarbContract:
    return AoaOarbContract(
        status="degraded",
        reason=reason,
        geometry_revision="unavailable",
        fit_contract="unavailable",
        enclosure_clearance_ratio=0.0,
        inner_void_radius_fill_ratio=0.0,
        physical_radius=0.0,
        leaf_face_edge_units=0.0,
        aoa_parent_edge_units=0.0,
        fractal_face_count=0,
        texture_size=(0, 0),
        sphere_source_id="unavailable",
        atlas_source_id="unavailable",
    )


def _ellipsize(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _set_rgb(cr: cairo.Context, rgb: tuple[float, float, float], alpha: float = 1.0) -> None:
    cr.set_source_rgba(rgb[0], rgb[1], rgb[2], alpha)


class AoaOarbStateCairoSource(CairoSource):
    """Render the current AoA/OARB fit contract as a first-class ward."""

    def __init__(self, contract_path: str | Path = DEFAULT_CONTRACT_PATH) -> None:
        self.contract_path = Path(contract_path)

    def _load_contract(self) -> AoaOarbContract:
        try:
            return load_aoa_oarb_contract(self.contract_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _degraded_contract(f"{type(exc).__name__}: {exc}")

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del state
        contract = self._load_contract()
        phase = (math.sin(t * 0.8) + 1.0) * 0.5
        w = float(canvas_w)
        h = float(canvas_h)

        cr.save()
        try:
            self._draw_geometry(cr, w, h, contract, phase)
            self._draw_text_panel(cr, w, h, contract)
        finally:
            cr.restore()

    def _draw_geometry(
        self,
        cr: cairo.Context,
        w: float,
        h: float,
        contract: AoaOarbContract,
        phase: float,
    ) -> None:
        side = min(h * 0.78, w * 0.32)
        left = w * 0.055
        top = (h - side) * 0.52
        p_top = (left + side * 0.5, top)
        p_left = (left, top + side)
        p_right = (left + side, top + side)
        center = (left + side * 0.5, top + side * 0.58)
        radius = max(5.0, side * 0.175)

        cr.save()
        cr.set_line_width(3.2)
        _set_rgb(cr, (0.20, 0.92, 1.00), 0.92)
        cr.move_to(*p_top)
        cr.line_to(*p_right)
        cr.line_to(*p_left)
        cr.close_path()
        cr.stroke()

        cr.set_line_width(1.7)
        _set_rgb(cr, (1.0, 0.42, 0.72), 0.62 + phase * 0.22)
        inner = side * 0.18
        cr.move_to(p_top[0], p_top[1] + inner)
        cr.line_to(p_right[0] - inner, p_right[1] - inner * 0.45)
        cr.line_to(p_left[0] + inner, p_left[1] - inner * 0.45)
        cr.close_path()
        cr.stroke()

        fit_ok = (
            contract.status == "loaded"
            and contract.inner_void_radius_fill_ratio == 1.0
            and contract.enclosure_clearance_ratio == 1.0
        )
        _set_rgb(cr, (1.0, 0.68, 0.12) if fit_ok else (1.0, 0.16, 0.24), 0.96)
        cr.set_line_width(2.6)
        cr.arc(center[0], center[1], radius, 0, math.tau)
        cr.stroke()
        _set_rgb(cr, (1.0, 0.68, 0.12) if fit_ok else (1.0, 0.16, 0.24), 0.22)
        cr.arc(center[0], center[1], radius * 0.92, 0, math.tau)
        cr.fill()

        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(12.0)
        _set_rgb(cr, (0.90, 1.0, 0.96), 0.94)
        cr.move_to(left + 4.0, top + side + 17.0)
        cr.show_text("AOA  OARB")
        cr.restore()

    def _draw_text_panel(
        self,
        cr: cairo.Context,
        w: float,
        h: float,
        contract: AoaOarbContract,
    ) -> None:
        x = w * 0.39
        cr.save()
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(20.0)
        _set_rgb(cr, (0.94, 1.0, 0.96), 0.98)
        cr.move_to(x, h * 0.24)
        cr.show_text("AOA / OARB")

        cr.set_font_size(11.0)
        _set_rgb(cr, (0.35, 0.94, 1.0), 0.94)
        cr.move_to(x, h * 0.38)
        cr.show_text(_ellipsize(contract.geometry_revision, 45))

        fit_label = (
            f"FIT {contract.inner_void_radius_fill_ratio:.2f}  "
            f"CLR {contract.enclosure_clearance_ratio:.2f}"
        )
        size_label = (
            f"AOA {contract.aoa_parent_edge_units:.0f}u  OARB R{contract.physical_radius:.0f}u"
        )
        face_label = (
            f"LEAF {contract.leaf_face_edge_units:.2f}u  FACES {contract.fractal_face_count}"
        )
        texture_label = f"TEX {contract.texture_size[0]}x{contract.texture_size[1]}"
        lines = [
            (fit_label, (1.0, 0.70, 0.18)),
            (size_label, (0.76, 1.0, 0.72)),
            (face_label, (0.86, 0.78, 1.0)),
            (texture_label, (0.94, 0.88, 0.72)),
        ]
        y = h * 0.50
        line_step = max(16.0, h * 0.105)
        for text, color in lines:
            cr.set_font_size(13.0)
            _set_rgb(cr, color, 0.95)
            cr.move_to(x, y)
            cr.show_text(text)
            y += line_step

        cr.set_font_size(10.0)
        status_color = (0.25, 1.0, 0.58) if contract.status == "loaded" else (1.0, 0.20, 0.22)
        _set_rgb(cr, status_color, 0.95)
        cr.move_to(x, h * 0.91)
        cr.show_text(_ellipsize(f"{contract.status}: {contract.reason}", 48))
        cr.restore()


__all__ = ["AoaOarbContract", "AoaOarbStateCairoSource", "load_aoa_oarb_contract"]
