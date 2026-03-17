# WS1: Temporal Structure Engineering for LLM Perceptual Systems

**Date**: 2026-03-16
**Status**: Research synthesis — Workstream 1 of phenomenological engineering project
**Depends on**: [LLM-Phenomenology Mapping Research](llm-phenomenology-mapping-research.md) (Thread A2)
**Sources**: 80+ papers and articles, 2022-2026

---

## 1. Problem

A perceptual system that merely snapshots current state fails a basic phenomenological requirement: temporal thickness. Husserl demonstrated that the experienced present is never a point — it is a three-phase structure:

- **Retention**: fading trace of the just-past, still present as modification of the now
- **Primal impression**: current input fused with expectation, not raw data
- **Protention**: anticipatory readiness for likely next states, shaped by concern

This structure is not philosophical decoration. Without it, a melody becomes a sequence of disconnected tones, a gesture becomes a series of unrelated positions, and context collapses into a flat snapshot. Active inference research has formalized this: the belief state at any moment is computed as a softmax over log-probabilities of protention (prior/forward), primal impression (predicted/backward), and retention (likely outcome) — what Sandved-Smith et al. (2023) call "living inferences" because they jointly constitute the phenomenological living present through computational mechanisms.

LLMs process tokens in a context window where all positions are simultaneously available during attention computation. There is no intrinsic temporal flow. But positional encodings (particularly RoPE) create geometric differences based on position, and the input formatting layer is fully under our control. The thesis of this workstream: **temporal structure can be engineered INTO the input such that the model's processing respects temporal topology, without modifying the model.**

---

## 2. Prior Art

### 2.1 RoPE and Natural Temporal Gradients

Rotary Position Embedding (Su et al., 2021) encodes each token's absolute position as a rotation in multiple cosine-sine planes. The position-dependent part of attention scores always appears as a function of (m - n), the relative distance between query position m and key position n. This has a critical property: **attention naturally decays with distance**.

The dot product between two rotated versions of the same vector equals cos(angle_difference). As the angle difference increases, cosine decreases, so attention scores decrease. RoPE uses multiple rotation frequencies: fast rotations capture short-range dependencies while slow rotations decay slowly to capture long-range dependencies. The combination gives the model rich information about both nearby and distant tokens.

This "long-term decay" property has been experimentally confirmed across models (Llama2-7B, Baichuan2-7B) during both pre-training and fine-tuning (NeurIPS 2024, "Base of RoPE Bounds Context Length"). It is not an artifact — it is an architectural inductive bias toward recency.

**Engineering implication**: If we place retention tokens BEFORE primal impression tokens BEFORE protention tokens in the input sequence, RoPE's natural decay means:
- Retention tokens receive progressively lower attention (fading trace — exactly what Husserl describes)
- Primal impression tokens occupy the high-attention recent positions
- Protention tokens at the very end receive maximum attention from the generation head

This is not a hack. The geometry of RoPE *already implements a retention gradient*. We just need to format input to exploit it.

### 2.2 ALiBi: Explicit Linear Decay

ALiBi (Press et al., 2021) takes a more explicit approach: instead of encoding position by rotating Q and K vectors, it directly subtracts a linearly increasing penalty from attention logits based on token distance. Different heads decay at different rates — some heads attend locally, others globally.

ALiBi's advantage over RoPE for temporal engineering: the decay is explicit, predictable, and head-diverse. Its disadvantage: fewer models use it (RoPE dominates in Llama, Mistral, Qwen, DeepSeek). For models using ALiBi (e.g., Falcon, BLOOM), temporal structure gets a cleaner implementation.

### 2.3 The "Lost in the Middle" Problem

Liu et al. (2024, TACL) demonstrated that LLMs exhibit a U-shaped attention bias: tokens at the beginning and end of context receive higher attention regardless of relevance, while middle content is systematically neglected. Measurements showed 30%+ accuracy drops when relevant information moved from position 1 to position 10 in a 20-document context.

The root cause is RoPE's long-term decay combined with the causal attention mask's recency bias. Recent work on "Found in the Middle" (ACL Findings 2024) proposes calibration mechanisms that achieve up to 15 percentage point improvements.

