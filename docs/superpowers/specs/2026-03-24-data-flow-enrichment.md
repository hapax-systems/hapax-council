# Data Flow Enrichment — Events, Trends, and Background Signals for Fortress Governance

**Status:** Design (data pipeline specification)
**Date:** 2026-03-24
**Builds on:** Context System, Fortress Governance Chains, DFHack Bridge, Tactical Execution

## 1. Problem Statement

The fortress produces monotonous data. Every governance cycle sees nearly identical state. Chains make the same decisions repeatedly because nothing pressures diversity. The creativity chain never activates (Maslow gate), the deliberation loop has nothing interesting to reason about, and episodes have no narrative texture. This spec defines the pipeline that fills the perception system with meaningful signal variation.

## 2. Three Signal Layers

### Layer 1: Events (discrete, interrupt-driven)

Game events that trigger goal activation and suppression modulation.

| Event | Source | Urgency | Goal Activated | Suppression Effect |
|-------|--------|---------|----------------|--------------------|
| Siege | `eventful.onInvasion` | INTERRUPT | `respond_to_siege` (P90) | `crisis_suppression` → 1.0 |
| Megabeast | `eventful.onReport` (filtered) | INTERRUPT | `respond_to_siege` (P95) | crisis + military → 1.0 |
| Death | `eventful.onUnitDeath` | ALERT | none (morale assess) | none |
| Strange mood | poll `unit.mood` | ALERT | `handle_strange_mood` (P65) | none |
| Cave-in | `eventful.onReport` (filtered) | ALERT | none (reassess dig) | planner → 0.8 |
| Migrant wave | `eventful.onUnitNewActive` (batch) | NOTICE | `process_migrants` (P60) | none |
| Caravan | poll `plotinfo.caravans` | NOTICE | `manage_trade` (P55) | none |
| Season change | poll `cur_season` | NOTICE | conditional (autumn → `survive_winter`) | none |
| Mandate | poll `plotinfo.mandates` | NOTICE | `handle_mandate` (P50) | none |
| Building complete | `eventful.onJobCompleted` | BACKGROUND | none (state update) | none |
| Item created | `eventful.onItemCreated` | BACKGROUND | none (state update) | none |

### Layer 2: Trends (continuous, rate-of-change)

Time-series analysis of state variables to detect gradients and anomalies.

Tracked variables (20):

- `food_count`, `drink_count`, `population`, `idle_dwarf_count`, `most_stressed_value`
- `active_threats`, `job_queue_length`, `workshop_active_ratio`
- Per-stockpile: `wood`, `stone`, `metal_bars`, `weapons`, `armor`, `cloth`, `seeds`
- `wealth_created`, `wealth_exported`

For each variable:

- **EMA rate** (velocity): `ema = α * delta + (1 - α) * prev_ema`, α = 0.2
- **Linear regression slope** (trend): OLS over 10-sample window
- **Trend classification**: rising / stable / declining / crashing (per-variable thresholds)
- **Z-score anomaly**: EWMA mean/variance, flag at |z| > 2.5 (warning), > 3.5 (critical)
- **CUSUM shift detection**: sustained drift that Z-score misses
- **Projection**: ticks_to_threshold for critical values (food → 0, drink → 0)

Data structure: `FortressStateRing` wrapping `collections.deque(maxlen=30)` — 30 samples at 120-tick intervals = 3 game-days of history. Companion `VariableTracker` per variable for EMA/Z-score/CUSUM.

### Layer 3: Announcements (text stream, filtered)

The game's announcement system is the primary event channel. Approximately 170 announcement types, filtered to approximately 30 high-value types.

Source: `eventful.onReport` → `df.report.find(id)` → filter by `report.type` against `IMPORTANT_TYPES` set.

Filtered output feeds:

- Episode builder (narrative material)
- Deliberation loop (`recent_events` parameter)
- Chunk compressor (alerts section)

## 3. EventRouter

Central component wiring events to goals and suppression fields.

```python
class EventRouter:
    def process_events(events, state, now) -> list[ActiveEvent]:
        # For each event:
        # 1. Classify via EVENT_CLASSIFICATIONS table
        # 2. Dedup via response_id (event type + distinguishing fields)
        # 3. Activate CompoundGoal if specified
        # 4. Pre-modulate suppression fields if INTERRUPT
        # 5. Return INTERRUPT events for immediate governor re-eval

    def expire_events(state):
        # Check predicate-based expiry (threats_zero, idle_below_threshold, etc.)
        # Remove expired events, release suppression targets
```

Deduplication: response IDs computed from event-distinguishing fields. Same siege from same civilization → deduplicated. Different civilization → new response. IDs pruned on expiry.

Expiry: predicate-based, not time-based:

- Siege expires when `active_threats == 0`
- Migrant expires when `idle_dwarf_count < 3`
- Mood expires when unit's mood field returns to normal
- Season goal expires at next season boundary
- Time-based fallback only where no state signal exists (mandates: 2 seasons)

