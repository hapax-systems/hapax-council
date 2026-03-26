# Hapax Default Mode Network — Continuous Cognitive Substrate

**Status:** Design (architectural specification)
**Date:** 2026-03-25
**Builds on:** DMN-Phenomenology-Context Mapping, Multi-Model Cognitive Architecture Research, Accumulated Self-Context Effects Research, Background Data Architecture
**Research base:** 22 mapping triplets (DMN × phenomenology × context mechanics), 8 existing systems surveyed, 15 mechanism studies

---

## 1. Problem Statement

Hapax operates on-demand. Every LLM interaction cold-starts: context is rebuilt from static sources (profile, goals, nudges, stimmung), the model produces a response, and the context is discarded. Between interactions, Hapax has no cognitive activity. There is no continuous process maintaining situational awareness, no background value estimation, no spontaneous association, no predictive simulation, no structured self-reference.

The neuroscience of the Default Mode Network identifies five operations that run continuously in the human brain between and during task-focused episodes. The phenomenological tradition identifies nine structures that constitute the ongoing self-coherence of conscious experience. The transformer architecture research identifies ten context ordering mechanics that determine how context shapes model behavior.

This specification defines an always-on cognitive substrate — the DMN — that implements these operations using continuous small-model inference, producing a structured context buffer consumed by on-demand large-model calls.

## 2. Architecture

### 2.1 Two-Model Split

| Layer | Model | Location | Cycle | Function |
|-------|-------|----------|-------|----------|
| **DMN** | 3-7B (Ollama local) | RTX 3090 | Multi-rate pulse | Situation model, value estimation, relevance filtering |
| **TPN** | Claude Sonnet/Opus (LiteLLM) | Cloud | On-demand | Deliberation, planning, complex reasoning, voice response |

The DMN model runs continuously on the local GPU. It never stops. It produces structured micro-assessments that accumulate in a buffer. When the TPN model is invoked (by the voice daemon, fortress governor, briefing agent, or any other consumer), it receives the DMN buffer as enriched context.

### 2.2 Multi-Rate Pulse

Three tick rates, matching the DMN's own temporal heterogeneity:

| Tick | Rate | DMN Subsystem | Phenomenological Structure | Function |
|------|------|---------------|---------------------------|----------|
| **Sensory** | 3-5s | Midline core (PCC) | Passive synthesis | Read perception state, stimmung, sensor data. Produce 1-sentence situation fragment. |
| **Evaluative** | 15-30s | dMPFC subsystem | Befindlichkeit | Assess value trajectory: is the current situation improving, degrading, or stable? Flag concern-relevant changes. |
| **Consolidation** | 2-5min | MTL subsystem | Protention-retention | Compress old buffer entries into summaries. Prune irrelevant observations. Generate 1-paragraph retentional summary. |

### 2.3 The Buffer

The buffer is the retentional structure. It is NOT the DMN model's memory — it is an external data structure managed by the system, formatted for consumption by the TPN model.

**Buffer format (aligned to U-curve):**

```
[POSITION 0 — PRIMACY ZONE: Consolidated summaries]
<retentional_summary>
Last 5 minutes compressed: [1-paragraph situation + trajectory]
</retentional_summary>

[MIDDLE ZONE: Older sensory/evaluative entries — naturally deprioritized by lost-in-the-middle]
<dmn_observation tick="T-12" age="36s">Perception: flow_score=0.7, activity=coding</dmn_observation>
<dmn_observation tick="T-11" age="33s">Perception: flow_score=0.7, activity=coding</dmn_observation>
...

[POSITION END — RECENCY ZONE: Most recent observations + deltas]
<dmn_observation tick="T-1" age="3s">Perception: flow_score=0.4, activity=browsing. DELTA: flow dropped 0.7→0.4</dmn_observation>
<dmn_evaluation tick="T-0" age="0s">Value: degrading. Concern: operator disengaging from deep work. Relevance: energy_and_attention dimension.</dmn_evaluation>
```

