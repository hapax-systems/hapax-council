# Reverie Adaptive Compositor

**Date:** 2026-03-31
**Status:** Design approved
**Context:** Audit of Reverie visual surface against research and design intention revealed the system was a fixed 7-pass shader pipeline. The operator confirmed the target is an adaptive compositing engine driven by the impingement cascade, with multimedia content injection, no prescribed semantics, and reactive cross-modal coupling with Daimonion.

---

## Design Decisions (from brainstorm)

| Question | Decision | Rationale |
|----------|----------|-----------|
| Operational vs phenomenological vs both | **Both** | Mixer adapts expressiveness to what needs expression |
| Shader vocabulary | **Curated 12 nodes**, fresh evaluation not anchored on original 5 | Research 5 were pre-effect-graph; evaluate all 54 against ontology |
| Architecture | **Core + Satellites** | Core = always-running phenomenological substrate. Satellites recruited on demand for operational expressiveness |
| Semantic assignment | **None** — impingement cascade decides | Hardcoded health→param tables are psycho-semantic magic numbers |
| Surface model | **Compositing engine** — DMN is the VJ | Multiple content streams layered and blended, effects modulate appearance |
| Content sources | **Raw RGBA buffer protocol + native text** | Any process that produces pixels can participate. Text rendered natively at GPU resolution |
| Cross-modal sync | **Reactive coupling** | Daimonion↔Reverie influence each other bidirectionally, not shared clock |

---

## 1. Architecture

Reverie is a compositing engine. The DMN is the VJ. Content streams (raw RGBA buffers from any source + native text) are layered and blended, with shader effects modulating how they appear. The impingement cascade — not prescribed semantic mappings — drives what appears, how it's blended, and which effects modulate it.

### Three Subsystems

**Content Selector** — decides WHAT to show. Recruited by impingements. Sources: any process that writes RGBA frames to shm, plus native text. The DMN, imagination loop, camera daemons, screen capture, data visualizers — anything that can produce pixels.

**Effect Mixer** — decides HOW it looks. 12 curated shader nodes available as effects. The mixer sets per-node activation weights based on which affordances the impingement cascade recruits. No hardcoded parameter tables. The visual chain capability's 9 dimensions remain the abstraction layer, but the mixer does not prescribe which dimension means what.

**Cross-Modal Coupler** — reactive coupling between Reverie and Daimonion. Vocal energy creates visual impingements. Visual salience creates vocal impingements. Bidirectional, not shared-clock. The cascade decides what the coupling produces.

---

## 2. Curated Shader Vocabulary (12 Nodes)

Evaluated all 54 shader nodes against the Hapax ontology (7 types: signals, states, events, flows, accumulations, predictions, modulations) and Bachelard phenomenology. Each node selected because it provides a unique expressive dimension no other node in the set covers.

### Core (8 nodes, always running)

| Node | Expressive Role | Unique Contribution |
|------|----------------|---------------------|
| **noise_gen** | Procedural substrate | FBM texture for materialization gating. The "air" content crystallizes from. |
| **reaction_diffusion** | Living ground field | Self-organizing patterns from 2 params. Nothing else has emergent spatial complexity. Temporal (`@accum_rd`). |
| **colorgrade** | Color regime | Palette shift = regime shift. Stimmung drives the entire color world. |
| **drift** | Spatial coherence | Gentle displacement field. Coherence parameter makes modulations visible as proportional warping. |
| **breathing** | Rhythmic pulse | The surface breathes. Cadence = system heartbeat. Without it, everything feels dead. |
| **feedback** | Temporal persistence | Frame-to-frame accumulation with trace-aware decay. Afterimages. Bachelard Amendment 2. Temporal (`@accum_fb`). |
| **content_layer** | Imagination content | DMN fragments materialize from substrate. Bachelard Amendments 1, 3, 5. |
| **postprocess** | Final composition | Vignette, sediment, final grade. Enclosure and history. |

### Satellites (4 nodes, recruited by mixer)

| Node | Expressive Role | Unique Contribution | Insertion Point |
|------|----------------|---------------------|-----------------|
| **fluid_sim** | Flow dynamics | Velocity field + vorticity + advection. Directional movement with inertia. Temporal (`@accum_fluid`). | After breathing, before feedback |
| **trail** | Temporal thickness | Explicit velocity encoding. Motion→visual width. Multiple blend modes. Distinct from feedback (additive vs multiplicative). Temporal (`@accum_trail`). | After feedback, before content |
| **voronoi_overlay** | Spatial partitioning | Organic cellular structure. Agent territory. Nothing else creates boundary topology. | After content, before postprocess |
| **echo** | Ghosted predictions | Discrete temporal copies with exponential decay. Protention states as fading echoes. Temporal (`@accum_echo`). | After content, before postprocess |

