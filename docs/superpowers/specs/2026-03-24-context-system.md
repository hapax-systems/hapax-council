# Context System — Perception, Query, and Working Memory for Fortress Governance

**Status:** Design (perception architecture specification)
**Date:** 2026-03-24
**Builds on:** Perceptual Chunking, Fortress Governance Chains, DFHack Bridge, Tactical Execution

This specification defines how the LLM-based governor perceives, queries, and reasons about the fortress. The design models human perceptual-decision-making during Dwarf Fortress play: bounded observation, change-driven attention, chunked working memory, and a deliberation rhythm anchored to game-day boundaries. It is the integration layer between the deterministic fast loop (threshold-based governance chains) and the LLM deliberation loop (ReAct-style tool use).

---

## 1. Design Principles

1. **Perception constrains intelligence.** The governor observes what it queries. Unqueried state decays via base-level activation (Anderson & Lebiere, 1998). No omniscient state dumps enter the context window.
2. **Menus are holistic; maps are chunked.** Menu and status data (stocks, military, nobles) arrives complete in a single tool call, analogous to a human reading a list. Spatial and map data arrives in attended patches, analogous to sequential gaze fixation (Itti & Koch, 2001).
3. **4 chunks per observation cycle.** Working memory capacity is fixed at 4 slots following Cowan's embedded-processes model (Cowan, 2001). Each chunk is one sentence, maximum 25 tokens. Chunks expand on salience (see Section 3).
4. **Change detection over absolute state.** The primary input to deliberation is foreground deltas ("food dropped 30 since yesterday"), not static values. This follows the change-detection literature showing that transients capture attention more reliably than steady-state features (Rensink, 2002).
5. **Natural language prose, not JSON.** For LLM input, structured natural language with section headers yields higher reasoning accuracy than raw schema (Reynolds & McDonell, 2021). All tool outputs are prose with embedded quantities.
6. **U-shaped prompt layout.** Identity and critical alerts occupy the top of the context window; the current situation occupies the bottom. Background context (history, seasonal summary) fills the middle. This exploits the serial-position effect: primacy and recency regions receive higher attention weight in autoregressive models (Liu et al., 2023, "Lost in the Middle").
7. **The pause-inspect-unpause cycle is the fundamental rhythm.** The game pauses at each deliberation boundary, the governor observes and acts, and the game resumes. This is not continuous polling; it is discrete sense-decide-act.

---

## 2. Two-Tier Governance Loop

### Tier 1: Fast Loop (deterministic, every 2s, no LLM)

- Read bridge state via shared memory
- Tick suppression fields (cooldown timers on chain outputs)
- Evaluate threshold-based chains (crisis, resource, planner)
- Dispatch tactical commands to DFHack
- No context window, no token cost

This is the existing `_governance_loop` in `__main__.py`. It remains unchanged. All crisis response routes through Tier 1 to avoid LLM latency on time-critical events.

### Tier 2: Deliberation Loop (ReAct, per game-day, 1 LLM call)

Fires once per game-day (1200 ticks, approximately 12 seconds real-time at 100 ticks/s default speed). The deliberation loop runs a ReAct cycle (Yao et al., 2023) with constrained iteration depth and tool budget.

Procedure:

1. Read `FastFortressState` from bridge
2. Skip if `state.day == last_deliberation_day`
3. Generate 4 situation chunks via `ChunkCompressor`
4. Build U-shaped prompt (Section 5)
5. Execute ReAct loop: up to 3 Thought-Action-Observation iterations
6. Dispatch resulting commands to bridge
7. Record decisions in episode log

Constraints:
- Maximum 3 ReAct iterations per cycle
- Maximum 5 tool calls per cycle (from attention budget)
- Model: Claude Sonnet 4.6 via LiteLLM on `:4000`, route `fortress/daily`
- Hard timeout: 8 seconds (cancel and fall back to fast-loop-only if exceeded)

```python
async def _deliberation_loop(self):
    """Per-game-day LLM deliberation cycle."""
    while self._running:
        state = self._bridge.read_state()
        if state is None or state.day == self._last_deliberation_day:
            await asyncio.sleep(GOVERNANCE_INTERVAL)
            continue
        self._last_deliberation_day = state.day

        # Generate 4 situation chunks
        chunks = self._chunk_compressor.compress(state)

        # Build prompt
        prompt = build_deliberation_prompt(
            chunks=chunks,
            recent_events=self._recent_events[-5:],
            tools=OBSERVATION_TOOLS,
        )

        # ReAct loop (max 3 iterations)
        response = await self._llm_call(prompt, tools=OBSERVATION_TOOLS, max_iterations=3)

        # Execute resulting commands
        for action in response.actions:
            self._bridge.send_command(action.name, **action.params)
```

