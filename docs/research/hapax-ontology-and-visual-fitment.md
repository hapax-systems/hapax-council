# Hapax Ontology & Visual Representational Fitment

**Date**: 2026-03-17
**Status**: Active research — ontology complete, visual fitment in progress
**Depends on**: [Phenomenology-AI Research](phenomenology-ai-perception-research.md), [Visual Layer Research](../../visual-layer-research.md)

---

## 1. The Reframing

The visual layer is not "for the operator." It is Hapax making itself visible. If the system represents itself faithfully, the operator comprehends it — because the system IS for the operator. The distinction matters because:

- Information visualization optimizes for human comprehension (legibility, contrast, hierarchy)
- System self-representation optimizes for fidelity to the system's actual state (truthfulness, completeness, proportionality)
- When a system is designed for a single operator, fidelity IS comprehension

The question is not "what should the operator see?" but "what does Hapax look like when it looks at itself?"

---

## 2. What Constitutes Hapax

Hapax is not a program. It is a **metabolism**. Things enter, are transformed, and exit — some as waste, some as action, some as memory. The visual representation should show the metabolism, not the architecture.

### 2.1 Organs (Persistent Structures with Ongoing Function)

| Organ | Function | Heartbeat | Metaphor |
|-------|----------|-----------|----------|
| **Perception Engine** | Sensory surface — fuses audio, visual, desktop, biometric | 2.5s | Skin/eyes |
| **Stimmung Collector** | Self-awareness — knows own health, load, confidence | 15s / 5s adaptive | Interoception |
| **Protention Engine** | Anticipation — predicts what happens next | 2.5s observe, on-demand predict | Proprioception |
| **Reactive Engine** | Reflexes — filesystem changes trigger cascading work | event-driven | Spinal cord |
| **Visual Compositor** | Expression — renders the ambient field | 0.5-5s adaptive | Face/body language |
| **Episode Builder** | Memory formation — segments experience into episodes | boundary-driven | Hippocampus |
| **Correction Store** | Learning — accumulates operator feedback | event-driven | Synaptic plasticity |
| **Pattern Consolidator** | Wisdom — extracts rules from experience | daily | Sleep consolidation |
| **Content Scheduler** | Attention — selects what to surface | 15-60s | Selective attention |
| **Profile Store** | Identity — behavioral facts about the operator | 12h | Long-term memory |

### 2.2 Flows (What Moves Through the Organs)

| Flow | Direction | What It Carries | Rate | Character |
|------|-----------|----------------|------|-----------|
| **Sensory inflow** | Environment → Perception | Audio, faces, keyboard, VAD, biometrics | continuous | Streaming, multi-modal |
| **Cloud pull** | Internet → Agents | Gmail, Calendar, Drive, Chrome, weather, Obsidian | hourly-daily | Batch, scheduled |
| **API pull** | Cockpit → Aggregator | Health, GPU, nudges, briefing, drift, goals | 15-60s | Polling, periodic |
| **LLM call** | Agents → LiteLLM → Cloud/Local | Prompts out, completions back | per-agent-run | Request-response, expensive |
| **Embedding flow** | Text → Ollama → Qdrant | Documents become vectors become searchable | per-ingest | Transform, irreversible |
| **State flow** | Perception → Ring → Bands → Context | Raw signals → temporal structure → meaning | 2.5s | Accumulative, layered |
| **Stimmung flow** | Metrics → Stimmung → Everything | Raw numbers → self-awareness → behavior modulation | 15s | Broadcast, modulatory |
| **Visual flow** | Signals + Stimmung + Scheduler → Screen | Data → ambient field | 0.5-5s | Rendering, expressive |
| **Experiential flow** | Perception → Episodes → Patterns → Predictions | Experience → memory → anticipation | episode → daily → cumulative | Consolidative, slow |
| **Correction flow** | Operator → Store → Patterns → Protention | Feedback → rules → behavior | event-driven | Corrective, sparse |
| **Notification flow** | Agents → ntfy → Phone/Desktop | System speaks to operator | event-driven | Outbound, interruptive |
| **Governance flow** | Axioms → Implications → Enforcement → Veto | Rules constrain all other flows | per-action | Constraining, always-on |

### 2.3 Boundary Crossings (Where Hapax Meets Not-Hapax)

