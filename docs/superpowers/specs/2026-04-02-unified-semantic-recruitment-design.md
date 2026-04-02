# Unified Semantic Recruitment

**Date:** 2026-04-02
**Status:** Draft
**Author:** Alpha session + operator
**Scope:** System-wide architectural spec — all subsystems, all capability types

## 1. Problem Statement

The system has a single semantic recruitment mechanism (AffordancePipeline + Qdrant embeddings + impingement cascade) that correctly gates shader modulation and vocal chain expression. But content appearance, tool selection, and destination routing bypass this mechanism entirely:

- Camera frames publish unconditionally every tick without recruitment
- The imagination LLM names concrete implementations (`camera_frame: overhead`) instead of expressing intent
- Content references flow directly from imagination to visual surface without affordance matching
- 30 tools use LLM menu selection, not semantic recruitment
- Output destinations (visual surface, speaker, notifications) are hardcoded, not recruited
- Each daemon runs its own pipeline instance with no cross-daemon recruitment

**Everything that appears must be a recruited representation.** The existing mechanism is correct and sufficient. It is incompletely applied.

## 2. Core Principle

Recruitment is singular. There is one mechanism. It operates on semantic intent — "observe the workspace," "express tension," "recall past experiences." Not on subsystem concerns, not on media types, not on implementation details.

Everything downstream of intent is a recruited capability. The visual surface is a capability. Vocalization is a capability. A camera feed is a capability. An internet search is a capability. Even the ability to acquire a new capability is a capability. All recruited the same way: semantic match between intention and capability affordance description.

The only exception: the **generative substrate** (vocabulary shader graph). The DMN is a permanently running generative process. External stimulation suppresses and redirects it; it does not start it. The vocabulary graph always runs. Recruitment modulates it. Content is composited into it. It is never recruited because it is never not running.

## 3. The Mechanism

The AffordancePipeline already implements the correct selection algorithm:

1. **Impingement arrives** — typed signal carrying semantic content, strength, optional embedding
2. **Embed** — `render_impingement_text(imp)` → embedding via nomic-embed-text-v2-moe (768-dim)
3. **Retrieve** — cosine similarity query against Qdrant `affordances` collection, top-K candidates
4. **Score** — `combined = 0.50×similarity + 0.20×base_level + 0.10×context_boost + 0.20×thompson_score × cost_weight`
5. **Govern** — `pipeline_veto | capability_veto` per candidate; vetoed candidates skipped, next tried
6. **Suppress** — winner suppresses runner-up by 30% of advantage gap; SEEKING stance halves threshold
7. **Return** — sorted list of surviving candidates across all domains and modalities

No changes to this algorithm. The work is: register all capabilities, remove all bypass paths, and make this the sole path from intention to expression.

### 3.1 Stigmergic Coordination

The mechanism is already stigmergic:

- **Qdrant `affordances` collection** = shared pheromone field. All daemons index their capabilities there. All daemons query the full collection.
- **JSONL transport** (`/dev/shm/hapax-dmn/impingements.jsonl`) = shared impingement trail. Producers append. Multiple consumers read independently via cursor tracking.
- **Activation state** = per-organism learning. Each daemon's Thompson sampling, Hebbian associations, and base level counters reflect its own experience. No shared activation file.
- **No centralized coordinator.** Each daemon reads the shared medium and acts on what concerns it.

### 3.2 Cross-Daemon Activation Summaries

One extension: each daemon periodically writes activation summaries (success rate, use count, last-use timestamp) into the Qdrant point payload for its own capabilities. Other daemons read this when scoring candidates whose local activation state is absent. Pure stigmergy — the pheromone field carries both the capability description and its track record.

## 4. Taxonomy

### 4.1 Six Domains

Derived from cognitive science (organism-environment coupling modes):

