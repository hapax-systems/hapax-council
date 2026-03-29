# Capability Parity: Unified Meta-Structure for Daimonion and Reverie

**Date:** 2026-03-29
**Status:** Design
**Context:** Daimonion (voice) has formal capability registration, recruitment via affordance pipeline, compositional governance (VetoChain), and dynamic context-based filtering. Reverie (visual) has the same raw capabilities but wired with less structure — static matrix selection, no registration protocol, ad-hoc governance, no impingement awareness. The primitives exist; Reverie doesn't use them.

## Problem

Two expression systems that should share meta-structure diverge architecturally:

- **Capability registration:** Daimonion has PerceptionBackend protocol + ToolCapability + SpeechProductionCapability. Reverie has manual instantiation, no protocol.
- **Recruitment:** Daimonion uses AffordancePipeline (4-weight scoring, Thompson sampling, Hebbian learning). Reverie uses a flat state matrix (stance × energy → preset family).
- **Governance:** Daimonion composes VetoChain + FallbackChain (deny-wins, extensible). Reverie hardcodes a guest multiplier and dwell timer.
- **Context:** Daimonion assembles 5 enrichment sources per utterance. Reverie reads stimmung + desk activity.
- **Modulation:** Both modulate output by system state, but with incompatible mechanisms.
- **Cross-modal:** Imagination produces content consumed independently by both. No coordination.

The differences are incidental (evolved separately), not structural (medium-specific). The medium-specific parts — shader uniforms vs LLM prompts, 16ms frame budget vs 3s tool timeout, WGSL vs tokenization — stay separate. Everything else converges.

## Principle

Every tool is a capability. Every preset is a capability. Every perception backend is a capability. They all declare what they provide, what they require, when they're available, and how they degrade. The recruitment protocol is universal: Submission → Selection → Gating. The governance model is compositional: deny-wins vetoes + priority-ordered fallbacks. The modulation bus is shared: perception signals flow to all consumers.

## Phase 1: Shared Capability Protocol

### Capability Interface

```python
@runtime_checkable
class Capability(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def category(self) -> CapabilityCategory: ...

    @property
    def resource_tier(self) -> ResourceTier: ...

    def available(self, ctx: SystemContext) -> bool: ...

    def degrade(self) -> str: ...
```

### CapabilityCategory

```python
class CapabilityCategory(enum.Enum):
    PERCEPTION = "perception"     # reads environment, produces behaviors
    TOOL = "tool"                 # executes actions on operator request
    EXPRESSION = "expression"     # produces output (speech, visual, notification)
    MODULATION = "modulation"     # adjusts parameters based on signals
```

### ResourceTier

Already exists in `tool_capability.py`. Reused without change:

```python
class ResourceTier(enum.Enum):
    INSTANT = "instant"   # <100ms, no external calls
    LIGHT = "light"       # <3s, API call or local query
    HEAVY = "heavy"       # >3s or GPU-intensive
```

### SystemContext

Replaces `ToolContext`. Same fields, used by all capability types:

```python
@dataclass(frozen=True)
class SystemContext:
    stimmung_stance: str = "nominal"
    consent_state: dict = field(default_factory=dict)
    guest_present: bool = False
    active_backends: frozenset[str] = field(default_factory=frozenset)
    working_mode: str = "rnd"
    experiment_flags: dict = field(default_factory=dict)
    tpn_active: bool = False
```

### CapabilityRegistry

Single registry, queryable across all categories:

```python
class CapabilityRegistry:
    def register(self, cap: Capability) -> None: ...
    def available(self, ctx: SystemContext,
                  category: CapabilityCategory | None = None) -> list[Capability]: ...
    def get(self, name: str) -> Capability | None: ...
    def all(self) -> list[Capability]: ...
```

Name uniqueness enforced at registration. `ToolRegistry` and `PerceptionEngine._backends` become views over this registry.

### Migration

| Existing Type | Change |
|--------------|--------|
| `PerceptionBackend` | Add `category=PERCEPTION`, `degrade()`. Already has `name`, `available()`. `resource_tier` derived from `tier` (FAST→INSTANT, SLOW→LIGHT, EVENT→INSTANT). |
| `ToolCapability` | Already conforms. `ToolContext` → `SystemContext`. |
| `SpeechProductionCapability` | Add `resource_tier=HEAVY` (GPU), `degrade()`. Already has `name`, `activation_cost`. |
| `ShaderGraphCapability` | Add `available(ctx)`, `resource_tier=HEAVY` (GPU), `degrade()`. |