**Engineering implication**: The U-shaped curve is a problem for flat input, but a *feature* for temporally structured input. If we want retention to fade and the current moment to be vivid, the natural attention distribution already does this. We should:
- Place retention at the beginning (high initial attention, but fading as context grows)
- Place primal impression in the recent positions (recency bias = vividness)
- Place protention at the very end (end-of-sequence attention boost)

The "lost in the middle" zone becomes the natural home for lower-salience background context.

### 2.4 Context Rot

Chroma Research (2025) documented "context rot" — systematic performance degradation as input length increases, even on simple tasks. Key findings:
- Performance degrades non-linearly with input length
- Position accuracy degrades substantially beyond ~2,500 tokens
- Logically coherent haystacks perform *worse* than shuffled versions (surprising)
- What matters is how information is presented, not just its presence

This confirms that naive context stuffing is counter-productive. Temporal structuring is not optional — it is necessary to avoid context rot in perception systems that accumulate state over time.

### 2.5 Structured Input Formatting

Research on prompt formatting (2024-2025) consistently shows that clear structure matters more than clever wording. XML tags create clear boundaries that prevent different parts of the prompt from mixing, which is critical for maintaining temporal separation. A study evaluating six prompting styles across GPT-4o, Claude, and Gemini found that format choice significantly affects processing, though simpler formats often match complex ones in accuracy.

Anthropic's own documentation recommends XML-structured prompts for Claude, which aligns perfectly with temporal band formatting:

```xml
<retention confidence="0.7" age_seconds="45">
  Operator was in deep flow state, working on code editor
  Emotion: focused, valence=0.3, arousal=0.4
  Scene: home office, single person, overhead lighting
</retention>

<primal_impression timestamp="2026-03-16T14:30:00Z">
  Face count: 1, operator present
  Gaze: toward secondary monitor
  Posture: leaning forward
  Activity: browsing (tab switch detected)
  Flow score: 0.35 (declining from 0.6)
  Audio: quiet keyboard, no speech
</primal_impression>

<protention basis="flow_decline + tab_switch">
  Likely transition: flow → browsing within 60s
  Break probability: 0.4 (based on 45min session length)
  If break: music genre shift appropriate
  If continued browsing: reduce visual layer to ambient
</protention>
```

### 2.6 Counterfactual and Hypothetical Reasoning (Protention Engineering)

LLMs can process hypothetical content, but research reveals significant limitations. A decompositional study (2025) found that LLMs "often struggle with counterfactual reasoning and frequently fail to maintain logical consistency or adjust to context shifts." CounterBench (2025) provides systematic evaluation, showing models handle common causal scenarios better than novel ones.

However, for protention engineering, we do not need full counterfactual reasoning. We need the model to treat anticipated states as *less certain* than observed states and to use them for readiness rather than action. Key techniques:
- **Explicit uncertainty marking**: "likely transition (p=0.4)" vs. stated facts
- **Conditional framing**: "if X then Y" keeps hypotheticals separate from assertions
- **Attention-layer separation**: protention tokens at specific positions get different attention patterns than factual tokens due to positional encoding

Research on in-context learning shows that counterfactual reasoning relies on copying in-context observed values through induction heads (self-attention mechanism). This means protention tokens that structurally resemble factual tokens but are marked as hypothetical may still influence reasoning through attention, even without full counterfactual capability.

### 2.7 Hierarchical Temporal Memory

Active inference proposes hierarchical temporal processing where higher levels encode more abstract and longer-term predictions: soundwaves → phonemes → syllables → words → sentences → biographies. For LLM perception systems, this maps to:

- **Millisecond scale**: Raw sensor readings (audio frames, pixel values) — below LLM resolution
- **Second scale**: Perception state snapshots (face detection, VAD, emotion) — the primal impression
- **Minute scale**: Activity modes, flow states, session patterns — retention band
- **Hour scale**: Daily rhythms, work patterns, energy cycles — deep context
- **Day+ scale**: Profile facts, preferences, habits — persistent knowledge (Qdrant)

Recent architectures address this:

**H-MEM** (2025): Hierarchical memory with four layers (Domain → Category → Memory Trace → Episode), using position indexing to search layer by layer.

