# Background Data Architecture — System-Wide Template for Cognitive Data Consumption

**Status:** Design (architectural specification)
**Date:** 2026-03-24
**Builds on:** Voice daemon reference architecture, Hapax data audit, Context system, Agent-environment boundary analysis

## 1. Problem Statement

Hapax operates comprehensive data collection infrastructure: 41 systemd timers, 10+ sync agents, 8 Qdrant collections, real-time perception via camera feeds and biometric sensors, and a reactive engine monitoring filesystem state. The data production side functions correctly. The data consumption side does not.

The voice daemon consumes data through a coherent architecture: dual-band context with per-turn rebuild, concern-weighted salience thresholds, progressive fidelity rendering, and continuous cognition. This architecture emerged from grounding research and represents the most mature consumer in the system.

Other consumers — briefing, nudges, content scheduler, fortress governor — each implement data consumption differently, with varying degrees of staleness awareness, no shared context management, and no common patterns for LLM prompt construction.

Three critical gaps define the current state:

1. **Grounding quality isolation.** The voice daemon computes GQI (Grounding Quality Index) continuously, but this value never flows to stimmung. The cognitive dimension of the operator profile reflects conversational grounding quality with 24+ hour latency, or not at all.

2. **Dead collections.** Two Qdrant collections (`claude-memory`, `samples`) are defined in the expected schema but have never received a single write. They occupy configuration space and create false expectations in health checks.

3. **Voice as an island.** The voice daemon has no access to pending nudges, operator goals, or health escalation signals. It operates with high-quality conversational context but zero awareness of the broader system state that surrounds the operator.

## 2. Five Reusable Patterns

The voice daemon's architecture contains five patterns that generalize to all cognitive consumers. This section defines each pattern abstractly, independent of the voice domain.

### Pattern 1: Dual-Band Context Management

Every LLM-calling system in Hapax maintains two context bands:

- **STABLE band.** Contains identity, history, established pacts, and operator preferences. This band survives context rebuilds. It changes only when the underlying facts change (profile update, new pact, identity revision). Rebuild frequency: minutes to hours.

- **VOLATILE band.** Contains environment state, active policies, salience signals, and temporal context. This band is rebuilt every cognitive cycle (turn, tick, or scheduled interval depending on the system). Rebuild frequency: seconds to tens of seconds.

**Deduplication.** Each band maintains a content hash of its most recent build. If a rebuild produces an identical hash, the downstream LLM call receives no context update. This prevents unnecessary token consumption and avoids confusing the model with repeated identical context blocks.

**Rebuild cadence.** The cognitive cycle period varies by system:
- Voice daemon: per-turn (1-10s)
- Visual layer aggregator: per-tick (3s)
- Fortress governor: per-game-day (~30s real-time)
- Briefing: per-invocation (on-demand)
- Nudges: per-evaluation (60s timer)

All Hapax cognitive systems that call an LLM MUST use dual-band context management.

### Pattern 2: Phenomenal Context as Progressive Fidelity Layers

Context describing the operator's current phenomenal state (perception, mood, environment, temporal orientation) is structured as six progressive layers:

| Layer | Content | Condition |
|-------|---------|-----------|
| 1 | Stimmung | Non-nominal only. Empty when calm. |
| 2 | Situation coupling | Operator state + environment in one phrase. |
| 3 | Temporal impression | Present moment + direction of change. |
| 4 | Surprise / deviation | Prediction errors only. Omitted when expectations hold. |
| 5 | Temporal depth | Retention (recent past texture) + protention (anticipated near future). |
| 6 | Self-state / apperception | System's awareness of its own cognitive state. |

**Tier-dependent cutoff.** LOCAL-tier models receive layers 1-3. CAPABLE-tier models receive all 6. This prevents overloading small models with context they cannot use productively.

**Upstream compression.** Each layer's source is responsible for self-compression. A calm stimmung produces no output, not a verbose description of calmness. A stable temporal impression produces a terse summary, not a detailed account of non-change. The renderer is faithful: it passes through what sources emit without further compression.

### Pattern 3: Perception Engine with Pluggable Backends

