# Perceptual Chunking and Spatial Memory

**Status:** Design (perception architecture specification)
**Date:** 2026-03-24
**Builds on:** DFHack Bridge Protocol, Fortress State Schema, Fortress Governance Chains

This specification replaces the omniscient state dump with a constrained observation system that models human-like sequential perception. The AI agent does not receive the full game state; instead, it issues observation queries against a spatial patch index and maintains a decaying memory of previously observed regions.

---

## 1. Design Principles

1. The AI does **not** receive full game state. It receives coherent spatial patches via observation queries.
2. What the operator looks at determines what it knows. Unobserved regions fade from memory following ACT-R base-level activation (BLA) decay.
3. The observation interface is tool-based: LLM governance chains call observation tools and receive natural-language patch descriptions.
4. An attention budget constrains the number of observation queries per game-day: `budget = 5 + 1.8 * sqrt(population)`, capped at 30.
5. Event-driven interrupts from DFHack (siege, death, mood) are push-based and fall outside the attention budget.

---

## 2. Patch Segmentation

Dwarf Fortress maps are segmented into coherent patches using DF's own spatial units.

### Patch Types

- **Type A: Named Rooms** — Buildings with `is_room == true`. Boundaries derived from `building.room` extents. Description via `dfhack.buildings.getRoomDescription()`.
- **Type B: Civzones** — Activity zones (temple, library, tavern). Boundaries from `x1/y1/x2/y2/z`.
- **Type C: Workshops/Stockpiles** — Functional areas not formally designated as rooms.
- **Type D: Corridors/Unclaimed** — Algorithmic segmentation via flood-fill from doors. Width-based classification: 1-2 tiles = corridor, 3+ square tiles = chamber.

### Patch Hierarchy

```
Tile → Room/Zone → Floor (z-level) → Connected Region → Fortress
```

---

## 3. Observation Tools

Observation follows a tool-as-query-language pattern (ReAct). Each tool returns a natural-language patch description.

```python
# Observation tool definitions

def observe_region(center_x: int, center_y: int, z: int, radius: int = 5) -> str:
    """Observe a spatial region. Returns NL description of all patches within radius."""

def describe_patch(patch_id: str) -> str:
    """Get detailed description of a named patch (room, workshop, stockpile)."""

def check_stockpile(category: str) -> str:
    """Quick stockpile level check. Returns: 'Food: 234 items (adequate for 47 dwarves)'."""

def scan_threats() -> str:
    """Scan for active threats. Returns NL summary of hostile units. Always costs 0 budget (crisis)."""

def examine_dwarf(unit_id: int) -> str:
    """Examine a specific dwarf. Returns skills, mood, job, stress level."""

def survey_floor(z_level: int) -> str:
    """High-level survey of an entire z-level. Returns room names, corridors, activity summary."""

def check_announcements(since_tick: int = 0) -> str:
    """Recent game announcements. Free (event-driven data)."""
```

---

## 4. Spatial Memory (ACT-R BLA)

Each queried patch produces a `SpatialMemory` record that tracks observation history and computes activation-based confidence.

```python
@dataclass
class SpatialMemory:
    patch_id: str
    last_observation: str  # NL description from last query
    observation_ticks: list[int]  # game ticks when observed (for BLA)
    entity_mobility: str  # STATIC | SLOW | FAST
    semantic_summary: str | None = None  # consolidated after decay

    def activation(self, current_tick: int, d: float = 0.5) -> float:
        """ACT-R base-level activation: ln(sum(t_j^(-d)))"""

    def confidence(self, current_tick: int) -> float:
        """Belief confidence adjusted for entity mobility."""
```

### Memory States

Three memory states per patch, determined by activation level:

- **Impression** (activation > 0): Full detail, full confidence. Currently or recently observed.
- **Retention** (activation between FORGET and 0): Fading. Presents last-known state or semantic summary.
- **Forgotten** (activation < FORGET): Pruned from working context. Equivalent to fog of war.

### Decay Rates

Static features (walls, rooms) decay slowly. Dynamic features (creatures, item counts) decay at an accelerated rate.

### Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| `d` | 0.5 | Canonical ACT-R decay exponent |
| `CONSOLIDATION_THRESHOLD` | -1.0 | Below this, full detail replaced by semantic summary |
| `FORGET_THRESHOLD` | -3.0 | Below this, record pruned from context |
| `MAX_OBSERVATION_HISTORY` | 20 | Maximum stored observation ticks per patch |

---

## 5. Attention Budget

The attention budget scales with fortress population:

```
budget(n) = 5 + 1.8 * sqrt(n_dwarves), capped at 30
```

| Population | Budget/day |
|------------|------------|
| 7 (embark) | 10 |
| 50 | 18 |
| 150 | 27 |
| 200+ | 30 (cap) |

### Three-Tier Allocation

- **Tier 1 (40%): Crisis detection** — military alerts, deaths, tantrums, flooding.
- **Tier 2 (35%): Routine monitoring** — stockpile levels, job queues, workshop activity, dwarf needs.
- **Tier 3 (25%): Strategic planning** — military training progress, skill development, exploration, noble demands.

### Dynamic Reallocation

When a crisis is detected, Tier 3 budget shifts to Tier 1, producing a 65%/35%/0% split. Tier 2 is preserved to maintain situational awareness during emergencies.

Event-driven interrupts (via DFHack `eventful` hooks) are free and fall outside the budget entirely.

---

## 6. Natural-Language Patch Generation

Each patch description follows the NetHack Language Wrapper pattern of (distance, direction, entity), grouped into coherent sentences.

**Example output:**

> The forge workshop on z-3 (5 tiles south of the dining hall) is currently idle. 2 iron bars and 8 copper bars in the adjacent stockpile. Urist McSmith is present, skill Legendary.

### Salience Filtering

- Only noteworthy features are included; not every tile is enumerated.
- Items below a threshold quantity are omitted.
- Dwarves are mentioned only when performing a notable action or when specifically queried.

---

## 7. Integration with Governance Chains

Governance chains currently receive full state objects. This specification introduces an observation layer between the DFHack bridge and chain evaluation.

### Pipeline

1. **GoalPlanner** determines which subsystems require attention (active goals).
2. **Observation Allocator** spends the attention budget on goal-relevant queries.
3. Observations update `SpatialMemory` records.
4. Chains evaluate using `SpatialMemory` (partial, faded) instead of omniscient state.
5. The creativity epsilon modulates how Tier 3 budget is spent: novel exploration versus routine monitoring.

### Relationship to Existing Infrastructure

This layer is additive. The DFHack bridge continues to produce raw state for metrics collection and death detection. The observation system sits between the bridge and the chains, filtering what the chains perceive.

---

## 8. Experimental Variables

The attention budget is the primary independent variable.

### Conditions

- **Condition A (omniscient):** Unlimited budget, full state every tick. This is the current baseline.
- **Condition B (constrained):** Calibrated budget per the scaling function defined in Section 5.
- **Condition C (minimal):** 5 queries per game-day regardless of population.

### Dependent Variables

- Fortress survival time (game-days).
- Decision quality (goal completion rate, dwarf mortality rate).
- Internal model accuracy (divergence between spatial memory and ground-truth state).

### Hypothesis

Constrained observation forces improved internal organization and produces more creative play through semantic compression under information scarcity. Condition B is expected to outperform Condition A on decision quality per observation, while Condition A provides higher raw accuracy.