### Tier 3: Seasonal Review (narrative, per season, 1 Opus call)

Fires once per season (100,800 ticks). Performs a full fortress assessment with narrative synthesis.

- Model: Claude Opus 4.6, route `fortress/seasonal`
- Input: season summary (aggregated daily decisions, population changes, notable events, spatial memory snapshot)
- Output: episode narrative, goal revision, strategy adjustment
- Token budget: approximately 5,000 input, 2,000 output

The seasonal review does not issue commands directly. It updates the governor's goal state and strategic context, which the daily deliberation loop reads on subsequent cycles.

---

## 3. Chunk Compressor

The `ChunkCompressor` transforms `FastFortressState` (or `FullFortressState`) into exactly 4 natural-language chunks for the deliberation prompt.

### Fixed 4-chunk structure

```python
class ChunkCompressor:
    def compress(self, state: FastFortressState, prev_state: FastFortressState | None = None) -> list[str]:
        return [
            self._food_chunk(state, prev_state),      # Food/drink situation
            self._population_chunk(state, prev_state), # Population health
            self._industry_chunk(state, prev_state),   # Workshop/production status
            self._safety_chunk(state, prev_state),     # Military/threats/safety
        ]
```

Each chunk function:

1. Computes current value from state fields
2. Computes delta from `prev_state` (if available)
3. Determines severity: NOMINAL, WARNING, or CRITICAL
4. Generates one sentence, maximum 25 tokens

Examples at each severity level:

- NOMINAL: `"Food adequate (142 food, 89 drink, rising). Brewery active."`
- WARNING: `"Population stressed: 3 dwarves above threshold, 1 in strange mood."`
- NOMINAL: `"Industry idle: 6/8 workshops inactive. Mason waiting for stone."`
- NOMINAL: `"Safety clear. No threats. Military training (2 squads, 8 soldiers)."`

### Severity-based expansion

When a chunk reaches CRITICAL severity, it expands from 1 slot to 2-3 slots, displacing lower-priority chunks. Displacement follows a fixed priority ordering: safety > food > population > industry.

- CRITICAL food: chunk expands to include per-item breakdown, farm status, brewery status (2-3 slots)
- CRITICAL threats: chunk expands to include threat count, direction, military readiness, civilian positioning (2-3 slots)
- Displaced chunks are reduced to a 5-token summary (e.g., "Industry nominal." or "Population stable.")

This maintains the 4-slot working memory bound while redistributing resolution toward the most salient domain.

---

## 4. Observation Tools

### Existing tools (7)

| Tool | Tier | Budget cost | Description |
|------|------|-------------|-------------|
| `observe_region` | T2 | 1 | Spatial map observation centered on coordinates |
| `describe_patch` | T2 | 1 | Detailed description of a named patch |
| `check_stockpile` | T2 | 1 | Inventory query for a resource category |
| `scan_threats` | Free | 0 | Crisis interrupt, push-based |
| `examine_dwarf` | T2 | 1 | Individual unit detail (skills, mood, inventory) |
| `survey_floor` | T3 | 1 | Z-level overview (all patches on one level) |
| `check_announcements` | Free | 0 | Recent event stream from DFHack |

### New tools (5)

| Tool | Tier | Budget cost | Description |
|------|------|-------------|-------------|
| `check_military` | T2 | 1 | Squad readiness, equipment status, training progress |
| `check_nobles` | T2 | 1 | Noble positions, active mandates, unmet demands |
| `check_work_orders` | T2 | 1 | Active production orders and completion conditions |
| `recall_memory` | Free | 0 | Query spatial memory store without re-observing |
| `get_situation_chunks` | Free | 0 | Returns the 4 compressed situation chunks |

Free tools do not consume the attention budget. They provide cached or precomputed information. Budget-consuming tools trigger DFHack queries and update the spatial memory store.

---

## 5. Prompt Structure (U-shape)

The deliberation prompt follows a U-shaped layout to exploit serial-position attention effects (Liu et al., 2023).