Medium-specific methods (`contribute()`, `handler()`, `activate()`) stay on the concrete classes. The protocol is the shared surface.

## Phase 2: Shared Context Enrichment

### EnrichmentContext

Assembled once per tick, consumed by both systems:

```python
@dataclass(frozen=True)
class EnrichmentContext:
    timestamp: float
    stimmung: SystemStimmung
    active_goals: list[dict]
    health_summary: dict
    pending_nudges: list[dict]
    dmn_observations: list[str]
    imagination_fragments: list[dict]  # serialized ImaginationFragment
    perception_snapshot: dict           # flattened behavior values
```

### ContextAssembler

Gathers from canonical sources with caching:

```python
class ContextAssembler:
    def __init__(self, stimmung_path: Path, dmn_path: Path, imagination_path: Path,
                 goals_fn: Callable, health_fn: Callable, nudges_fn: Callable,
                 perception_fn: Callable) -> None: ...

    def assemble(self) -> EnrichmentContext: ...
```

Each source is a callable or file path. Assembly reads all at once (snapshot isolation — no mid-assembly drift). Caches with 2s TTL for fast repeated access within a tick.

### Consumers

**Daimonion:** `ContextAssembler.assemble()` → inject into system prompt via existing `_goals_fn`, `_health_fn` etc. The callables now delegate to the shared assembler.

**Reverie:** `ContextAssembler.assemble()` → `AtmosphericSelector` reads `stimmung.stance` + `health_summary` for preset decisions. `UniformModulator` reads `perception_snapshot` for signal values. Both read from the same `EnrichmentContext` instance.

### What Changes

Daimonion's 5 separate `_*_fn` callables still exist but delegate to `ContextAssembler`. Reverie's direct stimmung JSON reads replaced with `EnrichmentContext` access. New context sources wire into `ContextAssembler` once, appear in both systems.

## Phase 3: Unified Governance Composition

### Extract to shared/

`VetoChain`, `FallbackChain`, `Veto`, `Candidate` move from `agents/hapax_daimonion/governance.py` to `shared/governance.py`. Daimonion imports from new location.

### Reverie Governance

`AtmosphericSelector` wrapped in governance composition:

```python
class VisualGovernance:
    _veto_chain: VetoChain[SystemContext] = VetoChain([
        Veto("consent_pending",
             lambda ctx: ctx.consent_state.get("phase") != "consent_pending"),
        Veto("tpn_voice_session",
             lambda ctx: not ctx.tpn_active),
        Veto("resource_pressure",
             lambda ctx: ctx.stimmung_stance != "critical"),
    ])

    _fallback: FallbackChain[SystemContext, str] = FallbackChain([
        Candidate("critical_health",
                  lambda ctx: ctx.stimmung_stance == "critical",
                  "silhouette"),
        Candidate("operator_absent",
                  lambda ctx: "operator_absent" in ctx.experiment_flags,
                  "clean"),
    ], default="atmospheric")

    def evaluate(self, ctx: SystemContext, atmospheric: AtmosphericSelector,
                 stance: str, energy: str, available: list[str],
                 genre: str | None) -> str | None:
        veto = self._veto_chain.evaluate(ctx)
        if not veto.allowed:
            return None  # suppress transition

        action = self._fallback.evaluate(ctx)
        if action != "atmospheric":
            return action  # override preset

        return atmospheric.evaluate(stance, energy, available, genre)
```

The state matrix stays as the selection logic within the fallback default. Governance wraps it.

### Vetoes Shared Across Systems

Some vetoes apply universally:

| Veto | Daimonion | Reverie |
|------|-----------|---------|
| consent_pending | Blocks proactive speech | Blocks camera-derived overlays |
| guest_present | Suppresses consent-requiring tools | Reduces intensity (0.6x) |
| resource_critical | Downgrades to CANNED | Falls back to silhouette |

These use the same `Veto` instances, composed into system-specific chains.

### Guest Reduction

Currently a hardcoded 0.6x multiplier in `compute_gestural_offsets`. Becomes a governance-composed modulation: `GuestVeto` gates gestural offsets entirely when `guest_present && !consent_granted`, or applies the reduction factor when consent is granted but intensity should be reduced.

## Phase 4: Unified Modulation Bus

### SignalBus

Perception backends publish, all capabilities subscribe:

```python
class SignalBus:
    def publish(self, name: str, value: float) -> None: ...
    def snapshot(self) -> dict[str, float]: ...
```

