# Affordance-as-Retrieval: Relational Capability Selection

**Status:** Design specification
**Supersedes:** Static affordance matching in `shared/capability_registry.py`
**Depends on:** Phase 0-2 cascade infrastructure (complete), Qdrant + nomic embeddings (operational)

## 1. Problem Statement

The current cascade architecture prefigures which capabilities serve which needs. `SpeechProductionCapability` declares `affordance_signature = {"verbal_response", "spontaneous_speech", ...}` and `can_resolve()` does substring matching against `impingement.content["metric"]`. This is functional fixedness in code (Duncker 1945, McCaffrey 2012) -- the system can never discover that a capability works for something it wasn't labeled for.

Additionally, three isolated `CapabilityRegistry` instances (voice, fortress, engine) prevent cross-domain competition. Speech and fortress governance never compete for the same impingement.

The system needs: relational capability matching (Gibson 1979), learned associations (Hebb 1949), retrieval-based discovery (Tool2Vec 2024), and unified competition (Desimone & Duncan 1995).

## 2. Design Principles

1. **Capability is relational.** A tool does not "have" capabilities. Capability is a relationship between a need and what happens to be available. The napkin becomes a writing surface when the need is "write something now" and the napkin is nearby (Gibson 1979, Sahin 2007).

2. **No prefigured associations.** Capabilities do not declare which needs they serve. Associations are discovered through embedding similarity and reinforced through outcome feedback. The system can use a tool for something it wasn't designed for if the properties match (Anderson 2010 neural reuse).

3. **Selection is competition, not search.** Multiple capabilities activate simultaneously; mutual inhibition resolves which one wins (Desimone & Duncan 1995). There is no lookup phase followed by a decision phase -- competition is the decision mechanism.

4. **Associations are learned, not authored.** Need-capability links strengthen through successful co-occurrence (Hebbian learning) and weaken through failure. Thompson Sampling provides principled exploration-exploitation (Thompson 1933).

5. **Scale through retrieval.** The capability landscape lives in a vector store. Impingement arrival triggers embedding retrieval, not linear registry scan. This scales from 3 to 3,000 capabilities without architectural change (HGMF 2026, Tool2Vec 2024).

## 3. Architecture

### 3.1 Capability Description Model