```
[TOP — HIGH ATTENTION ZONE]
You are the governor of {fortress_name}, a dwarf fortress.
Your role: make strategic decisions about expansion, production, defense, and welfare.

CRITICAL ALERTS:
{alerts_if_any}

[MIDDLE — LOW ATTENTION ZONE]
RECENT HISTORY:
{last_3_days_of_decisions_and_outcomes}

SEASONAL CONTEXT:
{current_season_summary}

[BOTTOM — HIGH ATTENTION ZONE]
CURRENT SITUATION (Day {day}, {season} Year {year}):
1. {chunk_1}
2. {chunk_2}
3. {chunk_3}
4. {chunk_4}

What should we focus on today? Use your observation tools to investigate
if needed, then decide on actions.
```

Structural notes:
- Critical alerts appear at top to ensure they are never lost to middle-region attention decay.
- Seasonal context is placed in the middle because it changes infrequently and is background knowledge.
- The 4 situation chunks appear at the bottom (most recent tokens) where recency effects are strongest.
- Tool definitions are provided via the model's native tool-use schema, not inlined in the prompt.

---

## 6. Attention Budget

The attention budget constrains the number of budget-consuming tool calls per game-day deliberation cycle.

### Budget formula

```
budget = min(30, int(5 + 1.8 * sqrt(population)))
```

This yields approximately 8 queries for a 3-dwarf embark, 14 for a 25-dwarf fortress, and the cap of 30 for populations above 174. The square-root scaling reflects that larger fortresses have more to observe but observation effort does not scale linearly with population.

### Crisis override

When the fast loop detects an active crisis (siege, forgotten beast, cavern breach), the attention budget receives a +50% increase. All additional budget is allocated to safety-relevant tools (`scan_threats`, `observe_region` near threat, `check_military`).

### Normal allocation

In the absence of crisis, the budget is allocated across tiers:

- 40% Tier 2 routine (stockpile checks, workshop status, dwarf examination)
- 35% Tier 2 investigation (follow-up queries prompted by chunk anomalies)
- 25% Tier 3 strategic (floor surveys, spatial exploration of unobserved regions)

Budget resets at each game-day boundary. Unused budget does not carry over. This prevents hoarding and ensures consistent observation cadence.

---

## 7. Spatial Memory Integration

The existing `SpatialMemoryStore` (ACT-R base-level activation decay; Anderson & Lebiere, 1998) serves as the governor's long-term spatial knowledge. The deliberation loop interacts with it as follows:

1. **Chunk generation** reads current bridge state (not memory). Chunks are always fresh.
2. **`recall_memory(patch_id)`** is a free tool that returns the most recent cached description of a patch along with a confidence score derived from BLA. The governor uses this to decide whether re-observation is necessary.
3. **Observation tools** (budget-consuming) refresh memory. Each observation updates the SpatialMemoryStore entry for the relevant patch, resetting its activation.
4. **Consolidation**: Memories above the consolidation threshold (BLA > 0.3) are retained at full resolution. Memories between 0.1 and 0.3 are summarized to a single sentence.
5. **Forgetting**: Memories below the forget threshold (BLA < 0.1) are pruned from the store entirely. The governor must re-observe to recover knowledge of these regions.

This produces a natural attention-decay gradient: frequently observed areas (workshops, main hall) remain vivid; remote or disused areas (deep mines, abandoned corridors) fade unless actively revisited.

---

## 8. Menu vs Map Serialization

### Menu data (holistic retrieval)

When the deliberation loop invokes a menu-type tool (`check_stockpile`, `check_military`, `check_nobles`, `check_work_orders`), the tool returns the complete structured summary in a single response. No pagination, no partial views. The LLM processes the full list before deciding.

Example — `check_stockpile("food")` returns:

```
Food stocks (complete):
  Prepared meals: 45 (adequate)
  Raw plants: 89 (surplus)
  Meat: 12 (low)
  Fish: 3 (critical)
  Seeds: 34 (adequate)
  Drink: 23 (low — need 55 for population)
```

This mirrors how a human reads the stocks screen: the full list is visible at once, and attention is drawn to anomalous entries (low, critical) by severity labels.

### Map data (chunked retrieval)

When the deliberation loop invokes a spatial tool (`observe_region`, `describe_patch`, `survey_floor`), the tool returns a patch-based natural-language description with coordinate context. The LLM never receives tile grids, ASCII maps, or raw coordinate arrays.

Example — `observe_region(center_x=67, center_y=106, z=178, radius=5)` returns:

```
Region around (67,106,z178), radius 5:
  Workshop cluster (3 workshops: Still active, Kitchen idle, Craftsdwarf idle)
  Open corridor running north-south, width 3
  2 dwarves present: Urist McBrewer (brewing), Kadol Craftsdwarf (idle)
  Stone debris on 4 tiles (granite boulders)
```