No callback subscriptions — consumers call `snapshot()` on their tick cadence. This avoids cross-thread complexity. The bus is a synchronized dict of current signal values.

### Signal Sources

Perception backends publish after `contribute()`:

| Signal | Source Backend | Current Consumer | New Consumer |
|--------|--------------|-----------------|-------------|
| operator_energy | AttentionBackend | Reverie (manual) | Both (via bus) |
| desk_activity | ContactMicBackend | Reverie (manual) | Both (via bus) |
| gaze_direction | AttentionBackend | Reverie (manual) | Both (via bus) |
| person_count | IrPresenceBackend | Reverie (manual) | Both (via bus) |
| flow_score | PerceptionEngine | Daimonion only | Both (via bus) |
| vad_confidence | AudioInput | Daimonion only | Both (via bus) |
| resource_pressure | StimmungCollector | Daimonion (ad-hoc) | Both (via bus) |
| display_density | VisualLayerAggregator | Daimonion (ad-hoc) | Both (via bus) |

### ModulationBinding (Generalized)

Already defined in `effect_graph/modulator.py`. Generalized to serve both systems:

```python
@dataclass
class ModulationBinding:
    target: str          # "bloom.alpha" or "voice.word_limit"
    signal: str          # "operator_energy" (from SignalBus)
    scale: float = 1.0
    offset: float = 0.0
    smoothing: float = 0.85
```

Reverie binds shader params. Daimonion binds behavioral params (word limit, model tier threshold). Same structure, different targets.

### Daimonion Modulations Formalized

Currently scattered across `get_model_adaptive()`, `_density_word_limit()`, `tool.available()`. Become explicit bindings:

```python
# Voice modulation bindings (conceptual — applied via code, not shader uniforms)
ModulationBinding(target="voice.model_tier_threshold", signal="resource_pressure", scale=-0.3)
ModulationBinding(target="voice.word_limit", signal="display_density", scale=-15, offset=50)
ModulationBinding(target="voice.tool_suppression", signal="resource_pressure", scale=1.0)
```

These don't write to `/dev/shm` like Reverie's — they're consumed in-process. But the structure is identical, enabling uniform reasoning about what modulates what.

## Phase 5: Cross-Modal Recruitment

### Register Visual Capabilities in Affordance Pipeline

`ShaderGraphCapability` gets indexed in Qdrant alongside `SpeechProductionCapability`:

```python
affordance_pipeline.index_capability(
    name="visual_expression",
    description="Express emotional state, imagination content, and system awareness "
                "through dynamic visual rendering — shader techniques, color, motion, "
                "material quality, temporal rhythm",
    capability=visual_capability,
)
```

When `AffordancePipeline.select(impingement)` runs, it returns candidates from ALL expression categories — speech, visual, notification. The system recruits whichever modality (or modalities) scores highest for the impingement.

### ExpressionCoordinator

When imagination escalates a fragment and the affordance pipeline recruits multiple modalities, the coordinator ensures coherence:

```python
class ExpressionCoordinator:
    def coordinate(self, impingement: Impingement,
                   recruited: list[tuple[str, Capability]]) -> None:
        fragment = impingement.content.get("fragment")
        if fragment is None:
            return  # non-imagination impingement, no coordination needed

        for name, cap in recruited:
            if cap.category == CapabilityCategory.EXPRESSION:
                cap.activate(impingement, fragment=fragment)
```

**Speech activation:** The LLM gets the fragment's narrative as context in the volatile band. Already works via `generate_spontaneous_speech(impingement)`.

**Visual activation:** The fragment's 9 dimensions + material map to shader parameters:

| Fragment Dimension | Shader Parameter |
|-------------------|-----------------|
| luminosity | bloom.alpha |
| density | particle_count |
| velocity | drift.speed |
| turbulence | noise.scale |
| warmth | color_temperature |
| depth | parallax.layers |
| rhythm | stutter.freeze_chance |
| opacity | master_alpha |
| material (water/fire/earth/air/void) | preset variant |

The coordinator doesn't make decisions — it passes the same fragment to each recruited capability and lets each translate it into its medium.

### Imagination Loop Changes

Currently: `maybe_escalate(fragment) → Impingement` → Daimonion affordance pipeline only.

After: Escalation routes through `CapabilityRegistry.available(ctx, category=EXPRESSION)` → affordance pipeline returns candidates across all expression categories → `ExpressionCoordinator.coordinate()` distributes fragment to recruited capabilities.

### What Stays Separate