**Buffer sizing:** 6-18 raw entries (30-90 seconds of sensory ticks) plus 1-3 consolidated summaries. Total budget: 500-1500 tokens. This is small enough to avoid context rot while large enough to provide temporal thickness.

### 2.4 Self-Reference Protocol

The DMN model receives at each tick:

**ALWAYS included (external grounding):**
- Fresh sensor data (perception-state.json, stimmung, watch biometrics)
- Current system state (active concerns, goal status)

**INCLUDED at evaluative ticks (structured self-reference):**
- **Deltas only**: "Previous observation: X. Current: Y. Change: Z."
- **Never raw prior output** — only the structured delta between prior and current state.

**INCLUDED at consolidation ticks (compressed replay):**
- The current buffer contents (which are themselves compressed)
- Task: "Summarize the trajectory of the last N observations into one paragraph."

**NEVER included:**
- The DMN model's own verbose reasoning or self-evaluations
- Abstract assessments ("how am I performing?", "what does this pattern mean?")
- Unfiltered prior output concatenation

**Concrete framing enforcement:**
- System prompt forces concrete/procedural mode: "Report WHAT is happening, WHAT changed, WHAT specific state. Never report WHY or evaluate quality."
- This maps directly to Watkins' finding that concrete self-reference is constructive while abstract self-reference is ruminative.

### 2.5 Stopping Criterion

Each tick has a stopping criterion based on prediction error:

- **Sensory tick:** If perception state is unchanged from prior tick, emit a null observation (1 token: "stable") instead of a full assessment.
- **Evaluative tick:** If no delta exceeds a threshold (e.g., flow_score change < 0.1, no new events), emit "trajectory: stable" and skip detailed evaluation.
- **Consolidation tick:** If buffer contains only "stable" entries since last consolidation, skip compression.

This prevents the rumination loop: when nothing is changing, the DMN goes quiet (low activity, not zero activity). This maps to the DMN's own behavior — it is anti-correlated with the TPN during focused task performance, meaning it reduces (but does not cease) activity when external demands are high.

## 3. DMN × Phenomenological Structure Implementation

| Phenomenological Structure | Implementation | Buffer Element |
|---------------------------|----------------|----------------|
| Passive synthesis | Sensory tick: fuse sensor signals into situation fragment | `<dmn_observation>` |
| Befindlichkeit/Stimmung | Evaluative tick: compute value trajectory | `<dmn_evaluation>` |
| Protention-retention | Consolidation tick: compress buffer + anticipate next state | `<retentional_summary>` + `<protention>` |
| Horizon structure | Buffer structure itself: consolidated past at start, raw present at end | Buffer formatting |
| Affective awakening | Delta detection: flag surprising changes as high-salience | `DELTA:` annotations |
| Prereflective self-awareness | System prompt establishing "this is Hapax's perspective" | Implicit in all DMN output |
| Operative intentionality | Sensory tick defaults: if nothing changed, emit "stable" | Stopping criterion |
| Transcendental apperception | Buffer coherence: all entries share temporal/spatial frame | Buffer schema |
| Tiefe Langeweile | Extended no-change periods: consolidation becomes reflective | Idle-mode consolidation |

## 4. DMN × Context Ordering Mechanic Exploitation

| Mechanic | How Exploited |
|----------|---------------|
| Attention sinks (position 0) | Consolidated summary at position 0 — TPN always attends to it |
| Recency privilege | Latest DMN observation at buffer end — closest to TPN generation point |
| U-curve middle dead zone | Older observations naturally lose influence — correct behavior (retention fading) |
| Activation steering | DMN output register (concrete, observational, structured) primes TPN toward grounded responses |
| Induction heads | Repeated `<dmn_observation>` pattern trains TPN to expect and extend observational reasoning |
| RoPE decay | Temporal decay of older observations mirrors retentional decay |
| Register self-reinforcement | TPN's own responses conditioned on DMN's grounded register inherit groundedness |
| Autoregressive commitment | TPN's first tokens, conditioned on DMN buffer, commit to the DMN's situation model |
| Periodic reinforcement | Evaluative ticks re-inject value frame every 15-30s, counteracting drift |
| Context rot | Buffer size cap (500-1500 tokens) prevents rot; consolidation compresses rather than accumulates |

