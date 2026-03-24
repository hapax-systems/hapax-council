# Tactical Execution Layer — Decision to DFHack Command Translation

**Status:** Design (execution pipeline specification)
**Date:** 2026-03-24
**Builds on:** Fortress Governance Chains, DFHack Bridge Protocol, Fortress Wiring Integration

This specification defines how symbolic governance decisions become concrete DFHack actions.

---

## 1. Problem Statement

The governor produces symbolic commands such as `{"operation": "expand_workshops"}` and `{"operation": "drink_production"}`. These flow through the bridge to DFHack but lack a tactical encoder. The bridge does not translate "expand_workshops" into dig designations or "drink_production" into manager orders. This specification defines the translation layer that maps symbolic governance output to executable DFHack primitives.

## 2. Architecture — Tactical Encoders

Each governance chain output maps to a **tactical encoder** that produces concrete DFHack commands.

| Chain | Symbolic Output | Tactical Encoder | DFHack Action |
|-------|----------------|-------------------|---------------|
| fortress_planner | expand_workshops | DigEncoder | `designate_rect()` + `constructBuilding()` |
| fortress_planner | expand_bedrooms | DigEncoder | `designate_rect()` + bed/door placement |
| resource_manager | drink_production | OrderEncoder | Manager order JSON import |
| resource_manager | food_production | OrderEncoder | Manager order JSON import |
| military_commander | full_assault | MilitaryEncoder | Squad assignment (deferred) |
| crisis_responder | immediate_lockdown | CrisisEncoder | Door close + burrow (deferred) |
| creativity | semantic_naming | NamingEncoder | `setNickname()` (deferred) |

Phase 1 implements DigEncoder and OrderEncoder only.

## 3. DigEncoder

The DigEncoder translates planner operations into concrete dig and build actions.

### 3.1 Location Selection

1. Find embark center via wagon position, hotkey zoom, or first unit position.
2. Scan downward from surface for a solid non-aquifer layer.
3. Place a staircase at center connecting surface to the dig layer.
4. Designate a rectangular room around the staircase center.

```lua
-- Pseudocode flow:
center = find_embark_center()
dig_z = find_diggable_layer(center, offset=-1 to -20)
designate_downstair(center.x, center.y, center.z)
designate_upstair(center.x, center.y, dig_z)
designate_rect(center.x-5, center.y-5, dig_z, center.x+5, center.y+5)
checkDesignationsNow()
```

### 3.2 Workshop Placement

After room excavation completes, place workshops using `dfhack.buildings.constructBuilding{}`:
- `type = df.building_type.Workshop`
- `subtype = df.workshop_type.Still` (for drink production), `.Craftsdwarfs`, etc.
- The `buildingplan` plugin handles material selection automatically.

### 3.3 Operations to Actions Mapping

| Operation | Dig | Build | Size |
|-----------|-----|-------|------|
| expand_workshops | 11x11 room | 1 Still + 1 Kitchen + 1 Craftsdwarf | 3x3 each |
| expand_bedrooms | 11x11 room | N beds + N doors | 1x1 each |
| expand_stockpiles | 5x5 area | 1 food stockpile | 5x5 |
| expand_defense | 3-wide corridor | 1 door at entrance | 1x1 |

### 3.4 Safety Checks

- Never dig into aquifer tiles (`dfhack.maps.isTileAquifer()`).
- Never dig into magma (`tiletype_material.MAGMA`).
- Verify accessibility (`dfhack.maps.canWalkBetween()`) from surface to dig site.
- Only dig WALL tiles (skip already-open space).

## 4. OrderEncoder

The OrderEncoder translates resource manager operations into DFHack manager orders.

### 4.1 Operations to Orders Mapping

| Operation | DFHack Command | Order Details |
|-----------|---------------|---------------|
| drink_production | `orders import` | Brew drink from plants, frequency=Daily, condition: plants >= 5 |
| food_production | `orders import` | Cook lavish meal, frequency=Daily, condition: cookable items >= 20 |
| equipment_production | `orders import` | Forge weapons, frequency=Monthly |