This representation is semantically dense and LLM-compatible. Spatial relationships are expressed in natural language ("running north-south", "width 3") rather than coordinate pairs.

---

## 9. Token Budget

| Component | Tokens (approx.) | Cached across cycles? |
|-----------|------------------:|:---------------------:|
| System prompt + persona + rules | 800 | Yes |
| Tool definitions (12 tools) | 600 | Yes |
| 4 situation chunks | 200 | No |
| Recent history (3 days) | 400 | No |
| Seasonal context | 200 | No |
| ReAct iterations (model output) | 300 | No |
| Tool results (observation responses) | 200 | No |
| Final actions (model output) | 100 | No |
| **Total per daily cycle** | **~2,800** | |

### Model routing

| Loop | Route | Model | Rationale |
|------|-------|-------|-----------|
| Daily deliberation | `fortress/daily` | Claude Sonnet 4.6 | Low latency, sufficient reasoning for tactical decisions |
| Seasonal review | `fortress/seasonal` | Claude Opus 4.6 | High reasoning capacity for strategic assessment and narrative |
| Fast loop | N/A | Deterministic | No LLM involvement |

### Estimated cost

At 2,800 tokens input + 400 tokens output per daily cycle, with 400 game-days per year:

- Daily deliberation: approximately $4.53/game-year (Sonnet pricing)
- Seasonal review (4 per year, ~7,000 tokens each): approximately $0.80/game-year (Opus pricing)
- **Total: approximately $5.33 per game-year**

Prompt caching reduces effective input cost by approximately 40% for the system prompt and tool definitions.

---

## 10. Files Changed

### New files

| File | Purpose |
|------|---------|
| `agents/fortress/chunks.py` | `ChunkCompressor`, chunk functions, severity detection, delta computation |
| `agents/fortress/deliberation.py` | ReAct loop, prompt builder, LLM call wrapper, timeout handling |
| `agents/fortress/tools_registry.py` | Tool definitions for LLM tool-use (12 tools, schemas, descriptions) |

### Modified files

| File | Change |
|------|--------|
| `agents/fortress/__main__.py` | Add `_deliberation_loop` to `asyncio.gather` alongside existing `_governance_loop` |
| `agents/fortress/observation.py` | Add 5 new tool implementations (`check_military`, `check_nobles`, `check_work_orders`, `recall_memory`, `get_situation_chunks`) |
| `agents/fortress/config.py` | Add `DeliberationConfig` (model route, budget formula, timeout, max iterations) |
| `agents/fortress/spatial_memory.py` | Tune BLA thresholds per consolidation/forget parameters from this spec |

---

## 11. Scope Exclusions

This specification defines the perception and query layer. It does not address:

- **Governance chain logic.** The threshold-based chains remain deterministic. This spec adds LLM reasoning alongside the fast loop, not instead of it.
- **Narrative generation.** The seasonal review produces narratives, but the generation system is a separate concern not specified here.
- **Creativity system semantic injection.** The creativity activation system (see 2026-03-24-creativity-activation.md) injects naming and aesthetic decisions. Integration with the deliberation loop is deferred.
- **Perceptual chunking attention budget replacement.** This spec supersedes the attention budget defined in 2026-03-24-perceptual-chunking.md Section 5. The formula is retained; the enforcement point moves from the observation layer to the deliberation loop.

Crisis response always routes through the fast loop. The deliberation loop never handles time-critical events. If the 8-second timeout is exceeded, the cycle is cancelled and the fortress continues under fast-loop governance until the next game-day boundary.

---

## References

- Anderson, J. R., & Lebiere, C. (1998). *The Atomic Components of Thought*. Lawrence Erlbaum Associates.
- Cowan, N. (2001). The magical number 4 in short-term memory: A reconsideration of mental storage capacity. *Behavioral and Brain Sciences*, 24(1), 87-114.
- Itti, L., & Koch, C. (2001). Computational modelling of visual attention. *Nature Reviews Neuroscience*, 2(3), 194-203.
- Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., & Liang, P. (2023). Lost in the Middle: How Language Models Use Long Contexts. *arXiv:2307.03172*.
- Rensink, R. A. (2002). Change detection. *Annual Review of Psychology*, 53, 245-277.
- Reynolds, L., & McDonell, K. (2021). Prompt programming for large language models: Beyond the few-shot paradigm. *arXiv:2102.07350*.
- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. *ICLR 2023*.