### Nodes Excluded

- **particle_system** — Fragment shader approximation; fluid_sim covers flow better.
- **warp** — Overlaps with drift; drift's coherence parameter is more nuanced.
- **syrup** — Expressive but niche; fluid_sim covers the fluid quality. Available in presets.
- **slitscan** — Temporal stratification fights content_layer on an always-on surface.
- **All VJ/aesthetic nodes** (datamosh, vhs, neon, trap, screwed, glitch, ascii, halftone, thermal, nightvision, silhouette, ambient) — expression *styles*, not expression *capabilities*. Belong in presets for studio use, not the cognitive vocabulary.

---

## 3. Content Protocol

One protocol, any source. The surface accepts content via a shm bus.

### Buffer Format

Content sources write to `/dev/shm/hapax-imagination/sources/{source_id}/`:

```
{source_id}/
  frame.rgba      # Raw RGBA buffer (width x height x 4 bytes)
  manifest.json   # Metadata, updated atomically
```

### Manifest Schema

RGBA content:
```json
{
  "source_id": "camera-overhead",
  "content_type": "rgba",
  "width": 1920,
  "height": 1080,
  "layer": 1,
  "blend_mode": "screen",
  "opacity": 0.7,
  "z_order": 10,
  "ttl_ms": 5000,
  "tags": ["perception", "spatial"]
}
```

Text content (rendered natively by Rust at GPU resolution):
```json
{
  "source_id": "imagination-fragment-42",
  "content_type": "text",
  "text": "the sound of rain on corrugated iron",
  "font_weight": 300,
  "opacity": 0.6,
  "layer": 1,
  "z_order": 20,
  "tags": ["imagination", "dwelling"]
}
```

### Source Lifecycle

- Sources appear when their directory is created (inotify on `/sources/`)
- Sources refresh by updating frame.rgba + manifest.json atomically
- Sources expire when `ttl_ms` elapses without a refresh, or directory is removed
- The compositing engine scans `/sources/` each frame — new sources fade in, expired sources fade out
- The surface has no opinion about what sources exist. It composites whatever it finds.

### Content Selector Role

The Content Selector (Python, driven by impingement cascade) does not produce frames. It tells producers to start/stop, and writes manifest.json to control blending. When an impingement recruits visual content:

1. Identifies which source can fulfill it (Qdrant affordance similarity)
2. Signals the producer to start writing frames (or resolves content itself, as imagination_resolver does today)
3. Writes manifest with blend/opacity/layer from impingement activation strength
4. Removes manifest when impingement decays

---

## 4. Effect Mixer

No prescribed semantics. The mixer translates impingement cascade activations into graph mutations and parameter updates.

### Affordance Registration

At startup, the mixer registers all 12 node affordances in Qdrant with embeddings from expressive descriptions:

```
reaction_diffusion: "self-organizing emergent spatial patterns, regime-sensitive"
fluid_sim: "directional flow with inertia, vorticity, viscous movement"
feedback: "temporal persistence, afterimage, dwelling trace"
trail: "motion history, velocity as visual thickness, temporal accumulation"
voronoi_overlay: "spatial partitioning, organic boundaries, cellular territory"
echo: "discrete temporal copies, ghosting, fading repetition"
noise_gen: "procedural texture, substrate, continuous field"
colorgrade: "palette regime, color world shift, atmospheric tone"
drift: "spatial displacement, coherence modulation, gentle warping"
breathing: "rhythmic pulse, expansion and contraction, life cadence"
content_layer: "content materialization, imagination surface, phenomenology"
postprocess: "final composition, enclosure, vignette, sediment"
```

Content-type affordances are also registered:

```
camera-feed: "live spatial perception, room awareness, presence"
imagination-text: "narrative fragment, poetic image, dwelling thought"
imagination-image: "resolved visual content, concrete reference"
waveform-viz: "acoustic energy shape, sound made visible"
data-plot: "structured information, measurement, trend"
```

When an impingement fires, cosine similarity determines which combination of effects and content types is recruited.

### Activation Flow