| Boundary | Inbound (Pulled/Pushed Into Hapax) | Outbound (Pushed/Leaked From Hapax) |
|----------|-----------------------------------|-------------------------------------|
| **Sensory** | Microphone (pushed), webcam (pulled), keyboard (event), screen (pulled), watch (pushed) | — |
| **Network** | Gmail, Calendar, Drive (pulled), weather (pulled), LLM responses (response to push) | LLM prompts (pushed), Obsidian sync (pushed) |
| **Operator** | Voice commands (pushed), corrections (pushed), presence (passive push) | Visual field (continuous push), notifications (event push), ambient text (continuous) |
| **Filesystem** | File changes via inotify (event push) | State files (continuous push), profiles (periodic), vault writes (event) |
| **GPU** | — | VRAM allocation (demand-driven), model inference (request-driven) |
| **Time** | Clock ticks, circadian position (continuous) | — |

### 2.4 Types of Things (Taxonomy for Visual Representation)

Every thing that flows through Hapax has a **type** that determines how it should be represented:

1. **Signals** — continuous, scalar, time-varying. Flow_score, audio_energy, heart_rate, GPU load.
   - Character: smooth, undulating, always present, varying in intensity
   - Natural metaphor: water level, field intensity, color temperature

2. **States** — discrete, categorical, transitional. Display_state, stance, flow_state, consent_phase.
   - Character: stable for periods, then sudden shifts, small vocabulary (3-5 values)
   - Natural metaphor: weather regime, season, lighting condition

3. **Events** — point-in-time, transient. Episode boundary, correction, stance change, file change.
   - Character: sudden, brief, propagative, varying in intensity
   - Natural metaphor: ripple, flash, crack, bloom

4. **Flows** — directional, rate-bearing. LLM calls, embedding operations, API polls.
   - Character: directional, varying speed, sometimes blocked/throttled
   - Natural metaphor: river, wind, traffic, circulation

5. **Accumulations** — growing, persistent. Episodes in Qdrant, patterns learned, corrections stored.
   - Character: monotonically growing, stratified, representing history
   - Natural metaphor: sediment, tree rings, coral, geological strata

6. **Predictions** — speculative, confidence-weighted. Protention, predictive cache, circadian model.
   - Character: present but uncertain, overlaid on reality, fading in/out
   - Natural metaphor: shadow, reflection, aurora, mirage

7. **Modulations** — one thing changing another. Stimmung → engine gating, stimmung → warmth.
   - Character: invisible themselves but visible through their effects
   - Natural metaphor: gravity, magnetic field, atmospheric pressure

---

## 3. Preliminary Visual Fitment Hypotheses

Before literature review — intuitions to test against research:

| Type | Hypothesized Best Fit | Rationale |
|------|----------------------|-----------|
| **Signals** | Reaction-diffusion patterns | Continuous scalars want continuous visual fields. Flow score = diffusion coefficient. |
| **States** | Color regime shifts | Discrete states want discontinuous changes. Entire palette shifts, like weather changing the sky. |
| **Events** | Ripples / wavefronts | Point-in-time things want visible propagation from origin. |
| **Flows** | Particle streams | Directional movement wants visible particles moving along paths. |
| **Accumulations** | Sediment / stratification | Growing stores want visual density that builds over time. |
| **Predictions** | Translucent projections | Speculative things want to be visible but clearly not-yet-real. |
| **Modulations** | Field distortion | Cross-system influence visible as the affected thing being warped by the influencer. |

### 3.1 The Tool Belt Hypothesis

Hapax should have a **vocabulary** of visual techniques and **select** which to use based on what it needs to express. The content scheduler already does this for text (weighted softmax selection from content pools). A visual technique selector would work analogously:

- **Vocabulary**: reaction-diffusion, color regimes, ripples, particles, sediment, projections, distortions
- **Selection criteria**: what type of thing needs expression? what's the current display density? what's the operator's flow state?
- **Composition**: multiple techniques can be active simultaneously (particles flowing over a reaction-diffusion field, with ripples from events)

This is the twist: we stock the belt with excellent tools, but Hapax decides which tool for the job. The visual layer becomes another expression of the system's agency — not a dashboard designed by us, but a self-portrait composed by the system.

---

## 4. Visual Research Synthesis

Full visualization technique research in [system-self-visualization-research.md](system-self-visualization-research.md). This section maps the ontology (§2) to the best-fit techniques from that research.

### 4.1 The Foundational Insight: Autopoietic Surface