Data ingestion follows a backend-plugin architecture:

```
PerceptionBackend protocol:
    name: str                           # unique identifier
    provides: set[str]                  # namespace of behaviors produced
    tier: Literal["FAST", "SLOW", "EVENT"]  # update cadence class
    available: bool                     # runtime capability check
    contribute(state) -> dict           # produce behaviors
    start() / stop()                    # lifecycle management
```

**Conflict detection.** Two backends declaring overlapping `provides` namespaces are rejected at registration time. This prevents ambiguous data provenance.

**Behavior\[T\].** Every value produced by a backend is wrapped in a `Behavior[T]` container carrying:
- The value itself (typed)
- A timestamp of production
- A watermark defining maximum acceptable staleness

**Fusion.** The perception engine orchestrates backends but does not merge their outputs. Each backend is independently testable. Consumers read behaviors by namespace key and check staleness against watermarks.

### Pattern 4: Grounding Ledger with Concern-Modulated Thresholds

Conversational grounding (mutual understanding verification) follows a state machine:

```
Discourse Unit states: PENDING -> GROUNDED | REPAIR | ABANDONED | CONTESTED | UNGROUNDED
```

**Grounding Quality Index (GQI).** A composite score computed as:
- 50% EWMA of acceptance rate (grounded / total DUs)
- 25% trend (direction of change over recent window)
- 15% negative evidence penalty (explicit rejections, repairs)
- 10% engagement signal (backchannels, elaborations)

**Threshold modulation.** The repair threshold is not fixed. It is modulated by `concern_overlap x GQI`, where concern_overlap measures how closely the current topic aligns with the operator's active concerns. High-concern topics with low GQI trigger repair at lower thresholds.

**Effort calibration.** Response effort level is computed as `activation x (1 - GQI x 0.6)`, mapping to three bands:
- EFFICIENT (GQI > 0.7, low activation): terse, no elaboration
- BASELINE (default): standard response depth
- ELABORATIVE (GQI < 0.4 or high activation): expanded, with grounding markers

**Hysteresis.** Escalation (toward more effort, more repair) is immediate. De-escalation is damped: GQI must sustain improvement for multiple cycles before effort drops.

### Pattern 5: Salience-Based Routing with Dual-Attention Activation

Model selection and response depth are driven by salience, not by fixed rules or keyword matching.

**Two attention channels:**
- **Top-down (dorsal).** Concern overlap: cosine similarity between the current input and the operator's concern graph (a weighted set of active topics, goals, and preoccupations). This represents what the operator cares about.
- **Bottom-up (ventral).** Novelty: `1 - max_sim(input, anchors + recent_utterances)`. This represents what is unexpected or new.

**Dialog features.** Structural cues modify activation: meta-questions (questions about the conversation itself), commands (direct instructions), hedges (uncertainty markers), and pre-sequences (topic-shift announcements) each carry activation weights.

**Activation computation.** `activation = w_concern * concern_overlap + w_novelty * novelty + w_dialog * dialog_features`, mapped to tier selection with governance overrides (e.g., axiom violations always escalate to CAPABLE).

**Hysteresis.** De-escalation is damped: maximum one tier drop per cognitive cycle. Escalation is immediate.

## 3. Current Compliance Matrix

| Consumer | Dual-Band | Per-Tick Refresh | State Machine | Staleness Awareness | Status |
|----------|-----------|-----------------|---------------|---------------------|--------|
| voice daemon | Yes | Yes | Yes (grounding, temperature, turn phase) | Yes | REFERENCE |
| visual_layer_aggregator | Yes | Yes | Yes (display state) | Yes | COMPLIANT |
| fortress governor | Yes (fast + deliberation) | Yes | Yes (events, goals) | Partial | MOSTLY COMPLIANT |
| content_scheduler | Partial | Yes | Yes (selection history) | No absolute veto | PARTIAL |
| nudges | No | Partial | No | Yes (age checks) | PARTIAL |
| briefing | No | No | No | Partial | NON-COMPLIANT |

