"""Layout safety contract for live compositor camera geometry.

This module keeps the live-layout rules near the geometry code but away
from GStreamer.  It answers a narrow question: is this camera tile layout
selectable for live egress, and if it leaves dark space, is that space
declared as deliberate material rather than accidental fallthrough?
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import CameraSpec, TileRect

BASE_COMPOSITOR_MATERIAL = "matte_black_studio_depth"
BASE_COMPOSITOR_BACKGROUND_PROPERTY_VALUE = 1
WARM_LIGHT_CALIBRATION_TARGET = (
    "preserve the studio's warm orange-yellow ambience; do not classify it "
    "as white-balance error unless focus or skin/object detail is lost"
)

DEFAULT_STARTUP_LAYOUT_MODE = "balanced"
STARTUP_LAYOUT_MODE_ENV = "HAPAX_COMPOSITOR_LAYOUT_MODE"
STARTUP_DEFAULT_MODE_ENV = "HAPAX_COMPOSITOR_DEFAULT_LAYOUT_MODE"
STARTUP_PERSIST_PATH_ENV = "HAPAX_COMPOSITOR_LAYOUT_MODE_PERSIST"
DEFAULT_STARTUP_PERSIST_PATH = (
    Path.home() / ".cache" / "hapax-compositor" / ("layout-mode-persist.txt")
)

MAX_HERO_UPSCALE = 1.0
MIN_VISIBLE_TILE_AREA_PX = 16


class LayoutSafetyError(ValueError):
    """Raised when a requested layout mode violates the live safety contract."""


@dataclass(frozen=True)
class NegativeSpaceContract:
    intent: str
    region: str
    material: str
    expected_visual_signature: str
    max_fraction: float


@dataclass(frozen=True)
class LayerBudget:
    layer: str
    max_active: int
    note: str


@dataclass(frozen=True)
class LayoutSafetyReport:
    mode: str
    family: str
    canvas_w: int
    canvas_h: int
    content_area_fraction: float
    dark_area_fraction: float
    content_regions: int
    quadrant_weights: Mapping[str, float]
    visible_rgb_roles: tuple[str, ...]
    visible_ir_roles: tuple[str, ...]
    hidden_roles: tuple[str, ...]
    negative_space: NegativeSpaceContract | None
    dark_space_interpretation: str
    violations: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class StartupLayoutMode:
    mode: str
    source: str
    path: Path | None = None


LAYER_BUDGETS: tuple[LayerBudget, ...] = (
    LayerBudget("cameras", 9, "RGB plus IR tiles must fit without hiding required roles."),
    LayerBudget("wards", 12, "Cairo wards remain bounded so overlays do not bury source truth."),
    LayerBudget("fx", 1, "One inline FX chain; topology churn is not a layout primitive."),
    LayerBudget("overlays", 4, "Operator-readable chrome must not occlude camera proof regions."),
)


_NEGATIVE_SPACE_BY_FAMILY: dict[str, NegativeSpaceContract] = {
    "balanced": NegativeSpaceContract(
        intent="16:9 camera gutters and equal-grid rhythm",
        region="between fitted camera tiles",
        material=BASE_COMPOSITOR_MATERIAL,
        expected_visual_signature="stable non-transparent matte black around live camera regions",
        max_fraction=0.60,
    ),
    "hero": NegativeSpaceContract(
        intent="hero framing gutters and secondary stack separation",
        region="hero/stack gutters",
        material=BASE_COMPOSITOR_MATERIAL,
        expected_visual_signature="stable non-transparent matte black, never checkerboard",
        max_fraction=0.52,
    ),
    "follow": NegativeSpaceContract(
        intent="follow-mode salience inside balanced posture",
        region="hero/stack gutters",
        material=BASE_COMPOSITOR_MATERIAL,
        expected_visual_signature="stable non-transparent matte black, never checkerboard",
        max_fraction=0.60,
    ),
    "packed": NegativeSpaceContract(
        intent="operator-declared containment constellation",
        region="open canvas outside camera constellation",
        material=BASE_COMPOSITOR_MATERIAL,
        expected_visual_signature="stable matte black field surrounding deliberately small tiles",
        max_fraction=0.86,
    ),
    "forcefield": NegativeSpaceContract(
        intent="Arnheim force-field composition with open center",
        region="negative field between distributed camera mass-points",
        material=BASE_COMPOSITOR_MATERIAL,
        expected_visual_signature="stable matte black spatial field with distributed live tiles",
        max_fraction=0.90,
    ),
    "sierpinski": NegativeSpaceContract(
        intent="fractal-mask camera constellation",
        region="triangle exterior and recursive voids",
        material=BASE_COMPOSITOR_MATERIAL,
        expected_visual_signature="stable matte black field around three live fitted tiles",
        max_fraction=0.96,
    ),
}


def mode_family(mode: str) -> str:
    normalized = mode.strip()
    if normalized.startswith("hero/"):
        return "hero"
    if normalized.startswith("packed/"):
        return "packed"
    if normalized.startswith("follow/"):
        return "follow"
    if normalized in {"balanced", "packed", "forcefield", "sierpinski"}:
        return normalized
    return "unknown"


def is_known_layout_mode(mode: str) -> bool:
    family = mode_family(mode)
    if family == "unknown":
        return False
    if family in {"hero", "packed", "follow"}:
        return bool(mode.split("/", 1)[1].strip())
    return True


def resolve_startup_layout_mode(
    *,
    env: Mapping[str, str] | None = None,
    persist_path: Path | None = None,
) -> StartupLayoutMode:
    """Resolve startup layout mode without consulting /dev/shm.

    Explicit environment wins, then persisted operator choice, then the
    configured default.  Invalid persisted data is ignored as stale state;
    invalid explicit environment fails closed.
    """

    values = os.environ if env is None else env
    explicit = values.get(STARTUP_LAYOUT_MODE_ENV)
    if explicit is not None:
        mode = explicit.strip()
        if not is_known_layout_mode(mode):
            raise LayoutSafetyError(
                f"{STARTUP_LAYOUT_MODE_ENV}={mode!r} is not a selectable layout mode"
            )
        return StartupLayoutMode(mode=mode, source="env")

    resolved_persist = persist_path
    if resolved_persist is None:
        raw_path = values.get(STARTUP_PERSIST_PATH_ENV)
        resolved_persist = Path(raw_path) if raw_path else DEFAULT_STARTUP_PERSIST_PATH

    try:
        persisted = resolved_persist.read_text(encoding="utf-8").strip()
    except OSError:
        persisted = ""
    if persisted and is_known_layout_mode(persisted):
        return StartupLayoutMode(mode=persisted, source="persisted", path=resolved_persist)

    default = values.get(STARTUP_DEFAULT_MODE_ENV, DEFAULT_STARTUP_LAYOUT_MODE).strip()
    if not is_known_layout_mode(default):
        raise LayoutSafetyError(
            f"{STARTUP_DEFAULT_MODE_ENV}={default!r} is not a selectable layout mode"
        )
    return StartupLayoutMode(mode=default, source="default", path=resolved_persist)


def validate_tile_layout(
    cameras: list[CameraSpec],
    tiles: Mapping[str, TileRect],
    *,
    mode: str,
    canvas_w: int,
    canvas_h: int,
    allow_low_resolution_hero_waiver: bool = False,
    allow_ir_hero_waiver: bool = False,
) -> LayoutSafetyReport:
    family = mode_family(mode)
    violations: list[str] = []
    warnings: list[str] = []

    if family == "unknown":
        violations.append(f"unknown_layout_mode:{mode}")

    camera_by_role = {camera.role: camera for camera in cameras}
    visible_roles: list[str] = []
    hidden_roles: list[str] = []
    rects: list[tuple[str, TileRect]] = []

    for role in camera_by_role:
        tile = tiles.get(role)
        if tile is None:
            hidden_roles.append(role)
            continue
        if _is_visible_tile(tile):
            visible_roles.append(role)
            rects.append((role, tile))
        else:
            hidden_roles.append(role)

    if not rects:
        violations.append("no_visible_camera_regions")

    for role, tile in rects:
        if tile.x < 0 or tile.y < 0:
            violations.append(f"tile_off_canvas:{role}")
        if tile.w <= 0 or tile.h <= 0:
            violations.append(f"tile_non_positive:{role}")
        if tile.x + tile.w > canvas_w or tile.y + tile.h > canvas_h:
            violations.append(f"tile_exceeds_canvas:{role}")

    content_fraction = _union_area_fraction([tile for _, tile in rects], canvas_w, canvas_h)
    dark_fraction = max(0.0, 1.0 - content_fraction)
    negative_space = _NEGATIVE_SPACE_BY_FAMILY.get(family)
    if negative_space is None and dark_fraction > 0.08:
        violations.append(f"unclassified_dark_area:{dark_fraction:.3f}")
    elif negative_space is not None and dark_fraction > negative_space.max_fraction:
        violations.append(
            f"negative_space_exceeds_contract:{dark_fraction:.3f}>{negative_space.max_fraction:.3f}"
        )

    hero_role = _hero_role_for_mode(mode, cameras)
    if hero_role:
        hero_camera = camera_by_role.get(hero_role)
        hero_tile = tiles.get(hero_role)
        if hero_camera is None:
            violations.append(f"hero_role_unknown:{hero_role}")
        elif hero_tile is not None and _is_visible_tile(hero_tile):
            scale = max(hero_tile.w / hero_camera.width, hero_tile.h / hero_camera.height)
            if scale > MAX_HERO_UPSCALE and not allow_low_resolution_hero_waiver:
                violations.append(f"hero_source_upscale_exceeds_budget:{hero_role}:{scale:.2f}")
            if is_ir_camera(hero_camera) and not allow_ir_hero_waiver:
                violations.append(f"ir_hero_requires_waiver:{hero_role}")

    if family == "follow" and mode.startswith("packed/"):
        violations.append("follow_mode_must_not_use_packed_repin")

    visible_ir = tuple(role for role in visible_roles if is_ir_camera(camera_by_role[role]))
    visible_rgb = tuple(role for role in visible_roles if role not in visible_ir)
    if visible_ir and family == "packed":
        warnings.append("ir_tiles_in_packed_mode_require_rotation_review")

    return LayoutSafetyReport(
        mode=mode,
        family=family,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        content_area_fraction=content_fraction,
        dark_area_fraction=dark_fraction,
        content_regions=len(rects),
        quadrant_weights=_quadrant_weights(rects, canvas_w, canvas_h),
        visible_rgb_roles=tuple(sorted(visible_rgb)),
        visible_ir_roles=tuple(sorted(visible_ir)),
        hidden_roles=tuple(sorted(hidden_roles)),
        negative_space=negative_space,
        dark_space_interpretation=(
            "intentional_negative_space" if negative_space is not None else "unclassified"
        ),
        violations=tuple(violations),
        warnings=tuple(warnings),
    )


def require_safe_tile_layout(report: LayoutSafetyReport) -> None:
    if report.violations:
        raise LayoutSafetyError(
            f"layout mode {report.mode!r} violates live safety contract: "
            + ", ".join(report.violations)
        )


def is_ir_camera(camera: CameraSpec) -> bool:
    haystack = " ".join(
        [
            camera.role,
            camera.semantic_role,
            camera.angle,
            " ".join(camera.subject_ontology),
        ]
    ).lower()
    return "ir" in haystack or "noir" in haystack or "thermal" in haystack


def _hero_role_for_mode(mode: str, cameras: list[CameraSpec]) -> str | None:
    family = mode_family(mode)
    if family in {"hero", "packed", "follow"} and "/" in mode:
        return mode.split("/", 1)[1].strip() or None
    heroes = [camera.role for camera in cameras if camera.hero]
    return heroes[0] if heroes else None


def _is_visible_tile(tile: TileRect) -> bool:
    return (
        tile.w * tile.h >= MIN_VISIBLE_TILE_AREA_PX and tile.x + tile.w > 0 and tile.y + tile.h > 0
    )


def _union_area_fraction(tiles: list[TileRect], canvas_w: int, canvas_h: int) -> float:
    if not tiles or canvas_w <= 0 or canvas_h <= 0:
        return 0.0
    xs = {0, canvas_w}
    clipped: list[tuple[int, int, int, int]] = []
    for tile in tiles:
        x1 = max(0, min(canvas_w, tile.x))
        y1 = max(0, min(canvas_h, tile.y))
        x2 = max(0, min(canvas_w, tile.x + tile.w))
        y2 = max(0, min(canvas_h, tile.y + tile.h))
        if x2 <= x1 or y2 <= y1:
            continue
        clipped.append((x1, y1, x2, y2))
        xs.add(x1)
        xs.add(x2)
    if not clipped:
        return 0.0
    x_points = sorted(xs)
    area = 0
    for left, right in zip(x_points, x_points[1:], strict=False):
        if right <= left:
            continue
        intervals = [(y1, y2) for x1, y1, x2, y2 in clipped if x1 < right and x2 > left]
        if not intervals:
            continue
        intervals.sort()
        merged: list[tuple[int, int]] = []
        for y1, y2 in intervals:
            if not merged or y1 > merged[-1][1]:
                merged.append((y1, y2))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], y2))
        covered_y = sum(y2 - y1 for y1, y2 in merged)
        area += (right - left) * covered_y
    return area / float(canvas_w * canvas_h)


def _quadrant_weights(
    rects: list[tuple[str, TileRect]], canvas_w: int, canvas_h: int
) -> dict[str, float]:
    quadrants = {
        "LT": (0, 0, canvas_w // 2, canvas_h // 2),
        "RT": (canvas_w // 2, 0, canvas_w, canvas_h // 2),
        "LB": (0, canvas_h // 2, canvas_w // 2, canvas_h),
        "RB": (canvas_w // 2, canvas_h // 2, canvas_w, canvas_h),
    }
    total_area = sum(max(0, tile.w) * max(0, tile.h) for _, tile in rects)
    if total_area <= 0:
        return {name: 0.0 for name in quadrants}
    out: dict[str, float] = {}
    for name, (qx1, qy1, qx2, qy2) in quadrants.items():
        area = 0
        for _, tile in rects:
            x1 = max(qx1, tile.x)
            y1 = max(qy1, tile.y)
            x2 = min(qx2, tile.x + tile.w)
            y2 = min(qy2, tile.y + tile.h)
            if x2 > x1 and y2 > y1:
                area += (x2 - x1) * (y2 - y1)
        out[name] = area / total_area
    return out