Replace `affordance_signature: set[str]` with a **property description** -- a natural language text describing what the capability does in function-free terms (McCaffrey's generic-parts technique).

```python
class CapabilityRecord(BaseModel, frozen=True):
    """Indexed capability in the affordance landscape."""
    name: str                          # unique identifier
    description: str                   # function-free property description
    embedding: list[float]             # 768-dim nomic vector of description
    operational: OperationalProperties # structured constraints

class OperationalProperties(BaseModel, frozen=True):
    """Hard constraints, not semantic -- used for filtering, not matching."""
    requires_gpu: bool = False
    requires_network: bool = False
    latency_class: str = "fast"        # fast (<1s), moderate (1-30s), slow (>30s)
    persistence: str = "none"          # none, session, permanent
    consent_required: bool = False
    priority_floor: bool = False       # safety-critical bypass
```

Example descriptions (function-free, property-based):

| Capability | Current affordance_signature | Proposed description |
|---|---|---|
| SpeechProduction | `{"verbal_response", "spontaneous_speech", ...}` | "Produces audible natural language that reaches the operator's ears within 1 second. Requires GPU and speakers. Output is ephemeral (not persisted). Can convey urgency through prosody." |
| FortressGovernance | `{"drink", "food", "population", ...}` | "Evaluates resource adequacy and threat levels in a managed simulation. Produces strategic recommendations and dispatches management commands. Operates on 2-second tick cycle." |
| RuleCapability(profile_sync) | `{"profile_sync"}` | "Detects changes to operator profile files and cascades downstream updates to dependent agents. Deterministic, sub-second, no LLM." |

### 3.2 Qdrant Collection: `affordances`

```python
# New collection in shared/qdrant_schema.py
"affordances": {
    "size": 768,
    "distance": "Cosine",
}

# Payload fields per point:
{
    "capability_name": str,          # foreign key to runtime capability
    "description": str,              # natural language (for audit/debug)
    "requires_gpu": bool,
    "latency_class": str,
    "consent_required": bool,
    "priority_floor": bool,
    "daemon": str,                   # which daemon owns this capability
    "available": bool,               # runtime availability flag
}
```

### 3.3 Impingement Embedding

Add an optional `embedding` field to the Impingement model. Computed at creation time by producers that have access to `embed()`, or lazily at broadcast time.

```python
class Impingement(BaseModel, frozen=True):
    # ... existing fields unchanged ...
    embedding: list[float] | None = None  # 768-dim, computed from content
```

Embedding source text constructed from impingement content:

```python
def render_impingement_text(imp: Impingement) -> str:
    """Render impingement content as embeddable text."""
    parts = [f"source: {imp.source}"]
    if imp.content.get("metric"):
        parts.append(f"signal: {imp.content['metric']}")
    if imp.content.get("value") is not None:
        parts.append(f"value: {imp.content['value']}")
    if imp.interrupt_token:
        parts.append(f"critical: {imp.interrupt_token}")
    return "; ".join(parts)
```

### 3.4 ACT-R Activation State

Per-capability activation tracking using Petrov (2006) k=1 approximation. Storage: 3 values per capability for base-level, 2 for Thompson Sampling.

```
B_i = ln( t_1^{-d} + 2(n-1) / (sqrt(t_n) + sqrt(t_1)) )
```

Where t_1 = time since last use, t_n = time since first use, n = use count, d = 0.5.

Thompson Sampling with discount (gamma=0.99, effective window ~100 observations):

```
On success: alpha *= gamma; alpha += 1
On failure: beta *= gamma; beta += 1
All others: alpha *= gamma; beta *= gamma
Sample: theta ~ Beta(alpha, beta)
```

### 3.5 Unified Selection Pipeline

Replace three isolated registries with a single pipeline:

```
IMPINGEMENT ARRIVES
       |
       v
[1. INTERRUPT CHECK] -- exact match on interrupt_token
       |               -- if match: bypass everything, dispatch immediately
       |
       v
[2. EMBED] -- render_impingement_text() -> embed() -> 768-dim vector
       |    -- cache: hash(content) -> embedding (avoid re-embedding repeats)
       |
       v
[3. RETRIEVE] -- Qdrant query: top-k capabilities by cosine similarity
       |        -- Filter: available=True, operational constraints
       |        -- k=10 (configurable)
       |
       v
[4. ACTIVATE] -- For each retrieved capability:
       |        -- similarity (from Qdrant, 0-1)
       |        -- base_level (ACT-R recency + frequency)
       |        -- context_boost (spreading activation from DMN state)
       |        -- thompson_sample (exploration noise)
       |        -- cost_weight (1.0 - activation_cost * 0.5)
       |        -- combined = weighted sum
       |
       v
[5. COMPETE] -- Priority floor bypass (unchanged)
       |      -- Mutual suppression (unchanged, 30% advantage penalty)
       |      -- Inhibition of return (unchanged, content hash + source)
       |      -- Threshold filter (combined > 0.05)
       |
       v
[6. DISPATCH] -- Winner(s) activate via existing activate() method
       |       -- Impingement queued in capability's pending queue
       |
       v
[7. LEARN] -- On resolution:
           -- Success: ts_alpha += 1, use_count += 1, update association matrix
           -- Failure: ts_beta += 1
           -- All capabilities: ts_alpha *= gamma, ts_beta *= gamma
```

### 3.6 Interrupt Token Override

Interrupt tokens (`population_critical`, `operator_distress`, `axiom_config_changed`) bypass the embedding pipeline entirely. They are exact-match safety signals that must never be softened by semantic similarity.

Capabilities register for interrupt tokens at init time -- this is the one prefigured association that is justified (safety-critical paths must be deterministic).

### 3.7 Rule Capability Compatibility

RuleCapability (logos engine) continues to use exact `trigger_filter()` matching. Rules are registered in the `affordances` collection with auto-generated descriptions, but their `can_resolve()` path remains deterministic. The embedding similarity acts as a pre-filter; `can_resolve()` provides the hard gate.

### 3.8 Context Spreading Activation

DMN's `read_all()` snapshot provides context cues for ACT-R spreading activation:

```python
CONTEXT_CUES = {
    "stimmung_stance": lambda s: s.get("stimmung", {}).get("stance", "unknown"),
    "operator_activity": lambda s: s.get("perception", {}).get("activity", "unknown"),
    "operator_presence": lambda s: s.get("perception", {}).get("presence", "unknown"),
    "time_of_day": lambda s: _time_bucket(s.get("timestamp", 0)),
}
```

Association strengths `S_ji` between context cues and capabilities are learned through co-occurrence (Hebbian). Stored as a sparse matrix. Updated after each successful activation.

Max associative strength `S = 4.0` (keeps associations positive for up to ~54 capabilities per cue). Attentional weights `W_j = 1.0 / len(active_cues)`.

## 4. Retroactive Impact on Phase 1 and Phase 2

### 4.1 Phase 1

| Component | Status | Change |
|---|---|---|
| Voice consumer loop | **NEEDS UPDATE** | Replace direct `can_resolve()` with unified pipeline query |
| Cognitive loop polling | **UNCHANGED** | `has_pending()` / `consume_pending()` queue stays |
| Spontaneous speech gen | **NEEDS UPDATE** | Ensure `content["metric"]` persists. Add similarity score to prompt context |
| Anti-correlation signal | **UNCHANGED** | TPN active/idle independent of matching |
| Fortress JSONL consumer | **NEEDS UPDATE** | Replace per-daemon broadcast with unified pipeline query |
| Fortress deliberation | **UNCHANGED** | `has_pending_impingement()` / `consume_impingement()` stays |

### 4.2 Phase 2

| Component | Status | Change |
|---|---|---|
| ChangeEvent converter | **NEEDS UPDATE** | Add embedding computation. Keep strength map for fallback |
| RuleCapability wrapper | **UNCHANGED** | Binary trigger_filter stays. Description auto-generated |
| Engine broadcast | **NEEDS UPDATE** | Replace discarded broadcast with unified pipeline |
| SensorBackend protocol | **NEEDS UPDATE** | `emit_sensor_impingement()` adds embedding |
| Sync agent emissions | **UNCHANGED** | Calls stay, embedding added inside protocol |
| DMN sensor extension | **UNCHANGED** | `read_sensors()` / `read_all()` unchanged |

### 4.3 Test Impact

| Test File | Affected | Change |
|---|---|---|
| test_impingement.py | 4 of 18 | Rewrite `can_resolve` assertions for similarity thresholds |
| test_engine_cascade.py | 4 of 11 | Range checks instead of exact strengths |
| test_sensor_protocol.py | 2 of 11 | Range check for strength, mock embedding |
| test_dmn.py | 0 of 16 | All unchanged |

## 5. Fallback and Graceful Degradation

If Ollama is unavailable (embedding cannot be computed):
1. Impingement `embedding` field is `None`
2. Selection pipeline falls back to keyword search on `content["metric"]` against capability descriptions
3. ACT-R activation and Thompson Sampling continue to operate
4. Log warning but do not block cascade

Current behavior is the degraded mode.

## 6. Performance Budget

| Operation | Latency | Frequency |
|---|---|---|
| Impingement embedding | ~50ms (Ollama) | Per impingement |
| Qdrant retrieval (top-10) | ~5ms (gRPC) | Per impingement |
| ACT-R activation (100 caps) | <0.1ms | Per selection |
| Thompson sampling (10 candidates) | <0.01ms | Per selection |
| Mutual suppression | <0.01ms | Per selection |
| **Total per impingement** | **~55ms** | **~1/s peak** |

With embedding cache for repeated patterns, amortized cost drops to ~5ms.

## 7. Research Foundation

| Concept | Source | Application |
|---|---|---|
| Relational affordances | Gibson 1979 | Capability is agent-environment relation |
| Effect-indexed retrieval | Sahin 2007 | Index by desired effect, not tool category |
| Functional fixedness defeat | McCaffrey 2012 | Function-free property descriptions |
| Usage-driven embeddings | Tool2Vec 2024 | Embed by resolved queries |
| Spreading activation RAG | SA-RAG 2024 | Activation spread for retrieval |
| Hierarchical retrieval | HGMF 2026 | Coarse-to-fine for scale |
| Base-level activation | ACT-R, Petrov 2006 | Recency + frequency, k=1 approximation |
| Biased competition | Desimone & Duncan 1995 | Mutual inhibition with top-down bias |
| Global workspace | Baars 1988 | Winner broadcasts for coordination |
| Complement cascade | Janeway 2001 | Amplification with distributed inhibition |
| Neural reuse | Anderson 2010 | Capabilities recruited for novel purposes |
| Hebbian learning | Hebb 1949 | Co-occurrence strengthens associations |
| Thompson Sampling | Thompson 1933 | Principled exploration-exploitation |
| Discounted TS | Raj & Kalyani 2017 | Non-stationary adaptation (gamma=0.99) |
| Situated action | Suchman 1987 | Tool selection is always contextual |
