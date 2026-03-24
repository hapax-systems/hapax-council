"""Patch segmentation — extract coherent spatial units from fortress state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agents.fortress.schema import FullFortressState


class PatchType(StrEnum):
    ROOM = "room"
    ZONE = "zone"
    WORKSHOP = "workshop"
    STOCKPILE = "stockpile"
    CORRIDOR = "corridor"
    CHAMBER = "chamber"
    UNCLAIMED = "unclaimed"


@dataclass(frozen=True)
class Patch:
    patch_id: str
    patch_type: PatchType
    name: str
    z_level: int
    x1: int
    y1: int
    x2: int
    y2: int
    contents: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.x2 - self.x1 + 1

    @property
    def height(self) -> int:
        return self.y2 - self.y1 + 1


def classify_unclaimed(width: int, height: int) -> PatchType:
    """Classify unclaimed space by dimensions."""
    if min(width, height) <= 2:
        return PatchType.CORRIDOR
    return PatchType.CHAMBER


def extract_patches(state: FullFortressState) -> list[Patch]:
    """Extract coherent spatial patches from fortress state."""
    patches: list[Patch] = []

    # Type A: Named rooms
    for bld in state.buildings_list:
        if bld.is_room:
            patches.append(
                Patch(
                    patch_id=f"room-{bld.id}",
                    patch_type=PatchType.ROOM,
                    name=bld.room_description or bld.name or f"Room {bld.id}",
                    z_level=bld.z,
                    x1=bld.x1,
                    y1=bld.y1,
                    x2=bld.x2,
                    y2=bld.y2,
                    contents={"building_type": bld.type, "is_room": True},
                )
            )

    # Type B: Activity zones
    for zone in state.zones:
        patches.append(
            Patch(
                patch_id=f"zone-{zone.id}",
                patch_type=PatchType.ZONE,
                name=zone.name or zone.type,
                z_level=zone.z,
                x1=zone.x1,
                y1=zone.y1,
                x2=zone.x2,
                y2=zone.y2,
                contents={"zone_type": zone.type},
            )
        )

    # Type C: Workshops
    for i, ws in enumerate(state.workshops):
        patches.append(
            Patch(
                patch_id=f"workshop-{i}",
                patch_type=PatchType.WORKSHOP,
                name=ws.type,
                z_level=ws.z,
                x1=ws.x,
                y1=ws.y,
                x2=ws.x + 2,
                y2=ws.y + 2,  # workshops are 3x3
                contents={
                    "workshop_type": ws.type,
                    "is_active": ws.is_active,
                    "current_job": ws.current_job,
                },
            )
        )

    return patches


def describe_patch(patch: Patch, state: FullFortressState) -> str:
    """Generate natural-language description of a patch."""
    parts: list[str] = []

    if patch.patch_type == PatchType.ROOM:
        parts.append(f"{patch.name} on z-level {patch.z_level}")
        parts.append(f"({patch.width}x{patch.height} tiles)")

    elif patch.patch_type == PatchType.ZONE:
        zone_type = patch.contents.get("zone_type", "zone")
        parts.append(f"{zone_type.title()} '{patch.name}' on z-level {patch.z_level}")

    elif patch.patch_type == PatchType.WORKSHOP:
        ws_type = patch.contents.get("workshop_type", "workshop")
        is_active = patch.contents.get("is_active", False)
        job = patch.contents.get("current_job", "idle")
        status = f"working on {job}" if is_active else "idle"
        parts.append(f"{ws_type} workshop on z-level {patch.z_level}, {status}")

    elif patch.patch_type in (PatchType.CORRIDOR, PatchType.CHAMBER):
        parts.append(f"{patch.patch_type.value.title()} on z-level {patch.z_level}")
        parts.append(f"({patch.width}x{patch.height} tiles)")

    return ". ".join(parts) + "." if parts else "Empty patch."