**REFERENCE** indicates the system from which patterns were extracted. **COMPLIANT** indicates full implementation of all five patterns. **MOSTLY COMPLIANT** indicates implementation with minor gaps. **PARTIAL** indicates some patterns present but structural gaps remain. **NON-COMPLIANT** indicates no pattern adoption.

## 4. Cross-System Wiring Gaps

Ten gaps were identified through data flow tracing. Each gap represents a producer-consumer pair where the data path is broken, missing, or incomplete.

| # | Gap | From | To | Impact | Fix |
|---|-----|------|----|--------|-----|
| 1 | GQI does not reach stimmung | voice `grounding-quality.json` | `visual_layer_aggregator` | Cognitive dimension stale 24h+ | Wire read path in aggregator |
| 2 | Watch biometrics may not reach stimmung | watch backend | stimmung `operator_stress` | Biometric dimension may not flow | Verify watch-to-stimmung path |
| 3 | Nudge urgency invisible to voice | nudges API | voice context | Voice unaware of pending actions | Inject nudge summary into VOLATILE band |
| 4 | Operator goals invisible to voice | goals API | voice context | Voice cannot relate to objectives | Inject goal summary into STABLE band |
| 5 | Content scheduler ignores voice state | scheduler state | voice session | Scheduler does not pause during active voice | Add voice-active gate to scheduler |
| 6 | Temporal bands may not reach phenomenal context | `temporal/bands.json` | phenomenal context renderer | Layers 3-5 may render stale data | Verify read path and staleness |
| 7 | Reactive engine effects do not cascade | rule outputs | downstream triggers | Rule consequences not propagated | Add cascade trigger mechanism |
| 8 | Corrections not fed back to profiler | `correction_synthesis` | `profiler` | Operator corrections not learned | Wire correction output as profiler input |
| 9 | Knowledge gaps not surfaced as nudges | `knowledge_sufficiency` | nudges | Computed gaps never presented to operator | Add nudge source for knowledge gaps |
| 10 | Health escalation cannot interrupt voice | `health_monitor` | voice interrupt | Critical health status not surfaced in conversation | Add interrupt pathway for critical events |

## 5. Dead and Stale Data Cleanup

| Collection / Source | Status | Action |
|---------------------|--------|--------|
| `claude-memory` (Qdrant) | Never written. No agent produces data for this collection. | Remove from `EXPECTED_COLLECTIONS`. |
| `samples` (Qdrant) | Never written. No agent produces data for this collection. | Remove from `EXPECTED_COLLECTIONS`. |
| `axiom-precedents` (Qdrant) | Seed data not confirmed present. | Verify seed loading pipeline, add automatic recording of axiom invocations. |
| `operator-patterns` | Extraction trigger unclear. | Document trigger conditions. Verify execution schedule. |
| `studio-moments` (Qdrant) | Written by studio compositor. No reader consumes these embeddings. | Add reader or document intended future consumer. |
| Fortress chronicle | Written by fortress narrator. No consumer reads the output. | Will be consumed by fortress narrative query system (spec exists). |
| AV correlator output | Produced by perception pipeline. Not consumed downstream. | Evaluate whether output serves any active use case. Remove if not. |
| Flow journal entries | Logged by flow detection. Not aggregated into any profile dimension. | Feed to `energy_and_attention` profile dimension via profiler. |

## 6. Priority Implementation Phases

### Phase 1: Fix Critical Wiring (immediate)