**ContextLM** (2025, ICLR 2026): Partitions tokens into non-overlapping chunks, each summarized into a context embedding. A Context Predictor applies a one-chunk shift, predicting context embeddings based solely on past context embeddings — a direct computational analogue of protention.

**EM-LLM**: Replaces standard attention with discrete retrieval of contiguous episode representations without fine-tuning. Episodes are temporal chunks, not random access.

**Zep/Graphiti** (Rasmussen, 2025): A temporal knowledge graph for agent memory using a bi-temporal model — T (event timeline, when things happened) and T' (transaction timeline, when the system learned about them). Tracks four timestamps per edge: t'_created, t'_expired, t_valid, t_invalid. This is exactly the versioned-fact structure needed for retention decay: facts don't disappear, they get invalidated by newer observations.

**Mem0** (2025): Scalable memory architecture achieving 26% improvement over OpenAI baselines by dynamically extracting, consolidating, and retrieving salient information. Graph-based variant captures relational structure among conversational elements.

### 2.8 Sensor-to-LLM Perception Pipelines

Two systems directly address feeding sensor data to LLMs:

**IoT-LLM** (2024-2025): Three-step framework — (1) preprocess IoT data into LLM-amenable formats (data simplification and enrichment), (2) expand knowledge via IoT-oriented RAG, (3) activate commonsense via chain-of-thought. Achieves 49.4% average improvement with GPT-4o-mini. Key insight: raw sensor data must be *verbalized* — converted from numeric streams to natural language descriptions — before LLMs can reason about it effectively.

**LLMSense** (2024): Converts raw sensor traces or low-level perception results into sentences for zero-shot high-level reasoning. Achieves 80%+ accuracy on tasks like dementia diagnosis from behavior traces and occupancy tracking from environmental sensors. Uses a four-component prompt: Objective, Context, Data, and Instructions. Two strategies for long traces: (1) summarization before reasoning, (2) selective inclusion of historical traces. Proposes edge-cloud architecture: small LLMs on edge for summarization, large LLMs in cloud for reasoning.

**Vision-Language-Action models** (2025): Robotics VLA architectures show three fusion strategies — early (shared encoder), late (modular), and hierarchical (transformer reasoning + diffusion decoders). Real-time grounding remains an open challenge: tight coupling between abstract LLM reasoning and continuous sensorimotor experience.

**Google SensorLM** (2024): Foundation model trained on 2.5M person-days of wearable sensor data (Fitbit/Pixel Watch). Enables zero-shot sensor understanding, sensor-text alignment, few-shot learning, and sensor caption generation. Demonstrates that sensor data can be treated as a "language" with its own grammar.

### 2.9 Computational Phenomenology of Time

Sandved-Smith et al. (2023, *Neuroscience of Consciousness*) provide the most complete computational formalization of Husserl's temporal structure through active inference:

- **Retention** nodes are treated as observations or empirical priors
- **Protention** and **primal impression** are treated as random variables
- A **Markov blanket** of the present moment integrates past and future moments in an asynchronous structure
- The "living inference" jointly produces the phenomenological living present

Key mathematical insight: P(present) ∝ softmax[log P(protention) + log P(primal impression) + log P(retention)]. The active inference belief update maps retention to accumulated posterior beliefs, protention to expected states under preferred policies.

For engineering, the critical takeaway is the **asymmetry**: retention is observation-like (grounded, decaying certainty), while protention is inference-like (speculative, concern-shaped). This asymmetry must be preserved in the input format.

### 2.10 Context Engineering as Discipline

A 2025 survey (arxiv 2507.13334) formalizes context engineering as three pillars:
1. **Context Retrieval and Generation**: prompt-based generation, external knowledge acquisition
2. **Context Processing**: long sequence processing, self-refinement, structured information integration
3. **Context Management**: memory hierarchies, compression, optimization

The JetBrains Research group (2025) documented practical context management for LLM-powered agents, identifying that the dominant failure mode is not insufficient context but *context pollution* — irrelevant information drowning relevant signals.

