"""Tests for the parameter drift engine."""

from __future__ import annotations

import math

import pytest

from agents.effect_graph.parameter_drift import (
    ParameterDriftState,
    SlotDriftState,
    drift_tick,
    init_drift_state,
    set_drift_target,
    snapshot_current_state,
)


class TestInitAndSnapshot:
    def test_init_creates_slots(self):
        state = init_drift_state(24)
        assert len(state.slots) == 24
        assert not state.initialized

    def test_snapshot_seeds_current(self):
        state = init_drift_state(4)
        assignments = ["colorgrade", "bloom", None, None]
        base_params = [
            {"brightness": 1.0, "contrast": 1.2},
            {"radius": 5.0, "threshold": 0.3},
            {},
            {},
        ]
        snapshot_current_state(state, assignments, base_params)
        assert state.initialized
        assert state.slots[0].node_type == "colorgrade"
        assert state.slots[0].current["brightness"] == 1.0
        assert state.slots[1].node_type == "bloom"
        assert state.slots[1].current["radius"] == 5.0
        assert state.slots[2].node_type is None

    def test_snapshot_excludes_time_width_height(self):
        state = init_drift_state(1)
        snapshot_current_state(
            state,
            ["colorgrade"],
            [{"brightness": 1.0, "time": 42.0, "width": 1280.0, "height": 720.0}],
        )
        assert "brightness" in state.slots[0].current
        assert "time" not in state.slots[0].current
        assert "width" not in state.slots[0].current


class TestSetDriftTarget:
    def test_matching_topology_returns_true(self):
        state = init_drift_state(2)
        state.slots[0].node_type = "colorgrade"
        state.slots[0].current = {"brightness": 1.0}
        state.initialized = True

        ok = set_drift_target(state, 0, "colorgrade", {"brightness": 0.8, "contrast": 1.5})
        assert ok
        assert state.slots[0].target["brightness"] == 0.8

    def test_mismatched_topology_returns_false(self):
        state = init_drift_state(2)
        state.slots[0].node_type = "colorgrade"
        state.initialized = True

        ok = set_drift_target(state, 0, "bloom", {"radius": 5.0})
        assert not ok

    def test_out_of_range_slot(self):
        state = init_drift_state(2)
        ok = set_drift_target(state, 99, "colorgrade", {})
        assert not ok


class TestDriftTick:
    def test_convergence_toward_target(self):
        state = init_drift_state(1)
        state.slots[0].node_type = "colorgrade"
        state.slots[0].current = {"brightness": 0.5}
        state.slots[0].target = {"brightness": 1.0}
        state.initialized = True

        # Zero sigma for deterministic test
        import os
        os.environ["HAPAX_DRIFT_SIGMA"] = "0"
        os.environ["HAPAX_DRIFT_TAU_S"] = "5"
        try:
            updates = drift_tick(state, dt=5.0, stance="nominal")
            # After tau seconds, should be ~63% of the way
            expected = 0.5 + 0.5 * (1 - math.exp(-1))
            assert 0 in updates
            assert abs(updates[0]["brightness"] - expected) < 0.01
        finally:
            os.environ.pop("HAPAX_DRIFT_SIGMA", None)
            os.environ.pop("HAPAX_DRIFT_TAU_S", None)

    def test_stance_slows_drift(self):
        """Cautious stance should drift slower than nominal."""
        import os
        os.environ["HAPAX_DRIFT_SIGMA"] = "0"
        os.environ["HAPAX_DRIFT_TAU_S"] = "5"
        try:
            # Nominal
            s1 = init_drift_state(1)
            s1.slots[0].node_type = "cg"
            s1.slots[0].current = {"b": 0.0}
            s1.slots[0].target = {"b": 1.0}
            s1.initialized = True
            u1 = drift_tick(s1, dt=1.0, stance="nominal")

            # Cautious (2.5x tau)
            s2 = init_drift_state(1)
            s2.slots[0].node_type = "cg"
            s2.slots[0].current = {"b": 0.0}
            s2.slots[0].target = {"b": 1.0}
            s2.initialized = True
            u2 = drift_tick(s2, dt=1.0, stance="cautious")

            # Nominal should have moved further
            assert u1[0]["b"] > u2[0]["b"]
        finally:
            os.environ.pop("HAPAX_DRIFT_SIGMA", None)
            os.environ.pop("HAPAX_DRIFT_TAU_S", None)

    def test_bounds_clamping(self):
        state = init_drift_state(1)
        state.slots[0].node_type = "colorgrade"
        state.slots[0].current = {"brightness": 0.9}
        state.slots[0].target = {"brightness": 5.0}  # way above bound
        state.slots[0].bounds = {"brightness": (0.0, 1.2)}
        state.initialized = True

        import os
        os.environ["HAPAX_DRIFT_SIGMA"] = "0"
        os.environ["HAPAX_DRIFT_TAU_S"] = "1"
        try:
            # Run for a very long dt so it fully converges
            updates = drift_tick(state, dt=100.0, stance="nominal")
            assert updates[0]["brightness"] <= 1.2
        finally:
            os.environ.pop("HAPAX_DRIFT_SIGMA", None)
            os.environ.pop("HAPAX_DRIFT_TAU_S", None)

    def test_no_update_when_at_target(self):
        state = init_drift_state(1)
        state.slots[0].node_type = "cg"
        state.slots[0].current = {"b": 1.0}
        state.slots[0].target = {"b": 1.0}
        state.initialized = True

        import os
        os.environ["HAPAX_DRIFT_SIGMA"] = "0"
        try:
            updates = drift_tick(state, dt=1.0)
            # No change needed — should be empty or have negligible changes
            assert not updates or abs(updates.get(0, {}).get("b", 1.0) - 1.0) < 1e-5
        finally:
            os.environ.pop("HAPAX_DRIFT_SIGMA", None)

    def test_uninitalized_noop(self):
        state = init_drift_state(1)
        updates = drift_tick(state, dt=1.0)
        assert updates == {}

    def test_negative_dt_noop(self):
        state = init_drift_state(1)
        state.initialized = True
        updates = drift_tick(state, dt=-1.0)
        assert updates == {}
