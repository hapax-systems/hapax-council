"""Tests for tactical execution layer."""

from __future__ import annotations

from agents.fortress.commands import FortressCommand
from agents.fortress.schema import FastFortressState
from agents.fortress.tactical import TacticalContext, encode_tactical


def _fast_state(**kw):
    defaults = dict(
        timestamp=0,
        game_tick=100000,
        year=1,
        season=0,
        month=0,
        day=0,
        fortress_name="Test",
        paused=False,
        population=7,
        food_count=100,
        drink_count=5,
        active_threats=0,
        job_queue_length=0,
        idle_dwarf_count=7,
        most_stressed_value=0,
    )
    defaults.update(kw)
    return FastFortressState(**defaults)


class TestEncodeResource:
    def test_drink_production_imports_orders(self):
        cmd = FortressCommand(
            id="",
            action="order",
            chain="resource_manager",
            params={"operation": "drink_production"},
        )
        ctx = TacticalContext()
        actions = encode_tactical(cmd, _fast_state(), ctx)
        assert len(actions) == 1
        assert actions[0]["action"] == "import_orders"
        assert actions[0]["library"] == "library/basic"
        assert ctx.orders_imported

    def test_orders_imported_only_once(self):
        cmd = FortressCommand(
            id="",
            action="order",
            chain="resource_manager",
            params={"operation": "drink_production"},
        )
        ctx = TacticalContext()
        encode_tactical(cmd, _fast_state(), ctx)
        actions2 = encode_tactical(cmd, _fast_state(), ctx)
        assert len(actions2) == 0  # already imported

    def test_food_production_also_imports(self):
        cmd = FortressCommand(
            id="",
            action="order",
            chain="resource_manager",
            params={"operation": "food_production"},
        )
        ctx = TacticalContext()
        actions = encode_tactical(cmd, _fast_state(), ctx)
        assert len(actions) == 1
        assert actions[0]["action"] == "import_orders"


class TestEncodePlanner:
    def test_expand_workshops_digs_room(self):
        cmd = FortressCommand(
            id="",
            action="dig",
            chain="fortress_planner",
            params={"operation": "expand_workshops"},
        )
        ctx = TacticalContext()
        actions = encode_tactical(cmd, _fast_state(), ctx)
        # Should produce dig_room + build_workshop
        action_types = [a["action"] for a in actions]
        assert "dig_room" in action_types
        assert "build_workshop" in action_types
        assert ctx.room_dug

    def test_room_dug_only_once(self):
        cmd = FortressCommand(
            id="",
            action="dig",
            chain="fortress_planner",
            params={"operation": "expand_workshops"},
        )
        ctx = TacticalContext()
        encode_tactical(cmd, _fast_state(), ctx)
        actions2 = encode_tactical(cmd, _fast_state(), ctx)
        # Second call should only build workshop, not dig again
        action_types = [a["action"] for a in actions2]
        assert "dig_room" not in action_types

    def test_workshops_placed_incrementally(self):
        cmd = FortressCommand(
            id="",
            action="dig",
            chain="fortress_planner",
            params={"operation": "expand_workshops"},
        )
        ctx = TacticalContext()
        a1 = encode_tactical(cmd, _fast_state(), ctx)
        a2 = encode_tactical(cmd, _fast_state(), ctx)
        a3 = encode_tactical(cmd, _fast_state(), ctx)
        # Each call should place a different workshop
        ws_types = set()
        for actions in [a1, a2, a3]:
            for a in actions:
                if a["action"] == "build_workshop":
                    ws_types.add(a["workshop_type"])
        assert len(ws_types) == 3  # Still, Kitchen, Craftsdwarfs


class TestTacticalContext:
    def test_initial_state(self):
        ctx = TacticalContext()
        assert not ctx.orders_imported
        assert not ctx.room_dug
        assert len(ctx.workshops_placed) == 0

    def test_passthrough_for_unknown_chains(self):
        cmd = FortressCommand(
            id="",
            action="creativity",
            chain="creativity",
            params={"operation": "semantic_naming"},
        )
        ctx = TacticalContext()
        actions = encode_tactical(cmd, _fast_state(), ctx)
        assert len(actions) == 0  # passthrough returns empty