## 4. Bridge Event Collection

The DFHack bridge registers additional eventful hooks beyond the current invasion + death:

```lua
-- In hapax-df-bridge.lua start():
eventful.enableEvent(eventful.eventType.REPORT, 0)         -- announcements
eventful.enableEvent(eventful.eventType.JOB_COMPLETED, 0)  -- production
eventful.enableEvent(eventful.eventType.BUILDING, 0)       -- construction
eventful.enableEvent(eventful.eventType.UNIT_NEW_ACTIVE, 0) -- migrants
eventful.enableEvent(eventful.eventType.ITEM_CREATED, 5)   -- crafting

-- Announcement filter
eventful.onReport.hapax = function(report_id)
    local r = df.report.find(report_id)
    if r and IMPORTANT_TYPES[r.type] then
        table.insert(event_buffer, {
            type = "announcement",
            announcement_type = df.announcement_type[r.type],
            text = r.text,
            pos = {x = r.pos.x, y = r.pos.y, z = r.pos.z},
        })
    end
end

-- Polled events (season, caravan, mood, mandate) added to export cycle
```

The bridge adds polled event detection for season changes, caravan arrivals, strange moods, and mandate creation to the existing `export_fast()` function. These check against cached previous values and emit events on change.

## 5. Trend Engine

```python
@dataclass
class VariableTracker:
    values: deque[float]       # raw samples (maxlen=30)
    timestamps: deque[int]     # tick of each sample
    ema_rate: float = 0.0      # exponential moving average of rate
    ewma_mean: float = 0.0     # for Z-score
    ewma_var: float = 0.0      # for Z-score
    cusum_pos: float = 0.0     # CUSUM positive accumulator
    cusum_neg: float = 0.0     # CUSUM negative accumulator

class TrendEngine:
    _trackers: dict[str, VariableTracker]
    _state_ring: deque[dict[str, float]]  # snapshot ring

    def push(self, state: FastFortressState) -> None:
        # Extract 20 tracked variables from state
        # Update each VariableTracker
        # Compute EMA rates, Z-scores, CUSUM

    def trend(self, variable: str) -> str:
        # Returns: "rising" | "stable" | "declining" | "crashing"

    def anomalies(self) -> list[str]:
        # Returns descriptions of variables with |z| > 2.5

    def projections(self) -> list[str]:
        # Returns "food exhausted in ~15 cycles" type predictions

    def correlations(self) -> list[str]:
        # Returns detected co-occurring trends (from CAUSAL_RULES)
```

## 6. Chunk Compressor Enhancement

The existing ChunkCompressor gains trend and projection data:

```
Before: "Food: 120. Drink: 45. (6/2 per dwarf)"
After:  "Food: 120, -8/day (declining). Drink: 45, -12/day (crashing → exhausted in ~4 days). (6/2 per dwarf)"
```

The `_food_chunk` function receives trend data from TrendEngine and embeds rate + classification + projection inline.

## 7. Deliberation Loop Integration

The deliberation loop's `recent_events` parameter receives:

- Active events from EventRouter (type + response_id + age)
- Recent announcements (last 5 important)
- Trend alerts (anomalies + projections)

```python
recent_events = []
for ae in event_router.active_events:
    recent_events.append(f"[{ae.classification.urgency}] {ae.event.type}: {ae.response_id}")
for anomaly in trend_engine.anomalies():
    recent_events.append(f"[TREND] {anomaly}")
for proj in trend_engine.projections():
    recent_events.append(f"[PROJECTION] {proj}")
```

## 8. New Goals

Three new CompoundGoals:

- `handle_strange_mood` (P65): provide workshop + provide materials
- `manage_trade` (P55): haul to depot + select trade goods
- `handle_mandate` (P50): produce mandated item

## 9. Files Changed

New:

- `agents/fortress/events.py` — EventRouter, EventClassification, EVENT_CLASSIFICATIONS
- `agents/fortress/trends.py` — TrendEngine, VariableTracker, trend/anomaly/projection functions

Modified:

- `scripts/hapax-df-bridge.lua` — register additional eventful hooks, add polled event detection
- `agents/fortress/__main__.py` — wire EventRouter + TrendEngine into governance loop
- `agents/fortress/goal_library.py` — add 3 new goals, update DEFAULT_GOALS
- `agents/fortress/chunks.py` — embed trends/projections in chunk text
- `agents/fortress/deliberation.py` — pipe active events + trends to recent_events

## 10. What This Enables

With data flow enrichment:

- Siege → crisis chain fires → military responds → planner suppressed → creativity killed
- Migrant wave → GoalPlanner activates `process_migrants` → resource chain allocates food/beds
- Strange mood → advisor chain can reason about material availability
- Season change → winter preparation goals activate in autumn
- Drink declining → trend engine projects exhaustion → chunk says "crashing" → deliberation prioritizes brewing
- Caravan arrives → trade goal activates → resource chain prepares export goods

Without it: the governor makes the same decision every cycle indefinitely.