1. Wire GQI to stimmung (gap #1). Verify that `visual_layer_aggregator` reads `grounding-quality.json` from the voice daemon's output directory and maps the value to the cognitive dimension.
2. Remove dead Qdrant collections (`claude-memory`, `samples`) from `EXPECTED_COLLECTIONS` in schema definition.
3. Wire flow journal entries to the `energy_and_attention` profile dimension (subset of gap #8).
4. Fix perception ring depth = 0 condition that causes temporal bands to produce empty output.

### Phase 2: Voice Context Enrichment (near-term)

5. Inject operator goals summary into voice STABLE band (gap #4).
6. Inject pending nudge summary into voice VOLATILE band (gap #3).
7. Add health escalation interrupt pathway to voice daemon (gap #10).
8. Verify temporal bands read path into phenomenal context renderer (gap #6).

### Phase 3: Cross-System Cascades (medium-term)

9. Add cascade trigger mechanism to reactive engine rule outputs (gap #7).
10. Wire correction synthesis output to profiler as fact source (gap #8).
11. Add knowledge gap detection as nudge source (gap #9).
12. Add voice-active gate to content scheduler (gap #5).

### Phase 4: Compliance Upgrades (longer-term)

13. Refactor `briefing.py` to continuous pattern with per-source staleness tracking and dual-band context.
14. Refactor `nudges.py` to parallel collection with fast/slow source separation.
15. Add absolute staleness veto to `content_scheduler.py` (refuse to present content with stale backing data).

## 7. Shared Library Scope

The following components are extracted from the voice daemon into `shared/cognitive/` for reuse by all consumers:

- **`context_manager.py`** — `ContextManager` class implementing dual-band rebuild with content-hash deduplication. Parameterized by rebuild cadence and band definitions.
- **`phenomenal_renderer.py`** — `PhenomenalContextRenderer` implementing progressive fidelity layers with tier-dependent cutoff. Parameterized by layer sources and tier mapping.
- **`data_source.py`** — `DataSource` protocol defining the interface for reading JSON state files with staleness checking (timestamp + watermark).

The following components remain in the voice daemon (too domain-specific for extraction):

- **GroundingLedger.** Conversational grounding is specific to dialog systems. Other consumers do not maintain discourse unit state machines.
- **SalienceRouter.** The concern graph and dual-attention activation model are specific to real-time conversational routing. Other consumers use fixed scheduling or simpler priority schemes.
- **PerceptionEngine.** The backend-plugin architecture is already defined as a shared pattern. The voice daemon holds the reference implementation. Other consumers may implement their own backends conforming to the same protocol.

## 8. Files Changed

### Phase 1

| File | Change |
|------|--------|
| `shared/qdrant_schema.py` | Remove `claude-memory` and `samples` from `EXPECTED_COLLECTIONS`. |
| `agents/visual_layer_aggregator.py` | Verify and wire GQI read path from `grounding-quality.json`. |
| `agents/profiler.py` | Add flow journal as fact source for `energy_and_attention` dimension. |
| `agents/temporal_scales.py` | Fix ring depth calculation that produces depth = 0. |

### Phase 2

| File | Change |
|------|--------|
| `agents/hapax_voice/conversation_pipeline.py` | Inject operator goals (STABLE) and pending nudges (VOLATILE) into context bands. |
| `agents/hapax_voice/phenomenal_context.py` | Verify temporal bands read path for layers 3-5. |
| `agents/health_monitor.py` | Add voice interrupt emission on critical health status. |

### Phase 3

| File | Change |
|------|--------|
| `logos/engine/reactive_rules.py` | Add cascade trigger mechanism for rule outputs. |
| `agents/correction_synthesis.py` | Wire output to `agents/profiler.py` as fact source. |
| `logos/data/nudges.py` | Add `knowledge_sufficiency` as nudge source. |
| `agents/content_scheduler.py` | Add voice-active gate (check voice daemon state before presenting content). |

## 9. Success Criteria

The system is correctly wired when the following conditions hold:

1. All stimmung dimensions are fresh (< 120s) during active sessions. No dimension reports data older than two minutes when the operator is present and the system is running.

2. The voice daemon has access to operator goals, pending nudges, and health status within its context bands. These appear in the STABLE and VOLATILE bands respectively and are verifiable in context dumps.

3. No Qdrant collections exist that are never written or never read. Every collection in `EXPECTED_COLLECTIONS` has at least one producer and at least one consumer.

4. Every data producer has at least one active consumer. No agent writes output that is never read by any downstream process.

5. Cross-system state changes propagate within one cognitive cycle (3-12s depending on the consumer's tick rate). A change in one agent's output is visible to dependent agents within one cycle.

6. All LLM-calling agents use dual-band context management. No agent constructs prompts by ad-hoc string concatenation of state files. Context construction follows the ContextManager protocol with hash-based deduplication.