A taxonomy of context types from production systems includes: instruction context, query context, knowledge context (RAG), memory context, tool context, user-specific context, and environmental/temporal context. The last two are exactly what a perceptual system produces.

---

## 3. Hapax Architecture Mapping

### 3.1 Current Data Flow

```
Sensors (webcam, mic, screen, devices)
  ↓
PerceptionEngine (30+ behaviors, ~2.5s tick)
  ↓
_perception_state_writer.py → perception-state.json (flat snapshot)
  ↓
VisualLayerAggregator (15s fast / 60s slow cadence)
  ↓
DisplayStateMachine → visual-layer-state.json
  ↓
Studio Compositor (Cairo overlay rendering)
```

Additionally:
- Cockpit API (`:8051`) serves health, GPU, nudges, briefing, drift, goals, copilot
- Reactive engine (inotify watcher) cascades filesystem changes to downstream agents
- Qdrant stores profile facts, documents, axiom precedents, claude-memory
- Health history in JSONL, SDLC events in JSONL

### 3.2 Where Temporal Structure Concerns Map

| Temporal Concern | Current State | Where It Lives | What's Missing |
|---|---|---|---|
| **Retention (just-past)** | No history. `perception-state.json` is a flat snapshot overwritten every 2.5s. Previous states are lost. | `_perception_state_writer.py` | Ring buffer of recent states (last N ticks). Decay weighting. |
| **Primal impression (now)** | `perception-state.json` is the current impression, but it arrives as flat key-value pairs with no fusion with expectation. | `_perception_state_writer.py` + `VisualLayerAggregator` | Expectation integration. The "now" should include surprise/confirmation relative to protention. |
| **Protention (anticipation)** | None. No component predicts next likely states. The `DisplayStateMachine` has de-escalation cooldowns (crude temporal expectation) but no forward model. | Nowhere — entirely missing | Transition probability model. Pattern-based anticipation from retention history. |
| **Temporal hierarchy** | Two cadences exist (15s fast, 60s slow) in `VisualLayerAggregator`. `PresenceDetector` has a 5-minute sliding window. But no multi-scale temporal abstraction. | `VisualLayerAggregator` cadences, `PresenceDetector` window | Explicit scale hierarchy: tick (2.5s), minute (aggregated), session (hour), day (profile). Summarization at each scale. |
| **Temporal decay** | `PresenceDetector` has face decay (30s), VAD sliding window pruning. `DisplayStateMachine` has de-escalation cooldowns. All ad-hoc. | Scattered across presence.py, visual_layer_state.py | Unified decay model. Configurable half-lives per signal type. |
| **Fact versioning** | Profile facts in Qdrant have no temporal metadata. Health history is append-only JSONL. | `shared/dimensions.py`, Qdrant | Zep-style bi-temporal tracking: when the fact was true vs. when the system learned it. |
| **Sensor verbalization** | `_perception_state_writer.py` already verbalizes sensor data into JSON key-value pairs (e.g., `"gaze_direction": "toward_screen"`). | `_perception_state_writer.py` | Temporal verbalization: "gaze shifted from monitor to screen 15s ago, now stable on screen" vs. "gaze: screen". |

### 3.3 Existing Components That Can Be Extended

**`_perception_state_writer.py`** — Currently writes a flat snapshot. Natural extension point for a ring buffer and temporal band formatting. Instead of overwriting, maintain last N states and compute retention/protention bands on write.

**`VisualLayerAggregator`** — Already has dual-cadence polling. Can be extended with temporal summarization at each cadence boundary: fast tick produces primal impression, slow tick produces minute-scale retention summaries.

**`PresenceDetector`** — Already implements sliding-window decay (VAD events) and face-detection decay. This is the closest existing code to retention mechanics. Its pattern can be generalized.

**`DisplayStateMachine`** — Has de-escalation cooldowns, which are a primitive form of protention (expecting the system to calm down). Can be extended with explicit state transition probabilities.

**`cockpit/engine/watcher.py`** — The reactive engine already watches for filesystem changes with frontmatter parsing and document-type inference. A temporal state file could trigger reactive rules.

**Qdrant collections** — Profile facts and claude-memory could store temporal metadata. The `documents` collection already supports metadata filtering.