### 4.2 Order JSON Generation

Instead of writing JSON files, use the `workorder` command inline:

```lua
dfhack.run_command('workorder', '{"job":"CustomReaction","reaction":"BREW_DRINK_FROM_PLANT","amount_total":5,"frequency":"Daily"}')
```

Or import the built-in library:

```lua
dfhack.run_command('orders', 'import', 'library/basic')
```

The minimal viable approach: on first `drink_production` command, import `library/basic` which includes brew, cook, thread, cloth, and related orders. This provides the fortress with a complete production baseline without per-order encoding.

### 4.3 Deduplication at the Tactical Level

Orders are imported at most once. The encoder tracks which order sets have been imported and suppresses duplicate import commands.

## 5. Labor Management

Enable `labormanager` plugin on bridge start. No per-command encoding is required; the plugin handles all labor assignment automatically.

```lua
-- In hapax-df-bridge.lua start():
dfhack.run_command('enable', 'labormanager')
```

## 6. Bridge Command Handler Updates

The bridge's `poll_commands()` function requires new action handlers:

```lua
-- New actions:
if action == "dig_room" then
    -- params: {x, y, z, width, height, dig_type}
    designate_rect(cmd.x, cmd.y, cmd.z, cmd.x + cmd.width - 1, cmd.y + cmd.height - 1, cmd.dig_type)
    dfhack.job.checkDesignationsNow()

elseif action == "build_workshop" then
    -- params: {x, y, z, workshop_type}
    dfhack.buildings.constructBuilding{
        type = df.building_type.Workshop,
        subtype = df.workshop_type[cmd.workshop_type],
        pos = xyz2pos(cmd.x, cmd.y, cmd.z),
        width = 3, height = 3,
    }

elseif action == "import_orders" then
    -- params: {library}
    dfhack.run_command('orders', 'import', cmd.library)

elseif action == "workorder" then
    -- params: {order_json}
    dfhack.run_command('workorder', cmd.order_json)
```

## 7. Governor Tactical Dispatch

The governor's `__main__.py` dispatch loop requires a tactical layer that translates symbolic commands before sending to the bridge:

```python
def _encode_tactical(self, cmd: FortressCommand, state) -> list[dict]:
    """Translate symbolic command to concrete DFHack actions."""
    if cmd.chain == "fortress_planner" and cmd.params.get("operation") == "expand_workshops":
        center = self._find_dig_center(state)
        return [
            {"action": "dig_room", "x": center.x-5, "y": center.y-5, "z": center.z-1, "width": 11, "height": 11},
            {"action": "build_workshop", "x": center.x, "y": center.y, "z": center.z-1, "workshop_type": "Still"},
        ]
    elif cmd.chain == "resource_manager" and cmd.params.get("operation") == "drink_production":
        return [{"action": "import_orders", "library": "library/basic"}]
    else:
        return [cmd.to_bridge_dict()]  # pass through as-is
```

## 8. Phase 1 Implementation Scope

Minimal viable execution:

1. Enable `labormanager` on bridge start.
2. Import `library/basic` orders on first `drink_production` or `food_production` command.
3. Dig a room below surface on first `expand_workshops` command.
4. Place a Still workshop in the dug room.
5. All other commands pass through as symbolic (logged but not executed).

## 9. Files Changed

Lua (bridge):
- `hapax-df-bridge.lua` — new action handlers (`dig_room`, `build_workshop`, `import_orders`), enable `labormanager` on start, dig/build utility functions.

Python (governor):
- `agents/fortress/__main__.py` — tactical encoding layer before bridge dispatch.
- `agents/fortress/tactical.py` (NEW) — `encode_tactical()` function, dig center finding, order generation.

## 10. Deferred Scope

- Military squad management (Phase 2)
- Crisis lockdown (Phase 2)
- Creativity actions (Phase 3)
- Multi-level fortress planning (Phase 2)
- Blueprint library integration (Phase 2)