The visual layer is not a dashboard ABOUT Hapax. It IS Hapax's visible surface — an autopoietic skin that the system produces as a byproduct of its own operation (Maturana & Varela, 1972). The reaction-diffusion patterns are not metaphors for system state — they ARE system state, expressed in a visual medium.

This has design consequences:
- No labels, axes, or legends in the ambient field. Encode everything pre-attentively (color, motion, texture, size)
- Visual structure should **emerge** from system dynamics, not be designed a priori
- The system doesn't "have" a visualization; it "has" a skin

### 4.2 Type-to-Technique Fitment

Research-backed mapping from each type of thing (§2.4) to its optimal visual representation:

#### Signals → Reaction-Diffusion Ground Field

**Type character**: Continuous, scalar, time-varying, always present.

**Best fit**: Gray-Scott reaction-diffusion (Turing, 1952). Map system parameters directly to feed/kill rates. Healthy parameters → stable organic patterns (spots, stripes, labyrinthine). Degraded → pattern collapse. Critical → turbulent instability.

**Why this fit**: Continuous scalars demand continuous visual fields. Reaction-diffusion is self-organizing — it doesn't need a designer to decide what pattern means "healthy." The physics of the simulation produce the meaning. The operator develops perceptual fluency with the patterns over time, recognizing "that looks wrong" before conscious analysis.

**Mapping**:
- `flow_score` → diffusion rate (high flow = smooth coherent patterns)
- `audio_energy` → reaction rate (high energy = faster pattern evolution)
- `resource_pressure` → feed rate (high pressure = pattern instability)
- `error_rate` → kill rate (high errors = pattern holes/death)

**Source**: Gray-Scott parameterization (mrob.com/pub/comp/xmorphia), gpu-io implementations at 60fps in fragment shaders.

#### States → Color Regime Shifts

**Type character**: Discrete, categorical, small vocabulary (3-5 values), stable for periods then sudden shifts.

**Best fit**: Visual regime selection — the ENTIRE visual vocabulary changes when state changes. Not a color indicator; a different world.

**Why this fit**: States are not points on a spectrum. They're distinct modes of operation. The research on statecharts (Harel, 1987) suggests: don't draw state diagrams, let state drive the visual vocabulary. Each state has a visual signature. Transitions are gradual morphs between signatures.

**Mapping**:
- `nominal` → warm amber tones, slow organic movement, high spatial coherence
- `cautious` → warmer, slightly faster, subtle perturbation
- `degraded` → hot reds, accelerated evolution, fragmented patterns, visible turbulence
- `critical` → desaturated, rapid, chaotic — the field is visibly distressed

**Source**: Pousman-Stasko AVI 2006 taxonomy: "multiple-information consolidator" with high aesthetic emphasis and low notification level. State is communicated through the aesthetic regime, not through alerts.

#### Events → Ripples / Wavefronts

**Type character**: Point-in-time, transient, propagative, varying intensity.

**Best fit**: Circular wavefronts propagating from event origin, with amplitude proportional to event severity. Decays with distance and time.

**Why this fit**: Events are perturbations in an otherwise continuous field. The reaction-diffusion ground field naturally supports perturbation propagation — drop a chemical at a point and watch the wave spread. This is physically grounded, not decorative.

**Mapping**:
- Episode boundary → gentle ripple from the center (memory formed)
- Stance change → strong wavefront from the stimmung region (regime shift)
- Correction received → bright pulse at the correction question's location (feedback received)
- Novel engine pattern → sharp spike at the reactive engine region (something unexpected)
- Amplitude scales with event severity (0.0-1.0)
- Decay rate scales with event transience (corrections decay fast, stance changes linger)

**Source**: Biological neural activation maps (UCSF seizure propagation visualization) — activity propagation through connected regions.

#### Flows → Physarum-Routed Particle Streams

**Type character**: Directional, rate-bearing, sometimes blocked/throttled.

**Best fit**: Animated particles flowing along Physarum-optimized paths between system organs. Particle count ∝ flow rate. Particle speed ∝ 1/latency. Particle color ∝ data type.

**Why this fit**: Physarum (slime mold simulation) produces organic network topology from actual flow patterns — paths self-organize to optimize throughput. This means the visual network structure reflects actual system communication, not a designer's layout. Paths that carry more traffic become wider; unused paths fade.