---

## 4. Implementation Possibilities

Ordered by feasibility — each builds on the previous.

### 4.1 Retention Ring Buffer (Immediate, No LLM Changes)

Add a ring buffer to `_perception_state_writer.py` that retains the last N perception snapshots (N=20 at 2.5s tick = 50s of history). Write both the current snapshot and a `perception-history.json` containing timestamped entries with computed deltas.

```python
# In _perception_state_writer.py
RING_BUFFER_SIZE = 20
_ring_buffer: deque[dict] = deque(maxlen=RING_BUFFER_SIZE)

def write_perception_state(perception, consent_registry, consent_tracker=None):
    state = _build_current_state(perception, consent_registry, consent_tracker)
    _ring_buffer.append(state)

    # Compute retention band: exponentially weighted summary of recent history
    retention = _compute_retention_band(_ring_buffer)

    # Write both current state and temporal context
    temporal_state = {
        "primal_impression": state,
        "retention": retention,
        "retention_depth": len(_ring_buffer),
        "timestamp": time.time(),
    }
    # Atomic write...
```

Retention band computation: exponential decay weighting where each tick's contribution is multiplied by `decay_factor^age_in_ticks`. Default half-life of 5 ticks (12.5s).

**Cost**: ~50 lines of code. No LLM involvement. Immediate benefit for any downstream consumer.

### 4.2 Temporal Band Formatting for LLM Input (Low Effort, High Impact)

Create a `TemporalContextFormatter` that reads the ring buffer and produces XML-structured temporal bands for LLM consumption. This is the core intervention.

```xml
<temporal_context scale="perception" tick_interval="2.5s">

<retention age="recent" confidence="0.85">
  Flow state was active (score 0.62) for 45 minutes
  Operator was coding in VS Code, gaze on primary monitor
  No context switches in last 3 minutes
  Emotion: focused → neutral transition 30s ago
</retention>

<retention age="fading" confidence="0.5">
  Session started 52 minutes ago after coffee break
  Initial activity: email triage (4 minutes) → code editor
  One Slack notification dismissed without reading
</retention>

<primal_impression certainty="observed">
  Face: 1 person, operator confirmed
  Gaze: secondary monitor (shifted 8s ago from primary)
  Posture: leaning forward (unchanged)
  Flow score: 0.35 (was 0.62, declining over 90s)
  Activity: tab switch to browser detected
  Audio: keyboard stopped 12s ago, quiet
  Ambient: overhead light, brightness 0.7, warm
</primal_impression>

<protention basis="flow_decline_pattern" confidence="0.6">
  Pattern match: flow exit sequence (gaze shift + tab switch + keyboard stop)
  Expected: transition to browsing/break within 60-120s
  Historical: operator typically takes 5-10min break after 45min flow
  If break confirmed: music genre shift appropriate, visual layer → ambient
  If return to code: flow re-entry likely, maintain peripheral state
</protention>

</temporal_context>
```

This format exploits RoPE's geometry: retention at the start (natural decay), primal impression in the middle-to-recent zone (vivid), protention at the end (end-of-sequence attention boost). The XML tags create clear boundaries that prevent temporal bands from bleeding into each other.

**Cost**: New module (~200 lines). Requires the ring buffer from 4.1.

### 4.3 Protention Engine (Medium Effort)

A lightweight transition probability model that predicts likely next states based on retention history. Not an LLM call — a statistical model built from observed patterns.

Sources of protention:
1. **Flow state transitions**: Empirical half-life of flow states (from health-history.jsonl)
2. **Activity mode sequences**: Markov chain of activity mode transitions (code → browse → break → code)
3. **Temporal patterns**: Time-of-day effects on activity (morning = email, afternoon = deep work)
4. **Session duration**: How long the current activity mode has persisted vs. historical averages
5. **DisplayStateMachine cooldowns**: Already encode temporal expectations; make them explicit

Implementation: a `ProtentionEngine` class that maintains transition counts and computes conditional probabilities. Updated on each perception tick. Outputs top-3 likely transitions with confidence scores.

**Cost**: ~300 lines. Depends on accumulated history in health-history.jsonl or a new transition log.

