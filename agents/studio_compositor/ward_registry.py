"""Ward registry — canonical catalog of livestream-surface wards.

A "ward" is anything painted onto the livestream surface other than the
WGSL effects layer (memory `reference_wards_taxonomy.md`): Cairo overlay
sources (sierpinski, token pole, album cover, captions, hothouse panels),
Pango/markdown overlay zones, PiP camera tiles, and YouTube external_rgba
slots. The registry is the single source of truth for ward IDs the
ward-property-management layer keys against.

The registry is derived once at compositor startup from the active layout
JSON (``config/compositor-layouts/default.json``) plus the static set of
overlay-zone IDs declared in ``overlay_zones.ZONES``. Subsequent layout
swaps trigger a re-derivation.

Naming convention: ward IDs match the ``id`` field of the originating
``SourceSchema`` / ``SurfaceSchema`` / overlay zone config — kebab-case
or snake_case depending on the source's existing convention. Stable
across sessions so SHM-based property overrides keyed by ward_id remain
valid across compositor restarts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.compositor_model import Layout

log = logging.getLogger(__name__)


class WardCategory(StrEnum):
    """Coarse classification used by per-category render decisions."""

    CAIRO = "cairo"
    OVERLAY_ZONE = "overlay_zone"
    EXTERNAL_RGBA = "external_rgba"
    CAMERA_PIP = "camera_pip"
    YOUTUBE_SLOT = "youtube_slot"
    VIDEO_OUT = "video_out"


@dataclass(frozen=True)
class WardMetadata:
    """One entry in the ward registry."""

    ward_id: str
    category: WardCategory
    natural_w: int | None = None
    natural_h: int | None = None
    tags: tuple[str, ...] = ()


_REGISTRY: dict[str, WardMetadata] = {}


def register_ward(meta: WardMetadata) -> None:
    """Insert or overwrite a ward entry."""
    _REGISTRY[meta.ward_id] = meta


def get_ward(ward_id: str) -> WardMetadata | None:
    """Look up a ward by ID. Returns ``None`` if not registered."""
    return _REGISTRY.get(ward_id)


def all_wards() -> dict[str, WardMetadata]:
    """Return a snapshot of the registry (callers may mutate the copy)."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Drop every registered ward. Intended for tests + re-derivation."""
    _REGISTRY.clear()


def populate_from_layout(layout: Layout) -> None:
    """Derive registry entries from a parsed compositor :class:`Layout`.

    Each layout source becomes one ward. Camera/external_rgba sources keep
    their declared ``natural_w`` / ``natural_h`` from the schema params.
    Surfaces of kind ``video_out`` register as a separate VIDEO_OUT entry
    so operators can dim/pause output sinks via the same property layer.
    """
    for src in layout.sources:
        category = _category_for_source_kind(src.kind)
        natural_w = _int_param(src.params, "natural_w")
        natural_h = _int_param(src.params, "natural_h")
        register_ward(
            WardMetadata(
                ward_id=src.id,
                category=category,
                natural_w=natural_w,
                natural_h=natural_h,
                tags=tuple(src.tags),
            )
        )
    for surf in layout.surfaces:
        if surf.geometry.kind != "video_out":
            continue
        register_ward(
            WardMetadata(
                ward_id=surf.id,
                category=WardCategory.VIDEO_OUT,
            )
        )


def populate_overlay_zones(zone_ids: list[str]) -> None:
    """Register per-zone IDs from the OverlayZoneManager configuration.

    Overlay zones are a sub-population of ``OverlayZonesCairoSource`` —
    each zone has its own ID (``main``, ``research``, ``lyrics``) and
    operators may want to address them individually for property
    overrides (dim ``research`` while ``main`` stays foregrounded).
    """
    for zid in zone_ids:
        register_ward(
            WardMetadata(
                ward_id=f"overlay-zone:{zid}",
                category=WardCategory.OVERLAY_ZONE,
            )
        )


def populate_youtube_slots(slot_count: int = 3) -> None:
    """Register YouTube PiP slot IDs (``youtube-slot-0`` …)."""
    for i in range(slot_count):
        register_ward(
            WardMetadata(
                ward_id=f"youtube-slot-{i}",
                category=WardCategory.YOUTUBE_SLOT,
            )
        )


def populate_camera_pips(camera_roles: list[str]) -> None:
    """Register per-camera-role ward IDs (e.g. ``camera-pip:c920-overhead``)."""
    for role in camera_roles:
        register_ward(
            WardMetadata(
                ward_id=f"camera-pip:{role}",
                category=WardCategory.CAMERA_PIP,
            )
        )


def _category_for_source_kind(kind: str) -> WardCategory:
    if kind == "cairo":
        return WardCategory.CAIRO
    if kind == "external_rgba":
        return WardCategory.EXTERNAL_RGBA
    if kind == "camera":
        return WardCategory.CAMERA_PIP
    if kind == "video":
        return WardCategory.YOUTUBE_SLOT
    return WardCategory.CAIRO


def _int_param(params: dict, key: str) -> int | None:
    value = params.get(key)
    if isinstance(value, (int, float)):
        return int(value)
    return None


__all__ = [
    "WardCategory",
    "WardMetadata",
    "register_ward",
    "get_ward",
    "all_wards",
    "clear_registry",
    "populate_from_layout",
    "populate_overlay_zones",
    "populate_youtube_slots",
    "populate_camera_pips",
]