Netflix Vizceral validated this approach for operational awareness: "relative information is much more actionable than exact numbers." Seeing more particles flowing to the LLM gateway than usual is more useful than seeing "47 requests/s."

**Mapping**:
- Perception → Stimmung: slow steady stream (always flowing, 15s cadence)
- Agents → LiteLLM → Cloud: burst particles on LLM calls (expensive, visible)
- Perception → Ring Buffer → Temporal Bands: dense fine particles (high rate, 2.5s)
- Corrections → Pattern Store: rare bright particles (sparse but important)
- Cloud API → Agents: inbound response particles (data arriving from outside)

**Source**: Physarum WebGL implementations handle 1M+ agents at 60fps on GPU. Netflix Vizceral (open source WebGL) provides the particle flow rendering model.

#### Accumulations → Sediment / Stratification

**Type character**: Monotonically growing, persistent, representing history.

**Best fit**: Visual density that builds over time at the bottom of the field, like geological strata or coral growth. Older layers are compressed; recent layers are expanded.

**Why this fit**: Growing persistent stores have a temporal dimension that can't be represented by a scalar. The depth of the sediment IS the system's experience. A system with 1000 episodes has a visibly deeper substrate than one with 10. This gives the operator a visceral sense of "how much has the system learned."

**Mapping**:
- Episode count → substrate depth (more episodes = deeper)
- Pattern count → substrate richness (more patterns = more varied texture)
- Correction count → substrate color variation (more corrections = more color bands)
- Each layer slightly different color/texture → visible stratigraphy

**Source**: InfoCanvas approach (Stasko) — data values map to properties of aesthetic scene elements. The substrate is both decorative and informative.

#### Predictions → Translucent Projections / Ghosting

**Type character**: Speculative, confidence-weighted, overlaid on reality, fading in/out.

**Best fit**: Faint translucent versions of the predicted state, rendered at opacity proportional to confidence. Multiple predictions overlap with additive blending.