### 4.4 Multi-Scale Temporal Hierarchy (Medium-High Effort)

Implement explicit temporal summarization at four scales:

| Scale | Source | Update Cadence | Storage |
|---|---|---|---|
| **Tick** (2.5s) | Raw perception state | Every tick | Ring buffer (50s window) |
| **Minute** (60s) | Aggregated from tick ring buffer | Every slow poll | Minute ring buffer (60min window) |
| **Session** (variable) | Summarized from minute buffer at session boundaries | On activity mode change | Session log (day's sessions) |
| **Day** | Summarized from sessions | End of day or on-demand | Profile facts in Qdrant |

Each scale computes its own retention/primal_impression/protention triplet. The LLM context formatter selects the appropriate scale(s) based on the query or task.

The `VisualLayerAggregator` already has dual cadences (15s/60s) — the minute scale slots naturally into the slow poll. Session detection can be derived from `activity_mode` transitions in the perception state.

**Cost**: ~500 lines across multiple files. Requires session boundary detection logic.

### 4.5 Surprise-Weighted Primal Impression (Medium Effort)

The primal impression should not be a neutral snapshot — it should be fused with expectation. Implement surprise scoring: compare current perception state against the most recent protention prediction. Signals that violate prediction get higher weight.

```python
def compute_surprise(current: dict, protention: dict) -> dict:
    """Score each perception field by how much it deviates from prediction."""
    surprise = {}
    for key in current:
        if key in protention:
            if current[key] != protention[key]["expected"]:
                surprise[key] = protention[key]["confidence"]  # high confidence = high surprise
            else:
                surprise[key] = 0.0  # confirmed expectation, low salience
    return surprise
```

In the temporal context formatter, surprise-weighted fields get prominent placement and explicit marking:

```xml
<primal_impression>
  <surprising field="face_count" expected="1" observed="2" surprise="0.8">
    Second person detected — was not anticipated
  </surprising>
  <confirmed field="gaze" expected="screen" observed="screen" surprise="0.0">
    Gaze: on screen (as expected)
  </confirmed>
</primal_impression>
```

This is computationally trivial but phenomenologically significant: it transforms the snapshot from bare data into interpreted data, where interpretation means deviation-from-expectation.

**Cost**: ~150 lines. Depends on protention engine (4.3).

### 4.6 Zep-Style Temporal Fact Store (High Effort, High Value)

Replace flat Qdrant profile facts with a bi-temporal knowledge graph following Zep/Graphiti's architecture:
- Each fact gets four timestamps: t_valid, t_invalid, t'_created, t'_expired
- New observations invalidate old facts rather than deleting them
- Retrieval can be temporal: "what did the system believe at time T?" vs. "what is currently true?"
- Retention decay becomes fact-age-weighted retrieval

This is the most architecturally significant change and enables genuine temporal reasoning about the operator's patterns over days and weeks.

**Cost**: New module (~800 lines), Qdrant schema changes, migration of existing facts. Could use Zep/Graphiti directly as a dependency instead of building from scratch.

---

## 5. Open Questions

### 5.1 Attention Geometry Validation

The RoPE-based temporal band placement is theoretically grounded but empirically untested for this specific use case. Questions:
- Does the U-shaped attention curve actually produce the desired retention/primal_impression/protention weighting in practice?
- Does the specific token count per band matter? (If retention is 500 tokens and primal impression is 200, does the ratio affect processing?)
- Do different models (Claude, Gemini, Llama) respond differently to temporal band formatting?

**Next step**: Construct a benchmark. Feed identical perception data in flat vs. temporal-band format to Claude and Gemini. Compare output quality on tasks like: "What just changed?", "What is likely to happen next?", "Should the visual layer escalate?"

### 5.2 Optimal Decay Functions

The retention band needs a decay function. Candidates:
- **Exponential**: `weight = e^(-λt)` — simple, matches RoPE's cosine decay
- **Power law**: `weight = t^(-α)` — heavier tail, preserves more distant memory
- **Stepped**: Full weight for T-1 tick, half for T-2 through T-5, quarter for T-6 through T-20

Which matches human phenomenological retention? Husserl described retention as continuous modification, not discrete decay — suggesting smooth exponential rather than stepped. But the IoT-LLM research suggests that discrete summarization (stepped) may be more effective for LLM processing.

### 5.3 Protention Without an LLM

The protention engine (4.3) uses statistical patterns, not LLM inference. Is this sufficient? Active inference suggests protention should be shaped by *policy* (what the agent intends to do), not just statistics. But the Hapax system has no explicit intentions — it observes and responds. Statistical protention may be the right level for a passive perceptual system. If the system later gains agency (e.g., proactively scheduling content), LLM-driven protention becomes necessary.

### 5.4 Context Budget Allocation

A perception tick generates ~200-400 tokens of current state. With retention (3 bands × ~150 tokens) and protention (~100 tokens), the temporal context could reach 1000+ tokens per tick. For a model with 200K context, this is trivial. For a local model with 8K context, it is significant. How should the temporal context budget be allocated across scales?

The context rot research suggests that *less is more* — 2,500 tokens is the sweet spot before degradation sets in for many tasks. This implies aggressive summarization: retention should be a compressed narrative, not a raw data dump.

### 5.5 Temporal Structure in the Reactive Engine

The reactive engine (`cockpit/engine/`) uses inotify to watch filesystem changes. If `perception-state.json` gains temporal structure, should the reactive engine's rules become temporally aware? E.g., a rule that fires not on "state X exists" but on "state X persisted for >60s" or "state X followed state Y within 30s." This is a significant architectural question that connects temporal structure to the engine's rule evaluation model.

### 5.6 Bidirectional Temporal Flow

Husserlian time-consciousness has a subtlety: retention modifies the present moment, but the present also retroactively modifies what the retention *means*. A sudden loud noise reframes the preceding silence as "quiet before the interruption." Can this retroactive reframing be implemented? One approach: when surprise is high in the primal impression, re-weight the retention band to emphasize the contrast. This is computationally straightforward but philosophically deep.

### 5.7 When Does Temporal Structure Help vs. Hurt?

Not every LLM interaction benefits from temporal context. A simple factual query ("What is the GPU temperature?") does not need retention or protention. The system needs a way to determine when temporal structure adds value and when it adds noise. Heuristic: temporal context is valuable when the query involves *change*, *trend*, *anticipation*, or *context-sensitivity*. It is noise for point queries.

---

## 6. Sources

### Positional Encoding and Attention Geometry

- Su, J., Lu, Y., Pan, S., Murtadha, A., Wen, B., & Liu, Y. (2021). [RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864). Neurocomputing, 2024.
- Press, O., Smith, N.A., & Lewis, M. (2021). [Train Short, Test Long: Attention with Linear Biases Enables Input Length Extrapolation](https://arxiv.org/abs/2108.12409). ICLR 2022.
- [Base of RoPE Bounds Context Length](https://proceedings.neurips.cc/paper_files/paper/2024/file/9f12dd32d552f3ad9eaa0e9dfec291be-Paper-Conference.pdf). NeurIPS 2024.
- [Positional Embeddings in Transformer Models: Evolution from Text to Vision Domains](https://d2jud02ci9yv69.cloudfront.net/2025-04-28-positional-embedding-19/blog/positional-embedding/). ICLR Blogposts 2025.
- [Positional Embeddings in Transformers: A Math Guide to RoPE & ALiBi](https://towardsdatascience.com/positional-embeddings-in-transformers-a-math-guide-to-rope-alibi/). Towards Data Science.
- [Rotary Embeddings: A Relative Revolution](https://blog.eleuther.ai/rotary-embeddings/). EleutherAI Blog.

### Attention Distribution and Context Utilization

- Liu, N.F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., & Liang, P. (2024). [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172). TACL, 12, 157-173.
- [Found in the Middle: Calibrating Positional Attention Bias Improves Long Context Utilization](https://arxiv.org/abs/2406.16008). ACL Findings 2024.
- [Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://research.trychroma.com/context-rot). Chroma Research, 2025.

### Structured Prompting and Context Engineering

- [Does Prompt Formatting Have Any Impact on LLM Performance?](https://arxiv.org/html/2411.10541v1). 2024.
- [A Survey of Context Engineering for Large Language Models](https://arxiv.org/html/2507.13334v1). 2025.
- [Context Engineering: Memory and Temporal Context](https://www.dailydoseofds.com/llmops-crash-course-part-8/). DailyDoseOfDS, 2025.
- [Cutting Through the Noise: Smarter Context Management for LLM-Powered Agents](https://blog.jetbrains.com/research/2025/12/efficient-context-management/). JetBrains Research, 2025.

### Counterfactual and Hypothetical Reasoning

- [On the Eligibility of LLMs for Counterfactual Reasoning: A Decompositional Study](https://arxiv.org/abs/2505.11839). 2025.
- [CounterBench: A Benchmark for Counterfactuals Reasoning in Large Language Models](https://arxiv.org/html/2502.11008v1). 2025.
- [Prompting Large Language Models for Counterfactual Generation](https://aclanthology.org/2024.lrec-main.1156.pdf). LREC 2024.
- [Towards Better Causal Reasoning in Language Models](https://aclanthology.org/2025.naacl-long.622.pdf). NAACL 2025.

### Temporal Memory and Hierarchical Context

- Rasmussen, P. (2025). [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956).
- [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/abs/2504.19413). 2025.
- [H-MEM: Hierarchical Memory for High-Efficiency LLMs](https://arxiv.org/pdf/2507.22925). 2025.
- [HMT: Hierarchical Memory Transformer for Efficient Long Context Processing](https://aclanthology.org/2025.naacl-long.410.pdf). NAACL 2025.
- [Context-Level Language Modeling (ContextLM)](https://arxiv.org/pdf/2510.20280). ICLR 2026.
- [MemOS: A Memory OS for AI Systems](https://statics.memtensor.com.cn/files/MemOS_0707.pdf). 2025.

### Phenomenological Computation

- Sandved-Smith, L., Hesp, C., Mattout, J., Friston, K., Lutz, A., & Ramstead, M. (2023). [Time-consciousness in computational phenomenology: a temporal analysis of active inference](https://pmc.ncbi.nlm.nih.gov/articles/PMC10022603/). Neuroscience of Consciousness, 2023(1).
- [Dynamic planning in hierarchical active inference](https://www.sciencedirect.com/science/article/pii/S0893608024010049). Neural Networks, 2024.
- [Retention and Protention Methodology: Edmund Husserl's Phenomenology as a Multidimensional Design Approach](https://series.francoangeli.it/index.php/oa/catalog/download/548/374/3140). 2022.
- [A beautiful loop: An active inference theory of consciousness](https://www.sciencedirect.com/science/article/pii/S0149763425002970). Neuroscience & Biobehavioral Reviews, 2025.

### Sensor-to-LLM Perception Systems

- [IoT-LLM: Enhancing Real-World IoT Task Reasoning with Large Language Models](https://arxiv.org/abs/2410.02429). 2024.
- [LLMSense: Harnessing LLMs for High-level Reasoning Over Spatiotemporal Sensor Traces](https://arxiv.org/abs/2403.19857). 2024.
- [SensorLM: Learning the language of wearable sensors](https://research.google/blog/sensorlm-learning-the-language-of-wearable-sensors/). Google Research, 2024.
- [Foundation Model Driven Robotics: A Comprehensive Review](https://arxiv.org/html/2507.10087v1). 2025.
- [Multimodal fusion with vision-language-action models for robotic manipulation](https://www.sciencedirect.com/science/article/pii/S1566253525011248). Information Fusion, 2025.

### Memory Frameworks and Tools

- [LangChain Long-term Memory Documentation](https://docs.langchain.com/oss/python/langchain/long-term-memory).
- [LlamaIndex Memory Documentation](https://developers.llamaindex.ai/python/examples/memory/memory/).
- [Model Context Protocol Specification](https://modelcontextprotocol.io/specification/2025-11-25). Anthropic, 2025.
- [The 6 Best AI Agent Memory Frameworks](https://machinelearningmastery.com/the-6-best-ai-agent-memory-frameworks-you-should-try-in-2026/). MachineLearningMastery, 2025.