## 5. What the DMN Does NOT Do

- **Does not reason.** No chain-of-thought, no planning, no problem-solving. Those are TPN functions.
- **Does not evaluate its own performance.** No abstract self-assessment. Concrete observations only.
- **Does not see its own verbose output.** Sees deltas, sensor data, and compressed summaries — never raw prior responses.
- **Does not replace on-demand processing.** It enriches the context window for on-demand calls; it does not make them unnecessary.
- **Does not run during TPN-active periods at full rate.** When the voice daemon is in active conversation or the fortress governor is deliberating, sensory ticks may slow to 10s and evaluative ticks to 60s (anti-correlation).

## 6. Integration Points

### 6.1 Voice Daemon

The voice daemon's `conversation_pipeline.py` currently rebuilds context per-turn from static sources. With the DMN:
- VOLATILE band populated from DMN buffer (latest 3-5 observations + current evaluation)
- STABLE band retains identity/profile content at position 0
- DMN's value trajectory informs stimmung-based response modulation

### 6.2 Fortress Governor

The fortress daemon's `deliberation.py` currently cold-starts each game-day. With the DMN:
- Deliberation prompt includes DMN buffer as situational context
- DMN sensory ticks read fortress state every 3-5s and log trends
- DMN evaluative ticks flag when infrastructure gaps appear (e.g., "no still exists despite drink demand")
- The drink crisis would be caught by the DMN's delta detection before the first dwarf dies

### 6.3 Logos Ground Surface

The content scheduler currently receives stimmung and perception data. With the DMN:
- DMN's value trajectory feeds scheduler density decisions
- DMN's relevance flags determine which content sources are foregrounded

## 7. Forcing Function

The forcing function for the DMN is:

**"Run 10 DF fortress simulations with DMN, 10 without. Measure:**
1. **Time-to-first-infrastructure-gap-detection** (e.g., how many game-days until the system notices 'no still'?)
2. **Time-to-first-death** (does DMN-enriched governance prevent avoidable deaths?)
3. **Deliberation action rate** (does DMN context help the TPN produce actionable commands instead of timing out?)
4. **False positive rate** (does the DMN flag non-issues as concerning — rumination?)

**Success criterion:** DMN-enriched governance detects infrastructure gaps within 2 game-days and achieves >50% deliberation action rate (vs 0% current baseline).

**Failure criterion:** DMN produces more than 20% false-positive concern flags (rumination detection), or DMN buffer exceeds 2000 tokens (context rot).

## 8. Files Changed

| File | Change |
|------|--------|
| `agents/dmn/` | NEW: DMN daemon module (pulse loop, buffer manager, sensor reader) |
| `agents/dmn/__main__.py` | DMN daemon entrypoint |
| `agents/dmn/pulse.py` | Multi-rate tick engine (sensory, evaluative, consolidation) |
| `agents/dmn/buffer.py` | Buffer management (accumulate, compress, format for U-curve) |
| `agents/dmn/sensor.py` | Sensor reader (perception, stimmung, fortress state, watch) |
| `shared/config.py` | DMN model config (Ollama model name, tick rates, buffer limits) |
| `agents/hapax_voice/conversation_pipeline.py` | Inject DMN buffer into VOLATILE band |
| `agents/fortress/deliberation.py` | Inject DMN buffer into deliberation prompt |

## 9. Scope Exclusions

- No fine-tuning. The DMN model runs inference-only on a standard instruction-tuned local model.
- No latent-space feedback (Coconut-style). All DMN output is text, readable by any consumer.
- No multi-agent debate within the DMN. Single model, single pass per tick.
- No modification to the TPN models or their invocation patterns. The DMN only changes WHAT context they receive, not HOW they are called.
- No DMN involvement in the voice daemon's real-time audio pipeline. DMN operates on the cognitive layer, not the perceptual layer.