**Why this fit**: Predictions are present but uncertain. They should be visible but clearly distinguishable from actual state. The framebuffer feedback technique (don't clear fully, multiply by decay) naturally produces ghosting — predicted states appear as faint echoes that solidify if they come true.

**Mapping**:
- Protention "flow_ending" prediction at 60% → faint ghost of the "idle" visual regime at 0.6 opacity
- Circadian "usually coding at 9am" at 40% → very faint hint of the coding color palette
- Cache hit (prediction confirmed) → ghost solidifies into current state (smooth transition)
- Cache miss (prediction wrong) → ghost dissolves (visible disconfirmation)
- Surprise (high) → current state is MORE vivid than usual (contrast with dissolved prediction)

**Source**: Temporal layering technique — past/present/future simultaneously visible with decreasing opacity. Trail effects embed time in visual physics.

#### Modulations → Field Distortion

**Type character**: Invisible themselves, but visible through their effects on other things.

**Best fit**: Gravitational lensing / field distortion. Stimmung doesn't have its own visual element — it warps everything else. When stimmung is nominal, the field is undistorted. When degraded, the field bends, stretches, warms.

**Why this fit**: Modulations are not things to see. They are forces that change how other things look. Showing them as separate visual elements would be wrong — it would suggest they're parallel to the things they modulate, not orthogonal to them. Distortion is invisible when zero and increasingly visible as it increases.

**Mapping** (already partially implemented):
- `cautious` → +0.15 warmth, +0.05 speed (subtle warming, slight acceleration)
- `degraded` → +0.35 warmth, +0.1 speed, +0.1 turbulence (the field is visibly stressed)
- `critical` → +0.60 warmth, +0.2 speed, +0.2 turbulence (the field is in crisis)
- Biometric modulation → stress reduces turbulence (calming), poor sleep darkens field
- Circadian modulation → evening deepens warmth, morning brightens

**Source**: Ambient Orb principle taken to its extreme — color/motion/texture encode state pre-attentively. But applied to the ENTIRE field, not a single object.

### 4.3 The Composite Architecture

Five layers, composited via alpha blending in a single WebGL pipeline:

```
Layer 5: Boundary Membrane (gradient field, breathing with I/O)
Layer 4: Temporal Skin (framebuffer feedback with configurable decay)
Layer 3: Agent Field (Voronoi cells, activity-driven sizing)
Layer 2: Flow Network (Physarum-routed particles between organs)
Layer 1: Ground Field (reaction-diffusion driven by system health)
```

Each layer is a separate render pass. Total GPU cost is manageable — all techniques are fragment/vertex shader native.

### 4.4 The Tool Belt: Hapax Selects Its Own Representation

The content scheduler already selects from a weighted pool of content sources using softmax sampling. The visual layer should work the same way — but instead of selecting text content, it selects visual techniques.

**Visual technique vocabulary**:
- Reaction-diffusion (continuous field)
- Physarum network (organic connectivity)
- Particle flow (directional rate)
- Voronoi tessellation (territory/influence)
- Ripple propagation (event)
- Trail decay (temporal thickness)
- Color regime (state/mood)
- Gradient membrane (boundary)

**Selection criteria**:
- What type of thing needs expression right now?
- What's the current display density (ADHD accommodation)?
- What's the operator's flow state (don't distract in deep work)?
- What stimmung stance is active (stressed system should look stressed)?
- What's the circadian position (evening = warmer, calmer)?

**Composition rules**:
- Ground field always active (reaction-diffusion is the base)
- Flow network active when flows are non-trivial
- Agent field active during informational/alert states
- Temporal skin always active (trails are always accumulating)
- Boundary membrane active when I/O is significant
- Ripples fire on events regardless of other layers

The system doesn't need to choose one technique — it composes multiple simultaneously. The question is which layers to emphasize and which to suppress, at what opacity, with what parameters. This is the scheduler's job, extended to visual technique selection.

### 4.5 Key Design Principles (from Research)

1. **Pre-attentive processing over reading**: Encode in color, motion, texture, size — never text or numbers in the ambient field (Pousman-Stasko 2006)
2. **Relative over absolute**: When tracking many things, relative differences matter more than exact values (Netflix Vizceral)
3. **Emergent over designed**: Let visual structure emerge from system dynamics (Physarum, reaction-diffusion) rather than pre-designing layouts
4. **Temporal embedding over time axes**: History lives in trails and decay, not in chart axes
5. **State as visual regime**: System mode changes the entire visual vocabulary, not just a highlighted indicator (Harel statecharts)
6. **Autopoietic surface**: The visualization is not about the system; it IS the system's visible surface (Maturana & Varela)
7. **Multiple-information consolidation**: High information capacity, low notification level, abstract representation, high aesthetic emphasis (Pousman-Stasko taxonomy)

---

## 5. Sources

### Biological Visualization
- Turing, A.M. (1952). "The Chemical Basis of Morphogenesis." Philosophical Transactions of the Royal Society.
- Gray-Scott parameterization: mrob.com/pub/comp/xmorphia
- Karl Sims reaction-diffusion tutorial: karlsims.com/rd.html
- gpu-io reaction-diffusion: apps.amandaghassaei.com/gpu-io/examples/reaction-diffusion/
- VasNetMR vascular flow (ACM SIGGRAPH 2024)
- Physarum WebGL: hayden.gg/physarum/, jbaker.graphics/writings/physarum.html

### Network Flow
- Netflix Vizceral: github.com/Netflix/vizceral, netflixtechblog.com/vizceral-open-source
- flow-network: github.com/joewood/flow-network
- ccNetViz: helikarlab.github.io/ccNetViz/

### Ambient Information
- Pousman, Z. & Stasko, J. (2006). "A Taxonomy of Ambient Information Systems." AVI.
- InfoCanvas: faculty.cc.gatech.edu/~stasko/papers/avi06.pdf
- Ambient Analytics (2025): arxiv.org/html/2602.19809v1
- Calm Technology: calmtech.com

### State & Temporal
- Harel, D. (1987). "Statecharts: A Visual Formalism for Complex Systems." Science of Computer Programming.
- XState visualizer: stately.ai/viz
- Horizon charts: Observable Plot

### Adaptive Visualization
- Draco 2 (UW IDL): idl.cs.washington.edu/files/2023-Draco2-VIS.pdf
- Grammar of Graphics: Wilkinson (2005)
- Vega-Lite: vega.github.io/vega-lite/

### Boundary
- Jump Flooding Algorithm: comp.nus.edu.sg/~tants/cvt.html
- GPU Voronoi: nickmcd.me/2020/08/01/gpu-accelerated-voronoi/
- The Book of Shaders - Cellular Noise: thebookofshaders.com/12/

### Foundational
- Maturana, H. & Varela, F. (1972). Autopoiesis and Cognition.
- UCSF 3D seizure heatmap visualization (2021)