1. Impingement arrives from cascade
2. Cosine similarity against all registered visual affordances
3. Affordances above threshold produce activation weights (0.0–1.0)
4. Visual chain breakpoint curves translate activation weights to per-node shader parameters
5. Core nodes: parameter weights written to uniforms.json (existing mechanism)
6. Satellite nodes: recruited into/dismissed from plan.json when crossing threshold

### Core vs Satellite Behavior

**Core nodes** are always in the graph. Their activation weights modulate intensity but never reach zero — the surface always has a living substrate.

**Satellite nodes** are recruited when their affordance fires above recruitment threshold. The mixer adds the node to plan.json with edges at the appropriate insertion point. When the affordance decays below threshold, the node is removed on the next plan write.

### No Semantic Prescription

The mixer has zero `if stance == "degraded"` branches. Zero hardcoded parameter tables. The only constants are infrastructure parameters:

- **Decay rate** — compressor release envelope, how fast activations fade
- **Recruitment threshold** — how strong an affordance must fire to recruit a satellite
- **Refractory period** — cross-modal damping (500ms)
- **Guest reduction factor** — governance constraint (0.6)

### Mixer Subsumes Actuation Loop

The mixer replaces `ReverieActuationLoop`. All actuation responsibilities (consume impingements, decay dimensions, write uniforms, track traces, apply governance) move into the mixer's tick cycle.

### Tick Cycle (1s)

```python
async def tick(self, dt: float):
    # 1. Read cross-modal input
    acoustic = self._read_acoustic_impulse()
    if acoustic:
        self._inject_impingement(acoustic)

    # 2. Consume pending impingements
    impingements = self._drain_impingements()

    # 3. Match against visual affordances (Qdrant cosine similarity)
    activations = await self._match_affordances(impingements)

    # 4. Decay all current activations (compressor release)
    self._decay_activations(dt)

    # 5. Merge new activations
    self._merge_activations(activations)

    # 6. Core: compute uniforms from active dimensions
    uniforms = self._compute_uniforms()

    # 7. Satellites: recruit/dismiss based on activation thresholds
    graph_changed = self._update_satellite_graph()

    # 8. Content: update source manifests (opacity, blend, ttl)
    self._update_content_manifests()

    # 9. Trace: update dwelling trace state
    self._update_trace(dt)

    # 10. Governance: apply veto chain + guest reduction
    uniforms = self._apply_governance(uniforms)

    # 11. Write outputs
    self._write_uniforms(uniforms)
    if graph_changed:
        self._write_plan()
    self._write_visual_salience()
```

---

## 5. Cross-Modal Coupler

Reactive coupling between Reverie and Daimonion. A lightweight relay running as a coroutine inside the DMN daemon (which already hosts both actuation loops).

### Daimonion → Reverie

Vocal energy (RMS amplitude from TTS output) written to `/dev/shm/hapax-visual/acoustic-impulse.json`:

```json
{
  "source": "daimonion",
  "timestamp": 1711907400.0,
  "signals": {
    "energy": 0.7,
    "onset": true,
    "pitch_hz": 185.0
  }
}
```

The mixer reads this and injects it as an impingement with source `"daimonion"`. The cascade recruits whichever visual affordances are semantically relevant.

### Reverie → Daimonion

Visual salience written to `/dev/shm/hapax-dmn/visual-salience.json`:

```json
{
  "source": "reverie",
  "timestamp": 1711907400.1,
  "signals": {
    "salience": 0.8,
    "content_density": 3,
    "regime_shift": false
  }
}
```

The Daimonion impingement consumer reads this and injects it as an impingement with source `"reverie"`. The cascade recruits vocal affordances.

### Damping

Refractory period (500ms default) per direction prevents runaway visual→vocal→visual feedback oscillation. This is a safety constraint, not a semantic one.

---

## 6. Compositing Engine (Rust)

The DynamicPipeline evolves from a linear shader graph into a layered compositing engine.

### Layer Model

```
L0  Ground Field    — Core shader graph (noise → R-D → colorgrade → drift → breathing → feedback)
L1  Content         — content_layer shader (Bachelard materialization/material/immensity)
                      compositing N content streams (RGBA buffers from shm + native text)
L2  Effects         — Satellite shader nodes applied over composited L0+L1
L3  Temporal Skin   — trail/echo nodes operating on the full composite
L4  Post            — postprocess (vignette, sediment, final grade) → output + shm JPEG
```

