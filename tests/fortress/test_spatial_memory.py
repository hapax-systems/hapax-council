"""Tests for spatial memory with ACT-R activation decay."""

from __future__ import annotations

import math
import unittest

from agents.fortress.config import PerceptionConfig
from agents.fortress.spatial_memory import (
    TICKS_PER_DAY,
    EntityMobility,
    MemoryState,
    SpatialMemory,
    SpatialMemoryStore,
    memory_state,
)


class TestActivation(unittest.TestCase):
    def test_single_recent_observation(self) -> None:
        mem = SpatialMemory(
            patch_id="room-1",
            last_observation="A room",
            observation_ticks=[1000],
        )
        # At tick 1001, delta=1/1200, so delta^(-0.5) = sqrt(1200)
        act = mem.activation(1001)
        assert act > 0  # recent observation should be positive

    def test_no_observations_negative_inf(self) -> None:
        mem = SpatialMemory(patch_id="room-1", last_observation="A room")
        act = mem.activation(1000)
        assert act == float("-inf")

    def test_multiple_observations_higher(self) -> None:
        mem_single = SpatialMemory(
            patch_id="a",
            last_observation="x",
            observation_ticks=[1000],
        )
        mem_multi = SpatialMemory(
            patch_id="b",
            last_observation="x",
            observation_ticks=[800, 900, 1000],
        )
        assert mem_multi.activation(1001) > mem_single.activation(1001)

    def test_activation_decays_over_time(self) -> None:
        mem = SpatialMemory(
            patch_id="room-1",
            last_observation="A room",
            observation_ticks=[1000],
        )
        act_soon = mem.activation(1010)
        act_later = mem.activation(1000 + TICKS_PER_DAY * 10)
        assert act_soon > act_later

    def test_activation_math_exact(self) -> None:
        """Verify BLA formula: ln(sum(delta^(-d)))."""
        mem = SpatialMemory(
            patch_id="x",
            last_observation="x",
            observation_ticks=[0],
        )
        current = TICKS_PER_DAY  # delta = 1.0 day
        act = mem.activation(current, d=0.5)
        expected = math.log(1.0 ** (-0.5))  # ln(1) = 0
        assert abs(act - expected) < 1e-6


class TestConfidence(unittest.TestCase):
    def test_recent_high_confidence(self) -> None:
        mem = SpatialMemory(
            patch_id="r",
            last_observation="x",
            observation_ticks=[1000],
            entity_mobility=EntityMobility.STATIC,
        )
        conf = mem.confidence(1001)
        assert conf > 0.5

    def test_fast_mobility_lower_confidence(self) -> None:
        ticks = [1000]
        mem_static = SpatialMemory(
            patch_id="a",
            last_observation="x",
            observation_ticks=list(ticks),
            entity_mobility=EntityMobility.STATIC,
        )
        mem_fast = SpatialMemory(
            patch_id="b",
            last_observation="x",
            observation_ticks=list(ticks),
            entity_mobility=EntityMobility.FAST,
        )
        assert mem_static.confidence(1010) > mem_fast.confidence(1010)

    def test_confidence_bounded(self) -> None:
        mem = SpatialMemory(
            patch_id="r",
            last_observation="x",
            observation_ticks=[1000],
        )
        conf = mem.confidence(1001)
        assert 0 <= conf <= 1


class TestMemoryState(unittest.TestCase):
    def test_impression(self) -> None:
        cfg = PerceptionConfig()
        assert memory_state(1.0, cfg) == MemoryState.IMPRESSION

    def test_retention(self) -> None:
        cfg = PerceptionConfig()
        assert memory_state(-0.5, cfg) == MemoryState.RETENTION

    def test_forgotten(self) -> None:
        cfg = PerceptionConfig()
        assert memory_state(-5.0, cfg) == MemoryState.FORGOTTEN


class TestSpatialMemoryStore(unittest.TestCase):
    def test_observe_and_recall(self) -> None:
        store = SpatialMemoryStore()
        store.observe("room-1", "A nice room", 1000)
        state, desc = store.recall("room-1", 1001)
        assert state != MemoryState.FORGOTTEN
        assert desc == "A nice room"

    def test_recall_unknown_patch(self) -> None:
        store = SpatialMemoryStore()
        state, desc = store.recall("nonexistent", 1000)
        assert state == MemoryState.FORGOTTEN
        assert desc is None

    def test_observe_updates_description(self) -> None:
        store = SpatialMemoryStore()
        store.observe("room-1", "Old description", 1000)
        store.observe("room-1", "New description", 2000)
        state, desc = store.recall("room-1", 2001)
        assert desc == "New description"

    def test_len(self) -> None:
        store = SpatialMemoryStore()
        assert len(store) == 0
        store.observe("a", "x", 1000)
        store.observe("b", "y", 1000)
        assert len(store) == 2

    def test_prune_old_memories(self) -> None:
        store = SpatialMemoryStore()
        store.observe("old", "ancient room", 100)
        # Advance far enough that activation drops below forget threshold
        pruned = store.prune(100 + TICKS_PER_DAY * 1000)
        assert pruned == 1
        assert len(store) == 0

    def test_consolidation(self) -> None:
        store = SpatialMemoryStore()
        long_desc = "A" * 100  # longer than 50 chars
        store.observe("room-1", long_desc, 100)
        # Advance enough to cross consolidation threshold (-1.0) but not forget (-3.0)
        # At 8 days: activation ≈ -1.04
        consolidated = store.consolidate(100 + TICKS_PER_DAY * 8)
        assert consolidated == 1
        # Check semantic summary was set
        mem = store._memories["room-1"]
        assert mem.semantic_summary is not None
        assert mem.semantic_summary.endswith("...")

    def test_trim_history(self) -> None:
        cfg = PerceptionConfig(max_observation_history=3)
        store = SpatialMemoryStore(cfg)
        for i in range(10):
            store.observe("room-1", "desc", 1000 + i)
        mem = store._memories["room-1"]
        assert len(mem.observation_ticks) == 3

    def test_active_memories_sorted(self) -> None:
        store = SpatialMemoryStore()
        store.observe("old", "old patch", 100)
        store.observe("new", "new patch", 5000)
        active = store.active_memories(5001)
        # "new" should be first (higher activation)
        assert len(active) >= 1
        if len(active) >= 2:
            assert active[0].patch_id == "new"

    def test_recall_consolidated_returns_summary(self) -> None:
        store = SpatialMemoryStore()
        long_desc = "B" * 100
        store.observe("room-1", long_desc, 100)
        tick = 100 + TICKS_PER_DAY * 8
        store.consolidate(tick)
        state, desc = store.recall("room-1", tick)
        if state == MemoryState.RETENTION:
            assert desc is not None
            assert desc.endswith("...")


if __name__ == "__main__":
    unittest.main()