The imagination agent still writes to `/dev/shm/hapax-imagination/current.json` for Rust to hot-reload. This path continues to work — it's the low-level frame pipeline. The cross-modal recruitment adds a higher-level coordination layer that operates on `ImaginationFragment` semantics, not pixel-level rendering.

## File Map

### New Files

| File | Phase | Responsibility |
|------|-------|---------------|
| `shared/capability.py` | 1 | Capability protocol, CapabilityCategory, SystemContext, CapabilityRegistry |
| `shared/context.py` | 2 | EnrichmentContext, ContextAssembler |
| `shared/signal_bus.py` | 4 | SignalBus |
| `shared/expression.py` | 5 | ExpressionCoordinator |

### Extracted

| From | To | Phase | What |
|------|-----|-------|------|
| `hapax_daimonion/governance.py` | `shared/governance.py` | 3 | VetoChain, FallbackChain, Veto, Candidate |
| `effect_graph/modulator.py` (ModulationBinding) | `shared/signal_bus.py` | 4 | ModulationBinding generalized |

### Modified (Reverie)

| File | Phase | Change |
|------|-------|--------|
| `effect_graph/capability.py` | 1 | Implements Capability protocol |
| `effect_graph/visual_governance.py` | 3 | AtmosphericSelector wrapped in VetoChain + FallbackChain |
| `effect_graph/modulator.py` | 4 | Subscribes to SignalBus instead of manual signal dict |
| `agents/imagination.py` | 5 | Escalation routes through CapabilityRegistry |

### Modified (Daimonion)

| File | Phase | Change |
|------|-------|--------|
| `hapax_daimonion/tool_capability.py` | 1 | ToolCapability conforms to Capability, ToolContext → SystemContext |
| `hapax_daimonion/capability.py` | 1 | SpeechProductionCapability conforms to Capability |
| `hapax_daimonion/perception.py` | 1, 4 | PerceptionBackend conforms to Capability; publishes to SignalBus |
| `hapax_daimonion/__main__.py` | 1, 2, 5 | CapabilityRegistry replaces separate registries; ContextAssembler; ExpressionCoordinator |
| `hapax_daimonion/governance.py` | 3 | Imports from shared/governance.py |

### Not Changed

- Rust binary (`hapax-imagination`) — reads same `/dev/shm` files
- WGSL shaders — parameter flow unchanged
- Conversation pipeline internals — consumes same interfaces
- DMN daemon — produces same impingements
- LiteLLM config — model routing unchanged

## Dependency Graph

```
Phase 1 (Capability Protocol)
    ↓
Phase 2 (Shared Context)  ←→  Phase 3 (Unified Governance)
    ↓                              ↓
Phase 4 (Modulation Bus)
    ↓
Phase 5 (Cross-Modal Recruitment)
```

Phases 2 and 3 are independent of each other but both need Phase 1. Phase 4 needs 2+3. Phase 5 needs everything.

## Implementation Phasing

Each phase is a separate implementation plan → PR → merge cycle. Each produces working, testable software on its own:

- **Phase 1** deliverable: `shared/capability.py` + all existing capabilities conform + CapabilityRegistry queryable
- **Phase 2** deliverable: `shared/context.py` + both systems read EnrichmentContext + identical context verified
- **Phase 3** deliverable: `shared/governance.py` + Reverie governance composed + consent/axiom vetoes active
- **Phase 4** deliverable: `shared/signal_bus.py` + perception publishes + both systems subscribe + new signals auto-flow
- **Phase 5** deliverable: `shared/expression.py` + visual capabilities in affordance pipeline + imagination recruits both modalities + ExpressionCoordinator ensures coherence

## Queue Items

| ID | Title | Phase | Depends On |
|----|-------|-------|-----------|
| #017 | Shared Capability Protocol | 1 | — |
| #018 | Shared Context Enrichment | 2 | #017 |
| #019 | Unified Governance Composition | 3 | #017 |
| #020 | Unified Modulation Bus | 4 | #018, #019 |
| #021 | Cross-Modal Recruitment | 5 | #020 |
| #015 | Full Tool Recruitment (existing) | post-5 | #021 + validation telemetry |

## Non-Goals

- Merging daimonion and Reverie into one process (stay separate, coordinate via `/dev/shm`)
- Changing LLM prompt format (context injection stays text-based)
- Changing shader compilation pipeline (WGSL stays)
- Adding new perception backends (this is infrastructure, not new sensors)
- Queue #015 full tool recruitment (deferred, depends on #021 + validation sprint telemetry)
- Changing the Rust binary or wgpu pipeline (reads same files)