The content_layer shader remains the Bachelard phenomenology surface — it gates how content materializes from the substrate (Amendment 1), applies material quality (Amendment 3), and handles immensity entry (Amendment 5). The new content source protocol provides the raw content; content_layer controls how it appears.

### Plan.json v2

```json
{
  "version": 2,
  "layers": [
    {
      "id": "ground",
      "passes": ["noise", "rd", "colorgrade", "drift", "breathing", "feedback"]
    },
    {
      "id": "content",
      "passes": ["content_layer"],
      "source": "shm_scan",
      "blend_onto": "ground"
    },
    {
      "id": "effects",
      "passes": [],
      "blend_onto": "content"
    },
    {
      "id": "temporal",
      "passes": [],
      "blend_onto": "effects"
    },
    {
      "id": "post",
      "passes": ["postprocess"],
      "blend_onto": "temporal"
    }
  ]
}
```

Satellite nodes appear in `effects.passes` or `temporal.passes` when recruited by the mixer.

### Content Source Scanning (New Rust Module)

`content_sources.rs` replaces `ContentTextureManager`. Each frame:

1. Scan `/dev/shm/hapax-imagination/sources/` for directories
2. For each source with valid manifest.json: read frame.rgba (mmap for zero-copy), create/update GPU texture
3. For text sources: render glyphs to texture via `ab_glyph` (already a dependency)
4. Sort by z_order, composite onto ground layer output using per-source blend mode and opacity
5. Expire sources whose `ttl_ms` has elapsed

### GPU Budget

- Core ground field: 6 passes
- Content compositing: 1 pass per active source (~3-5 typical)
- Satellite effects: 0-4 passes (recruited on demand)
- Temporal skin: 0-2 passes
- Post: 1 pass
- **Total: ~12-15 passes typical, 20 max**

At 12ms/frame on RTX 3090 for 7 passes currently, 20 passes stays under 33ms (30fps target).

### Backward Compatibility

During migration, the Rust binary reads both the old 4-slot JPEG format and the new sources/ protocol, preferring sources/ when present.

---

## 7. Migration Path

### Phase 1: Expand the Ground Field
- Add `reaction_diffusion` to `reverie_vocabulary.json` between noise and colorgrade
- R-D is temporal (`@accum_rd`); temporal texture init already fixed (PR #483)
- Visual chain gets R-D parameter bindings (already defined, currently targeting absent node)
- **Result:** Core goes from 7 to 8 passes. Linear chain. Everything else unchanged.

### Phase 2: Content Source Protocol
- New Rust module `content_sources.rs` replacing `ContentTextureManager`
- Shm source scanning, manifest parsing, GPU texture management
- Native text rendering via `ab_glyph`
- Backward compat with old 4-slot format
- Update `imagination_resolver.py` to write new protocol
- **Result:** Arbitrary content injection. Old path still functions.

### Phase 3: Layer Compositing
- Plan.json v2 with layer structure
- DynamicPipeline renders layers with inter-layer compositing
- Satellite insertion/removal via plan.json layer mutation
- **Result:** Full compositing engine.

### Phase 4: The Mixer
- New `agents/reverie/mixer.py` subsuming `ReverieActuationLoop`
- Affordance registration in Qdrant for 12 nodes + content types
- Impingement-driven activation, satellite recruitment/dismissal
- Content manifest management
- **Result:** DMN is the VJ. Cascade drives everything.

### Phase 5: Cross-Modal Coupler
- Acoustic impulse signal: Daimonion → shm → Reverie impingement
- Visual salience signal: Reverie → shm → Daimonion impingement
- Refractory damping
- **Result:** Synesthetic coupling.

### Dependencies

```
Phase 1 ──► Phase 3
Phase 2 ──► Phase 3
Phase 3 ──► Phase 4
Phase 4 ──► Phase 5
```

Phases 1 and 2 are independent and can run in parallel.

### What Stays
- `visual_chain.py` — affordance library, parameter breakpoints
- `agents/reverie/governance.py` — VetoChain, guest reduction
- `agents/imagination.py` — ImaginationLoop, fragments, reverberation
- `agents/dmn/vision.py` — multimodal visual observation
- All 54 shader nodes — available for presets/studio
- All Bachelard amendments — content_layer shader unchanged

### What Goes
- `ReverieActuationLoop` — subsumed by mixer
- `ContentTextureManager` (Rust) — replaced by content_sources.rs
- Plan.json v1 format — replaced by v2 (backward compat during migration)
- Hardcoded 4-slot content system — replaced by N-source protocol
