"""Tests for observation tools."""

from __future__ import annotations

import unittest

from agents.fortress.attention import AttentionBudget, AttentionTier
from agents.fortress.observation import (
    check_announcements,
    check_stockpile,
    describe_patch_tool,
    examine_dwarf,
    observe_region,
    scan_threats,
    survey_floor,
)
from agents.fortress.schema import (
    Building,
    BuildingSummary,
    DwarfSkill,
    DwarfUnit,
    FullFortressState,
    SiegeEvent,
    StockpileSummary,
    WealthSummary,
    Workshop,
)
from agents.fortress.spatial_memory import SpatialMemoryStore


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


class TestObserveRegion(unittest.TestCase):
    def test_returns_description(self) -> None:
        ws = Workshop(type="Mason", x=5, y=5, z=0, is_active=True, current_job="blocks")
        state = _base_full(workshops=(ws,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = observe_region(state, memory, budget, center_x=5, center_y=5, z=0)
        assert len(result) > 0
        assert "Mason" in result

    def test_updates_memory(self) -> None:
        ws = Workshop(type="Mason", x=5, y=5, z=0, is_active=True, current_job="blocks")
        state = _base_full(workshops=(ws,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        observe_region(state, memory, budget, center_x=5, center_y=5, z=0)
        assert len(memory) > 0

    def test_empty_region(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = observe_region(state, memory, budget, center_x=100, center_y=100, z=99)
        assert "No notable features" in result

    def test_budget_exhaustion(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        # Exhaust routine budget
        while budget.can_spend(AttentionTier.ROUTINE):
            budget.spend(AttentionTier.ROUTINE)
        result = observe_region(state, memory, budget, center_x=0, center_y=0, z=0)
        assert "budget exhausted" in result.lower()


class TestDescribePatchTool(unittest.TestCase):
    def test_known_patch(self) -> None:
        bld = Building(
            id=1,
            type="bedroom",
            x1=0,
            y1=0,
            x2=4,
            y2=4,
            z=0,
            is_room=True,
            room_description="Royal Bedroom",
        )
        state = _base_full(buildings_list=(bld,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = describe_patch_tool(state, memory, budget, "room-1")
        assert "Royal Bedroom" in result

    def test_unknown_patch(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = describe_patch_tool(state, memory, budget, "nonexistent-99")
        assert "not found" in result.lower()


class TestCheckStockpile(unittest.TestCase):
    def test_adequate_stockpile(self) -> None:
        state = _base_full(
            population=10,
            stockpiles=StockpileSummary(food=500),
        )
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = check_stockpile(state, memory, budget, "food")
        assert "adequate" in result

    def test_critical_stockpile(self) -> None:
        state = _base_full(
            population=100,
            stockpiles=StockpileSummary(food=10),
        )
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = check_stockpile(state, memory, budget, "food")
        assert "critical" in result

    def test_unknown_category(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = check_stockpile(state, memory, budget, "unobtanium")
        assert "Unknown" in result


class TestScanThreats(unittest.TestCase):
    def test_no_threats(self) -> None:
        state = _base_full(active_threats=0)
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = scan_threats(state, memory, budget)
        assert "No active threats" in result

    def test_with_threats(self) -> None:
        siege = SiegeEvent(attacker_civ="Goblins", force_size=30)
        state = _base_full(active_threats=1, pending_events=(siege,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = scan_threats(state, memory, budget)
        assert "ALERT" in result
        assert "Goblins" in result

    def test_free_no_budget_cost(self) -> None:
        state = _base_full(active_threats=0)
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        initial = budget.total_remaining
        scan_threats(state, memory, budget)
        assert budget.total_remaining == initial


class TestExamineDwarf(unittest.TestCase):
    def test_found_dwarf(self) -> None:
        unit = DwarfUnit(
            id=42,
            name="Urist McHammer",
            profession="Mason",
            skills=(DwarfSkill(name="Masonry", level=15),),
            stress=50,
            mood="normal",
            current_job="Construct building",
        )
        state = _base_full(units=(unit,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = examine_dwarf(state, memory, budget, unit_id=42)
        assert "Urist McHammer" in result
        assert "Mason" in result
        assert "Masonry" in result

    def test_not_found(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = examine_dwarf(state, memory, budget, unit_id=999)
        assert "not found" in result

    def test_budget_cost(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        initial = budget.remaining(AttentionTier.ROUTINE)
        examine_dwarf(state, memory, budget, unit_id=1)
        assert budget.remaining(AttentionTier.ROUTINE) == initial - 1


class TestSurveyFloor(unittest.TestCase):
    def test_empty_floor(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = survey_floor(state, memory, budget, z_level=0)
        assert "No developed features" in result

    def test_floor_with_features(self) -> None:
        bld = Building(
            id=1,
            type="bedroom",
            x1=0,
            y1=0,
            x2=4,
            y2=4,
            z=0,
            is_room=True,
            room_description="Bedroom",
        )
        ws = Workshop(type="Mason", x=10, y=10, z=0, is_active=False, current_job="idle")
        state = _base_full(buildings_list=(bld,), workshops=(ws,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = survey_floor(state, memory, budget, z_level=0)
        assert "room" in result.lower()
        assert "workshop" in result.lower()

    def test_strategic_budget(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        # Exhaust strategic budget
        while budget.can_spend(AttentionTier.STRATEGIC):
            budget.spend(AttentionTier.STRATEGIC)
        result = survey_floor(state, memory, budget, z_level=0)
        assert "budget exhausted" in result.lower()


class TestCheckAnnouncements(unittest.TestCase):
    def test_no_events(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = check_announcements(state, memory, budget)
        assert "No recent announcements" in result

    def test_with_events(self) -> None:
        siege = SiegeEvent(attacker_civ="Goblins", force_size=30)
        state = _base_full(pending_events=(siege,))
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        result = check_announcements(state, memory, budget)
        assert "[siege]" in result

    def test_free_no_budget_cost(self) -> None:
        state = _base_full()
        memory = SpatialMemoryStore()
        budget = AttentionBudget(population=50)
        initial = budget.total_remaining
        check_announcements(state, memory, budget)
        assert budget.total_remaining == initial


if __name__ == "__main__":
    unittest.main()
