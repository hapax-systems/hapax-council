# Boundary Fixes — Game Data Completeness and Boundary Purification

**Status:** Design (boundary layer specification)
**Date:** 2026-03-24
**Builds on:** Context System, Data Flow Enrichment, Agent-Environment Boundary Analysis

This specification addresses two categories of deficiency in the fortress governor's boundary layer: (1) game data gaps in the Lua bridge that reduce the environmental complexity visible through the boundary, and (2) boundary violations where agent-side inference leaks into the observation function.

---

## 1. Boundary Principle

The fortress governor is the observation/action interface between Hapax (agent) and Dwarf Fortress (environment). The observation function reports what IS. The agent infers what it MEANS. The boundary must not embed agent interpretations into observations.

Theoretical grounding:

- **Sutton & Barto:** The environment comprises everything the agent cannot arbitrarily change. The boundary separates what the agent controls from what it does not.
- **POMDP formalism:** The agent receives O = Z(S), never S directly. Observations are a function of state, not a function of state plus interpretation.
- **Gibson (ecological perception):** Affordances are perceived by the agent, not declared by the environment. The environment presents structure; the agent extracts relevance.

---

## 2. Game Data Gaps (Lua Bridge)

The following subsections identify fields defined in the fortress state schema that currently report hardcoded or missing values. Each fix replaces a constant with a computed value drawn from DFHack's Lua API.

### 2.1 Building Counts

Replace hardcoded zeros with actual counts from `df.global.world.buildings.all`.

```lua
pcall(function()
    for _, bld in ipairs(df.global.world.buildings.all) do
        local t = bld.type
        if t == df.building_type.Door then state.buildings.doors = state.buildings.doors + 1
        elseif t == df.building_type.Bed then state.buildings.beds = state.buildings.beds + 1
        elseif t == df.building_type.Table then state.buildings.tables = state.buildings.tables + 1
        elseif t == df.building_type.Chair then state.buildings.chairs = state.buildings.chairs + 1
        elseif t == df.building_type.Statue then state.buildings.statues = state.buildings.statues + 1
        elseif t == df.building_type.Armorstand then state.buildings.armor_stands = state.buildings.armor_stands + 1
        elseif t == df.building_type.Weaponrack then state.buildings.weapon_racks = state.buildings.weapon_racks + 1
        elseif t == df.building_type.Coffin then state.buildings.coffins = state.buildings.coffins + 1
        elseif t == df.building_type.TradeDepot then state.buildings.trade_depot = state.buildings.trade_depot + 1
        end
    end
end)
```

### 2.2 Squad Equipment Quality and Training Level

Replace hardcoded 0.5 with computed values.

- **Equipment quality:** Average item quality (0-5 scale, normalized to 0-1) across all squad members' worn items.
- **Training level:** Average combat skill rating across squad members, normalized to 0-1 (20 = legendary = 1.0).

### 2.3 Event Hooks

Register additional eventful hooks and polled detectors:

**Eventful hooks:**
- `eventful.onUnitNewActive` — MigrantEvent (filter to citizens only)
- `eventful.onReport` — filtered by IMPORTANT_TYPES for mood, caravan, and mandate announcements
- `eventful.onBuildingCreatedDestroyed` — building completion tracking
- `eventful.onJobCompleted` — production tracking

**Polled detectors:**
- Season change: compare `cur_season` to cached value
- Strange mood: scan `unit.mood` across active citizens
- Caravan: scan `plotinfo.caravans`
- Mandate: scan `plotinfo.mandates`

### 2.4 Map Exploration State

Compute z_levels_explored, cavern_layers_breached, and aquifer detection:

- **z_levels_explored:** Count z-levels with any non-hidden tiles.
- **cavern_layers_breached:** Count features with Discovered flag set.
- **aquifer_present:** Scan for aquifer block flags.

---

## 3. Boundary Purification

The following subsections identify locations where agent-side inference has leaked into the observation function, violating the boundary principle defined in Section 1.

### 3.1 Remove Trend Labels from Chunks

Chunks report raw state only. Remove the `trends` parameter from `compress()`, `_food_chunk()`, and all callers. Trends are agent-side analysis consumed by the deliberation loop separately.

**Before:**
```
"Food: 200, -8/day (declining). Drink: 45 (crashing)."
```

**After:**
```
"Food: 200. Drink: 45. (10/2 per dwarf)"
```

The deliberation loop's `recent_events` list already receives trend anomalies and projections from TrendEngine. That is the correct channel for agent inference.

### 3.2 Rename neuroception Parameter

In `creativity.py`, rename `stimmung_worst` to `normalized_stress` for clarity. The function gates on game-derived stress, not Hapax's internal stimmung. The current implementation is functionally correct (`chains/creativity.py` normalizes `most_stressed_value / 200_000`), but the parameter name implies a dependency on Hapax's affect system that does not exist.

### 3.3 Clarify TrendEngine Location

TrendEngine stays in `agents/fortress/` (it requires the schema types) but its outputs (trend labels, anomalies, projections) are consumed ONLY by the deliberation loop, not by the boundary layer. This must be documented: TrendEngine is agent-side analysis that happens to reside near the boundary for import convenience. It does not belong to the observation function.

---

## 4. Files Changed

### Lua

| File | Change |
|------|--------|
| `scripts/hapax-df-bridge.lua` | Building counts, squad quality computation, event hooks, polled detectors, map exploration state |

### Python

| File | Change |
|------|--------|
| `agents/fortress/chunks.py` | Remove `trends` parameter from `compress()` and `_food_chunk()` |
| `agents/fortress/creativity.py` | Rename `stimmung_worst` to `normalized_stress` |
| `agents/fortress/__main__.py` | Stop passing trends to `compress()` |
| `agents/fortress/observation.py` | Stop passing trends to `get_situation_chunks()` |
| `agents/fortress/deliberation.py` | Stop passing trends to `compress()` (keep passing to deliberation prompt as separate section) |

---

## 5. What This Does NOT Do

- Does not wire Hapax internal systems (stimmung, profile, Qdrant) into the governor.
- Does not change the deliberation loop's use of TrendEngine (that is correct agent-side analysis).
- Does not change the observation tool set or attention budget.
- Does not add new schema fields (existing schema already defines these; this specification addresses populating them).
