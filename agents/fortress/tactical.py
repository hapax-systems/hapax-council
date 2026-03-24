"""Tactical execution layer — translates symbolic commands to DFHack actions.

Maps governance decisions (e.g., "expand_workshops") to concrete DFHack
commands (dig_room, build_workshop, import_orders). Tracks what's been
built to avoid duplicate actions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agents.fortress.commands import FortressCommand
from agents.fortress.schema import FastFortressState, FullFortressState

log = logging.getLogger(__name__)


@dataclass
class TacticalContext:
    """Tracks tactical state across cycles to avoid duplicate actions."""

    orders_imported: bool = False
    room_dug: bool = False
    workshops_placed: set[str] = field(default_factory=set)
    dig_center_x: int = 0
    dig_center_y: int = 0
    dig_z: int = 0
    next_workshop_offset: int = 0  # offset from center for next workshop placement


def encode_tactical(
    cmd: FortressCommand,
    state: FastFortressState | FullFortressState,
    ctx: TacticalContext,
) -> list[dict[str, Any]]:
    """Translate a symbolic governance command to concrete DFHack actions.

    Returns a list of dicts, each suitable for DFHackBridge.send_command().
    """
    op = cmd.params.get("operation", "")

    if cmd.chain == "fortress_planner":
        return _encode_planner(op, state, ctx)
    elif cmd.chain == "resource_manager":
        return _encode_resource(op, state, ctx)
    elif cmd.chain == "crisis_responder":
        return _encode_crisis(op, state, ctx)
    else:
        # Pass through as-is for unhandled chains
        log.debug("Passthrough command: [%s] %s", cmd.chain, op)
        return []


def _encode_planner(
    op: str,
    state: FastFortressState | FullFortressState,
    ctx: TacticalContext,
) -> list[dict[str, Any]]:
    """Encode planner operations into dig + build commands."""
    actions: list[dict[str, Any]] = []

    if op in ("expand_workshops", "expand_bedrooms", "expand_stockpiles"):
        # Dig a room if not already done
        if not ctx.room_dug:
            # Find dig center from state — use first unit position as fallback
            cx, cy, cz = _find_center(state)
            ctx.dig_center_x = cx
            ctx.dig_center_y = cy
            ctx.dig_z = cz - 1  # one level below surface

            # Dig stairs to connect
            actions.append(
                {
                    "action": "dig_room",
                    "x": cx - 5,
                    "y": cy - 5,
                    "z": cz - 1,
                    "width": 11,
                    "height": 11,
                    "stair_x": cx,
                    "stair_y": cy,
                    "stair_z_surface": cz,
                }
            )
            ctx.room_dug = True
            log.info("Tactical: dig room at (%d,%d,%d) 11x11", cx - 5, cy - 5, cz - 1)

    if op == "expand_workshops":
        # Place workshops in the dug room
        workshop_types = ["Still", "Kitchen", "Craftsdwarfs"]
        for ws_type in workshop_types:
            if ws_type not in ctx.workshops_placed:
                # Offset each workshop within the room
                offset = ctx.next_workshop_offset
                wx = ctx.dig_center_x - 3 + (offset * 4)  # 4-tile spacing
                wy = ctx.dig_center_y
                wz = ctx.dig_z

                actions.append(
                    {
                        "action": "build_workshop",
                        "x": wx,
                        "y": wy,
                        "z": wz,
                        "workshop_type": ws_type,
                    }
                )
                ctx.workshops_placed.add(ws_type)
                ctx.next_workshop_offset += 1
                log.info("Tactical: place %s workshop at (%d,%d,%d)", ws_type, wx, wy, wz)
                break  # one workshop per cycle

    return actions


def _encode_resource(
    op: str,
    state: FastFortressState | FullFortressState,
    ctx: TacticalContext,
) -> list[dict[str, Any]]:
    """Encode resource operations into manager order imports."""
    actions: list[dict[str, Any]] = []

    if op in ("drink_production", "food_production", "equipment_production"):
        if not ctx.orders_imported:
            # Import the basic order library — covers brew, cook, thread, cloth, etc.
            actions.append({"action": "import_orders", "library": "library/basic"})
            ctx.orders_imported = True
            log.info("Tactical: importing library/basic orders")

    return actions


def _encode_crisis(
    op: str,
    state: FastFortressState | FullFortressState,
    ctx: TacticalContext,
) -> list[dict[str, Any]]:
    """Encode crisis operations — deferred, log only for now."""
    log.info("Tactical: crisis operation '%s' (not yet implemented)", op)
    return []


def _find_center(state: FastFortressState | FullFortressState) -> tuple[int, int, int]:
    """Find the fortress center point from state data."""
    # Default: send sentinel value (0,0,0) that tells the Lua side to auto-detect
    # via find_embark_center(). Unit positions aren't in our schema, so we rely
    # on the bridge to resolve the actual center.
    return (0, 0, 0)
