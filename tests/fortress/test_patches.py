"""Tests for patch segmentation."""

from __future__ import annotations

import unittest

from agents.fortress.patches import (
    Patch,
    PatchType,
    classify_unclaimed,
    describe_patch,
    extract_patches,
)
from agents.fortress.schema import (
    ActivityZone,
    Building,
    BuildingSummary,
    FullFortressState,
    StockpileSummary,
    WealthSummary,
    Workshop,
)


def _base_full(**overrides: object) -> FullFortressState:
    defaults: dict = {
        "timestamp": 1.0,
        "game_tick": 10000,
        "year": 1,
        "season": 0,
        "month": 0,
        "day": 0,
        "fortress_name": "Boatmurdered",
        "paused": False,
        "population": 50,
        "food_count": 500,
        "drink_count": 250,
        "active_threats": 0,
        "job_queue_length": 10,
        "idle_dwarf_count": 5,
        "most_stressed_value": 0,
        "pending_events": (),
        "stockpiles": StockpileSummary(food=500, drink=250),
        "workshops": (),
        "buildings": BuildingSummary(beds=50),
        "wealth": WealthSummary(created=10000),
    }
    defaults.update(overrides)
    return FullFortressState(**defaults)


class TestClassifyUnclaimed(unittest.TestCase):
    def test_narrow_is_corridor(self) -> None:
        assert classify_unclaimed(1, 10) == PatchType.CORRIDOR

    def test_thin_is_corridor(self) -> None:
        assert classify_unclaimed(20, 2) == PatchType.CORRIDOR

    def test_wide_is_chamber(self) -> None:
        assert classify_unclaimed(5, 5) == PatchType.CHAMBER

    def test_three_by_three_is_chamber(self) -> None:
        assert classify_unclaimed(3, 3) == PatchType.CHAMBER


class TestExtractPatches(unittest.TestCase):
    def test_empty_state(self) -> None:
        state = _base_full()
        patches = extract_patches(state)
        assert patches == []

    def test_buildings_list_rooms(self) -> None:
        bld = Building(
            id=1,
            type="bedroom",
            x1=10,
            y1=10,
            x2=14,
            y2=14,
            z=0,
            is_room=True,
            room_description="Royal Bedroom",
        )
        state = _base_full(buildings_list=(bld,))
        patches = extract_patches(state)
        assert len(patches) == 1
        assert patches[0].patch_type == PatchType.ROOM
        assert patches[0].name == "Royal Bedroom"
        assert patches[0].patch_id == "room-1"

    def test_non_room_building_excluded(self) -> None:
        bld = Building(
            id=2,
            type="wall",
            x1=0,
            y1=0,
            x2=5,
            y2=0,
            z=0,
            is_room=False,
        )
        state = _base_full(buildings_list=(bld,))
        patches = extract_patches(state)
        assert len(patches) == 0

    def test_zones_extracted(self) -> None:
        zone = ActivityZone(
            id=1,
            type="temple",
            x1=0,
            y1=0,
            x2=10,
            y2=10,
            z=-1,
            name="Shrine of Armok",
        )
        state = _base_full(zones=(zone,))
        patches = extract_patches(state)
        assert len(patches) == 1
        assert patches[0].patch_type == PatchType.ZONE
        assert patches[0].name == "Shrine of Armok"

    def test_workshops_extracted(self) -> None:
        ws = Workshop(type="Mason", x=5, y=5, z=0, is_active=True, current_job="make blocks")
        state = _base_full(workshops=(ws,))
        patches = extract_patches(state)
        assert len(patches) == 1
        assert patches[0].patch_type == PatchType.WORKSHOP
        assert patches[0].x2 == 7  # 3x3

    def test_mixed_sources(self) -> None:
        bld = Building(
            id=1,
            type="dining",
            x1=0,
            y1=0,
            x2=5,
            y2=5,
            z=0,
            is_room=True,
            room_description="Great Hall",
        )
        zone = ActivityZone(id=1, type="tavern", x1=6, y1=0, x2=12, y2=6, z=0, name="Pub")
        ws = Workshop(type="Carpenter", x=15, y=15, z=0, is_active=False, current_job="idle")
        state = _base_full(buildings_list=(bld,), zones=(zone,), workshops=(ws,))
        patches = extract_patches(state)
        assert len(patches) == 3


class TestDescribePatch(unittest.TestCase):
    def test_room_description(self) -> None:
        state = _base_full()
        patch = Patch(
            patch_id="room-1",
            patch_type=PatchType.ROOM,
            name="Grand Hall",
            z_level=0,
            x1=0,
            y1=0,
            x2=9,
            y2=9,
        )
        desc = describe_patch(patch, state)
        assert "Grand Hall" in desc
        assert "z-level 0" in desc
        assert "10x10" in desc

    def test_zone_description(self) -> None:
        state = _base_full()
        patch = Patch(
            patch_id="zone-1",
            patch_type=PatchType.ZONE,
            name="Temple",
            z_level=-2,
            x1=0,
            y1=0,
            x2=5,
            y2=5,
            contents={"zone_type": "temple"},
        )
        desc = describe_patch(patch, state)
        assert "Temple" in desc
        assert "z-level -2" in desc

    def test_workshop_idle(self) -> None:
        state = _base_full()
        patch = Patch(
            patch_id="workshop-0",
            patch_type=PatchType.WORKSHOP,
            name="Mason",
            z_level=0,
            x1=0,
            y1=0,
            x2=2,
            y2=2,
            contents={"workshop_type": "Mason", "is_active": False, "current_job": "idle"},
        )
        desc = describe_patch(patch, state)
        assert "idle" in desc

    def test_workshop_active(self) -> None:
        state = _base_full()
        patch = Patch(
            patch_id="workshop-0",
            patch_type=PatchType.WORKSHOP,
            name="Mason",
            z_level=0,
            x1=0,
            y1=0,
            x2=2,
            y2=2,
            contents={"workshop_type": "Mason", "is_active": True, "current_job": "blocks"},
        )
        desc = describe_patch(patch, state)
        assert "working on blocks" in desc

    def test_corridor_description(self) -> None:
        state = _base_full()
        patch = Patch(
            patch_id="corr-1",
            patch_type=PatchType.CORRIDOR,
            name="hallway",
            z_level=0,
            x1=0,
            y1=0,
            x2=9,
            y2=1,
        )
        desc = describe_patch(patch, state)
        assert "Corridor" in desc

    def test_empty_patch(self) -> None:
        state = _base_full()
        patch = Patch(
            patch_id="unk-1",
            patch_type=PatchType.UNCLAIMED,
            name="",
            z_level=0,
            x1=0,
            y1=0,
            x2=0,
            y2=0,
        )
        desc = describe_patch(patch, state)
        assert desc == "Empty patch."


class TestPatchProperties(unittest.TestCase):
    def test_width_height(self) -> None:
        patch = Patch(
            patch_id="t",
            patch_type=PatchType.ROOM,
            name="t",
            z_level=0,
            x1=3,
            y1=5,
            x2=7,
            y2=10,
        )
        assert patch.width == 5
        assert patch.height == 6


if __name__ == "__main__":
    unittest.main()