| Domain | Role | Gibson Verbs |
|--------|------|-------------|
| **Perception** | Extend what the system can sense | observe, detect, sense, distinguish, track |
| **Expression** | Externalize internal state | express, convey, manifest, project, render |
| **Recall** | Access stored knowledge | recall, retrieve, recognize, associate |
| **Action** | Change the environment or produce artifacts | produce, generate, transform, compose |
| **Communication** | Convey structured information to operator | speak, notify, signal, indicate |
| **Regulation** | Modulate other capabilities | regulate, gate, suppress, amplify, balance |

Domains are organizational. They are NOT embedded in Qdrant. They exist for human comprehension and for future UI affordance browsing.

### 4.2 Three-Level Rosch Structure

| Level | Role | Embedded? |
|-------|------|-----------|
| **Domain** (superordinate) | Organizational grouping | No |
| **Affordance** (basic) | The retrievable unit — what gets matched against impingements | **Yes** |
| **Instance** (subordinate) | The specific capability fulfilling the affordance | No (metadata payload) |

The affordance level is where perception, function, and motor programs converge (Rosch's basic level finding). This is the embedding target.

### 4.3 Affordance Description Rules

1. Lead with the cognitive function, not the modality
2. Use Gibson verbs (observe, detect, sense, express, convey, recall, produce, regulate, notify)
3. Include distinguishing constraints ("under any lighting" vs "with color detail")
4. 15-30 words — short enough to embed cleanly, long enough for relational specificity
5. Never mention implementation — no model names, resolutions, ports, collection names
6. Express the organism-environment relation — not "captures video" but "observe the operator's activity"
7. Use the 9 expressive dimensions as adjective vocabulary within expression affordances

### 4.4 Description Template

```
[What it offers to cognition] + [under what conditions] + [distinguishing constraint]
```

### 4.5 Example Descriptions

**Perception:**
- "Observe workspace from above, providing spatial context for physical activity and object arrangement"
- "Observe the operator's face, hands, and immediate work surface at close range"
- "Detect operator presence and hand activity at the desk under any lighting conditions"
- "Sense acoustic energy and rhythmic structure in the room"
- "Sense operator heart rate and physiological state through wearable biometrics"

**Expression (9 dimensions, modality-independent):**
- "Express intensity — energy, force, presence becoming manifest"
- "Express tension — constriction, resistance, strain"
- "Express depth — distance, immersion, spatial recession"
- "Express coherence — pattern regularity, structured order"
- "Express temporal distortion — time stretching, acceleration, phase displacement"

**Recall:**
- "Recall past experiences similar to the current moment from episodic memory"
- "Recall known facts about the operator's preferences and behavioral patterns"
- "Search ingested documents for knowledge relevant to the current context"

**Action:**
- "Search the internet for current information about a topic"
- "Transform visual content through dynamic shader graph effects"
- "Generate structured natural language through reasoning"

**Communication:**
- "Speak to the operator in natural language, capturing attention through sound"
- "Send a persistent notification to the operator's devices for later acknowledgment"
- "Display a status indicator in the desktop bar for ambient awareness"

**Regulation:**
- "Surface system health degradation to operator awareness"
- "Gate capability activation on operator consent for person-adjacent data"

### 4.6 The Nine Expressive Dimensions

The 9 dimensions are cross-cutting descriptors within the Expression domain. They are media-independent — the same dimension (tension, intensity, coherence...) applies to vocal chain MIDI CCs, visual chain shader params, and any future expression medium. Each dimension is registered as its own affordance with both a modality-independent description and modality-specific realizations in the metadata payload.

The dimensions are: intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion.

## 5. Imagination Fragment Model

### 5.1 New Model

```
id: str
timestamp: float
narrative: str              # the semantic intent — the ONLY recruitment query
salience: float             # 0.0-1.0, importance of this thought
material: Material          # water/fire/earth/air/void — phenomenological quality
dimensions: dict[str, float]  # canonical 9 expressive dimensions
continuation: bool          # extends previous fragment
parent_id: str | None       # cascade tracing
```

**Removed:** `content_references` — the imagination does not name implementations.

**Changed:** `dimensions` keys from color names to the 9 canonical expressive dimension names (intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion).

**Kept:** `material` — a semantic quality of the thought (dissolving, consuming, grounded, drifting, absorbing), not an implementation detail. How material maps to shader uniforms or vocal timbre is the recruited capability's concern.

### 5.2 Imagination LLM System Prompt

The prompt changes from "name specific content sources" to:

> You are the imagination process of a personal computing system. You observe the system's current state and produce spontaneous associations, memories, projections, and novel connections.
>
> Your output carries semantic intent only: a narrative describing what you are imagining, expressive dimensions characterizing its quality, a material quality, and a salience assessment. You do not decide how or where the thought is expressed — that is handled by downstream recruitment. Focus on WHAT you are imagining and WHY it matters.
>
> **Material Quality:** Each fragment has an elemental material that describes how the thought interacts with the field: water (dissolving, contemplative), fire (consuming, urgent), earth (dense, grounded), air (drifting, translucent), void (absorbing, absent).
>
> **Expressive Dimensions:** Rate the fragment on the nine dimensions (0.0-1.0): intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion.

### 5.3 Escalation

`maybe_escalate()` remains unchanged. High-salience fragments become impingements, entering the JSONL transport for pipeline recruitment. Low-salience fragments modulate the generative substrate via dimension levels without triggering content recruitment.

The escalated impingement carries the fragment's narrative as its content. This narrative is embedded and matched against all registered affordances. The pipeline discovers what representations to recruit — the imagination never decided.

## 6. Recruitment Flow

### 6.1 End-to-End

```
IMAGINATION TICK (~5-12s)
  LLM → fragment {narrative, dimensions, material, salience}
  if salience > threshold: emit Impingement to JSONL
  Always: write fragment to /dev/shm/hapax-imagination/current.json

MIXER TICK (1s governance cadence)
  Read fragment from /dev/shm
  Read impingements from JSONL consumer
  
  For each impingement:
    candidates = pipeline.select(impingement)
      → embeds narrative
      → queries Qdrant affordances (ALL domains, ALL modalities)
      → scores, governs, suppresses
      → returns surviving candidates
    
    FAST tier (synchronous):
      camera capture, visual dimension, vocal dimension, local file
    
    SLOW tier (asynchronous):
      Qdrant knowledge query, web search, text rendering
      Resolved content staged for next tick

  Write uniforms:
    dimensions from activated capabilities
    slot opacities from recruitment levels (not imagination salience)
    
RUST PIPELINE (continuous ~30fps)
  Vocabulary graph always running (generative substrate)
  Hot-reload uniforms per frame
  Recruited content composited into substrate via content layer
  Frame output to /dev/shm
```

### 6.2 Two-Tier Recruitment

Each `CapabilityRecord` carries `OperationalProperties.latency_class`:

- **FAST** (<100ms): camera capture, dimension activation, MIDI CC, local file read. Recruited and resolved within the mixer tick.
- **SLOW** (>100ms): Qdrant semantic query, web search, text rasterization, image generation. Recruited within the tick, resolved asynchronously. Staged content appears on the next tick that picks it up.

The tier classification is on the capability, not on the content type. A camera feed is FAST. A Qdrant query about the same topic is SLOW. The pipeline returns both; the mixer handles them differently.

### 6.3 Slot Opacities

Slot opacities are determined by recruitment level (`combined` score from pipeline scoring), not by per-reference salience from the imagination LLM. If the pipeline recruits "observe workspace from above" at combined score 0.7, that content gets opacity 0.7. The imagination never decided the opacity.

### 6.4 Content Resolver as Recruited Capability

The content resolver is no longer a hardcoded daemon that mechanically processes content_references. It becomes a set of recruited capabilities:

- "Materialize text as visual content" — a SLOW expression capability
- "Recall and visualize knowledge from episodic memory" — a SLOW recall + expression compound
- "Capture camera perspective as visual content" — a FAST perception + expression compound

Each registers its own affordance description. The pipeline recruits them when the imagination's narrative matches. They resolve content and stage it for the visual surface.

## 7. Destinations as Capabilities

### 7.1 Single-Pass Multi-Modal

A single `pipeline.select()` call returns candidates across ALL modalities. "Express tension" naturally recruits both `vocal_chain.tension` and `visual_chain.tension` because both have descriptions in the semantic neighborhood of tension. The ExpressionCoordinator distributes the fragment across recruited modalities.

No separate "where to express" pass. The destination IS the capability. Each expression capability's description includes medium properties:

- Visual chain: "...through continuous spatial field, ambient and persistent"
- Vocal chain: "...through vocal timbre, ephemeral and attention-capturing"
- Notification: "...through brief persistent text alert"

The embedding similarity naturally routes to appropriate media based on the impingement's semantic content.

### 7.2 Medium-Aware Descriptions

Destinations do not register separately. They are implicit in the expression capability descriptions. "Express tension through vocal timbre constriction" embeds differently from "Express tension through visual pattern tightening." The pipeline recruits whichever matches the impingement's semantic neighborhood — possibly both.

## 8. Generative Substrate

### 8.1 The Vocabulary Graph is Permanent

The 8-pass vocabulary graph (noise → rd → color → drift → breath → feedback → content → post) always runs. It is not in the Qdrant affordances collection. It is not selected by the pipeline. It is the field INTO which recruited content is composited and through which recruited modulations are expressed.

The DMN is a permanently running generative process. External stimulation suppresses and redirects it; it does not start it. The vocabulary graph is the visual analogue.

### 8.2 Modulation, Not Activation

The 9 expressive dimensions modulate the substrate's parameters when recruited by impingements — the same way TPN engagement modulates DMN activity. When impingement-driven activation decays to zero, the vocabulary returns to its default generative state. Not black. Not silent. Autonomously wandering.

### 8.3 Content Compositing

Recruited content (camera feeds, text, knowledge visualizations) is composited INTO the generative field via the content layer. The substrate shapes how content appears (material quality, feedback traces, noise texture). Content does not replace the substrate — it enters it.

## 9. Governance

### 9.1 Two-Level VetoChain Composition

```
pipeline_veto | capability_veto
```

**Pipeline-level** gates whether ANY recruitment happens:
- Consent state: `consent_refused` → no recruitment
- System health: `critical` → no recruitment
- Stimmung threshold modulation: raises minimum combined score under degraded stance

**Capability-level** gates whether a SPECIFIC capability is recruited:
- GPU required but unavailable
- Consent required for person-adjacent data
- Resource tier exceeds current budget
- Capability-specific constraints

If capability-level governance vetoes a candidate, the pipeline tries the next candidate (FallbackChain pattern). Graceful degradation by design.

### 9.2 Consent Gates Recruitment

Consent gates the recruitment itself, not just the final display. If an impingement carries person-adjacent content and the recruited capability requires consent, recruitment is denied before any processing happens. The ConsentLabel join-semilattice determines flow: `label.can_flow_to(capability_consent_level)`.

### 9.3 Stimmung Modulates Threshold

Stimmung modulates the pipeline's effective threshold:
- **Nominal:** threshold = 0.05 (standard)
- **SEEKING:** threshold = 0.025 (wider exploration)
- **Degraded:** threshold = 0.10 (only high-confidence matches)
- **Critical:** threshold = 1.0 (effectively no recruitment)

Source cadence modulation (imagination tick rate, DMN pulse rate) remains as-is — it governs how fast sources produce, orthogonal to recruitment threshold.

## 10. Novel Capability Discovery

### 10.1 The Meta-Affordance

A `capability_discovery` affordance is registered:

> "Find and acquire new capabilities when no existing capability matches an intention. Discover tools, services, or resources that could fulfill unmet cognitive needs."

When the pipeline fails to match an intention, the exploration tracker feeds `error=1.0`, eventually emitting a `CURIOSITY` or `BOREDOM` impingement. On the next pass, this impingement matches `capability_discovery` via semantic similarity.

### 10.2 Discovery vs. Acquisition

- **Discovery** (read-only, FAST-tier): search the internet, scan local packages, check available APIs for capabilities matching the unresolved intention. No side effects.
- **Acquisition** (write, SLOW-tier, `consent_required=True`): install a package, register a new service, configure a new API endpoint. Requires operator consent.

### 10.3 Self-Registration

When a new capability is acquired, it registers itself in the Qdrant `affordances` collection with a semantic description. Future queries for similar intentions match it directly. The system grows its capability surface through use.

### 10.4 Governance

The `capability_discovery` affordance itself has `consent_required=True`. The system cannot self-extend without the operator's knowledge. Discovery (searching for what's possible) may proceed autonomously. Acquisition (installing/configuring) requires consent.

