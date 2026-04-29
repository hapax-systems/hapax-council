"""Mobile portrait layout schema and source-selection helpers.

The mobile substream layout is deliberately separate from
``shared.compositor_model.Layout``. It describes a 9:16 egress crop and
mobile-only Cairo bands, not the source-registry surface graph used by
the desktop compositor.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MOBILE_WIDTH = 1080
MOBILE_HEIGHT = 1920
MIN_MOBILE_FONT_SIZE_PT = 18
DEFAULT_MOBILE_LAYOUT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "mobile.json"
)

DensityMode = Literal["normal_density", "minimum_density"]
ClaimPosture = Literal["neutral_hold"]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class HeroCamLayout:
    source: str
    source_crop: Rect
    dest: Rect


@dataclass(frozen=True)
class WardZoneLayout:
    y_top: int
    y_bottom: int
    max_wards: int
    ward_height: int
    padding_px: int
    fallback_density: DensityMode


@dataclass(frozen=True)
class MetadataFooterLayout:
    y_top: int
    y_bottom: int
    font_size_pt: int
    claim_posture: ClaimPosture


@dataclass(frozen=True)
class MobileLayout:
    version: int
    target_width: int
    target_height: int
    hero_cam: HeroCamLayout
    ward_zone: WardZoneLayout
    metadata_footer: MetadataFooterLayout
    salience_sources: tuple[Path, ...]
    ward_candidates: tuple[str, ...]


@dataclass(frozen=True)
class MobileSourceSelection:
    hero_source: str
    selected_wards: tuple[str, ...]
    density_mode: DensityMode
    claim_posture: ClaimPosture
    stale: bool


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"mobile layout {name} must be an object")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"mobile layout {name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"mobile layout {name} must be a non-negative integer")
    return value


def _rect(data: Any, name: str) -> Rect:
    raw = _require_dict(data, name)
    return Rect(
        x=_nonnegative_int(raw.get("x"), f"{name}.x"),
        y=_nonnegative_int(raw.get("y"), f"{name}.y"),
        width=_positive_int(raw.get("width"), f"{name}.width"),
        height=_positive_int(raw.get("height"), f"{name}.height"),
    )


def _validate_rect_inside(rect: Rect, width: int, height: int, name: str) -> None:
    if rect.x + rect.width > width or rect.y + rect.height > height:
        raise ValueError(f"mobile layout {name} exceeds {width}x{height} target")


def load_mobile_layout(path: Path | None = None) -> MobileLayout:
    """Load and validate the mobile 9:16 layout JSON."""

    layout_path = Path(path) if path is not None else DEFAULT_MOBILE_LAYOUT_PATH
    data = json.loads(layout_path.read_text(encoding="utf-8"))
    raw = _require_dict(data, "root")
    version = _positive_int(raw.get("version"), "version")
    if version != 1:
        raise ValueError(f"unsupported mobile layout version: {version}")
    target_width = _positive_int(raw.get("target_width"), "target_width")
    target_height = _positive_int(raw.get("target_height"), "target_height")
    if (target_width, target_height) != (MOBILE_WIDTH, MOBILE_HEIGHT):
        raise ValueError("mobile layout target must be 1080x1920")

    hero_raw = _require_dict(raw.get("hero_cam"), "hero_cam")
    hero = HeroCamLayout(
        source=str(hero_raw.get("source") or "compositor_main"),
        source_crop=_rect(hero_raw.get("source_crop"), "hero_cam.source_crop"),
        dest=_rect(hero_raw.get("dest"), "hero_cam.dest"),
    )
    _validate_rect_inside(hero.dest, target_width, target_height, "hero_cam.dest")

    ward_raw = _require_dict(raw.get("ward_zone"), "ward_zone")
    fallback_density = str(ward_raw.get("fallback_density") or "minimum_density")
    if fallback_density not in ("normal_density", "minimum_density"):
        raise ValueError("mobile layout ward_zone.fallback_density has invalid value")
    ward_zone = WardZoneLayout(
        y_top=_nonnegative_int(ward_raw.get("y_top"), "ward_zone.y_top"),
        y_bottom=_positive_int(ward_raw.get("y_bottom"), "ward_zone.y_bottom"),
        max_wards=_positive_int(ward_raw.get("max_wards"), "ward_zone.max_wards"),
        ward_height=_positive_int(ward_raw.get("ward_height"), "ward_zone.ward_height"),
        padding_px=_nonnegative_int(ward_raw.get("padding_px"), "ward_zone.padding_px"),
        fallback_density=fallback_density,  # type: ignore[arg-type]
    )
    if not (0 <= ward_zone.y_top < ward_zone.y_bottom <= target_height):
        raise ValueError("mobile layout ward_zone y range is invalid")
    ward_capacity = ward_zone.max_wards * ward_zone.ward_height
    if ward_capacity > (ward_zone.y_bottom - ward_zone.y_top):
        raise ValueError("mobile layout ward_zone cannot fit max_wards * ward_height")

    footer_raw = _require_dict(raw.get("metadata_footer"), "metadata_footer")
    claim_posture = str(footer_raw.get("claim_posture") or "neutral_hold")
    if claim_posture != "neutral_hold":
        raise ValueError("mobile layout metadata_footer.claim_posture must be neutral_hold")
    metadata_footer = MetadataFooterLayout(
        y_top=_nonnegative_int(footer_raw.get("y_top"), "metadata_footer.y_top"),
        y_bottom=_positive_int(footer_raw.get("y_bottom"), "metadata_footer.y_bottom"),
        font_size_pt=_positive_int(footer_raw.get("font_size_pt"), "metadata_footer.font_size_pt"),
        claim_posture="neutral_hold",
    )
    if metadata_footer.font_size_pt < MIN_MOBILE_FONT_SIZE_PT:
        raise ValueError("mobile footer font size must be >= 18pt")
    if not (
        ward_zone.y_bottom <= metadata_footer.y_top < metadata_footer.y_bottom <= target_height
    ):
        raise ValueError("mobile metadata_footer y range is invalid")

    salience_sources = raw.get("salience_sources")
    if not isinstance(salience_sources, list) or not salience_sources:
        raise ValueError("mobile layout salience_sources must be a non-empty list")
    ward_candidates = raw.get("ward_candidates")
    if not isinstance(ward_candidates, list) or not ward_candidates:
        raise ValueError("mobile layout ward_candidates must be a non-empty list")
    candidates = tuple(str(item) for item in ward_candidates if str(item))
    if len(set(candidates)) != len(candidates):
        raise ValueError("mobile layout ward_candidates must be unique")

    return MobileLayout(
        version=version,
        target_width=target_width,
        target_height=target_height,
        hero_cam=hero,
        ward_zone=ward_zone,
        metadata_footer=metadata_footer,
        salience_sources=tuple(Path(str(item)) for item in salience_sources),
        ward_candidates=candidates,
    )


def select_mobile_sources(
    layout: MobileLayout,
    salience: dict[str, Any] | None,
    *,
    now: float | None = None,
    max_age_s: float = 30.0,
) -> MobileSourceSelection:
    """Return the mobile source routing decision for the current salience state.

    Missing or stale salience fails closed to ``minimum_density`` and
    ``neutral_hold``. That keeps the mobile leg from implying live control,
    viewer claims, or public-reach changes when the selector is silent.
    """

    current = time.time() if now is None else now
    raw = salience if isinstance(salience, dict) else {}
    ts = raw.get("ts")
    try:
        stale = ts is None or (current - float(ts)) > max_age_s
    except (TypeError, ValueError):
        stale = True

    if stale:
        return MobileSourceSelection(
            hero_source=layout.hero_cam.source,
            selected_wards=(),
            density_mode=layout.ward_zone.fallback_density,
            claim_posture=layout.metadata_footer.claim_posture,
            stale=True,
        )

    candidates = set(layout.ward_candidates)
    selected: list[str] = []
    raw_wards = raw.get("selected_wards")
    if isinstance(raw_wards, list):
        for item in raw_wards:
            ward = str(item)
            if ward in candidates and ward not in selected:
                selected.append(ward)
            if len(selected) >= layout.ward_zone.max_wards:
                break

    return MobileSourceSelection(
        hero_source=layout.hero_cam.source,
        selected_wards=tuple(selected),
        density_mode="normal_density" if selected else layout.ward_zone.fallback_density,
        claim_posture=layout.metadata_footer.claim_posture,
        stale=False,
    )