## 11. Bypass Removal

The following ambient/hardcoded paths are removed:

| Current Bypass | Replacement |
|----------------|-------------|
| `update_camera_sources()` unconditional every tick | Camera capabilities registered in Qdrant; recruited by pipeline when imagination intent matches perception affordances |
| `content_references` on ImaginationFragment | Removed. Narrative is the only retrieval context. |
| `build_slot_opacities()` from per-reference salience | Slot opacities from recruitment `combined` scores |
| Content resolver mechanically processing all refs | Content resolution capabilities recruited by pipeline |
| `can_resolve()` hardcoded routing on capabilities | Removed. Semantic matching via AffordancePipeline only. |
| Tool selection via LLM function-calling menu | Tools registered as affordances; recruited by pipeline (queue #015, now in scope) |
| Destination hardcoded per-daemon (speech→speaker, visual→surface) | Destinations implicit in capability descriptions; pipeline recruits across modalities |
| Per-daemon AffordancePipeline routing only own capabilities | Each daemon's pipeline queries full Qdrant collection; routes recruited capabilities via stigmergic trace |

## 12. What Does Not Change

- The AffordancePipeline selection algorithm
- The Qdrant `affordances` collection structure
- The JSONL impingement transport
- The ImpingementConsumer cursor-tracking model
- The 9 expressive dimensions (now elevated to system-wide vocabulary)
- The VetoChain/FallbackChain governance primitives
- The ControlSignal health publication
- The 14 SCM control laws (ingress gates)
- The 15th exploration control law
- The generative substrate (vocabulary shader graph)
- The ExpressionCoordinator (distributes across recruited modalities)

## 13. Implementation Phases

### Phase 1: Imagination Purification
Remove `content_references` from ImaginationFragment. Update system prompt. Update all consumers (resolver, mixer, conversation pipeline). The imagination produces pure semantic intent.

### Phase 2: Content Recruitment
Register camera feeds, knowledge queries, text rendering, file access as affordances in Qdrant. Route content appearance through `pipeline.select()`. Remove `update_camera_sources()`. Remove hardcoded content resolver daemon.

### Phase 3: Tool Recruitment
Register all 30 tools as affordances (queue #015). Route tool selection through `pipeline.select()`. Remove LLM function-calling menu.

### Phase 4: Destination Recruitment
Enrich expression capability descriptions with medium properties. Let `pipeline.select()` return multi-modal candidates naturally. Destination routing emerges from embedding similarity.

### Phase 5: Novel Discovery
Register `capability_discovery` meta-affordance. Wire exploration tracker's empty-selection signal to discovery handler. Implement discovery (web search) and acquisition (consent-gated self-extension) capabilities.

### Phase 6: Cleanup
Remove all `can_resolve()` methods. Remove dead code paths (CapabilityRegistry.broadcast(), unused). Consolidate activation state persistence.
