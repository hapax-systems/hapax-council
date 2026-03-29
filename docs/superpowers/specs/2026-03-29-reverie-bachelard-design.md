# Hapax Reverie — Bachelardian Phenomenology Alignment

## Summary

Six amendments to Hapax Reverie that align the visual expressivity surface with Gaston Bachelard's phenomenology of reverie and material imagination. These transform Reverie from a display system into one that enacts the ontology of reverie itself.

The amendments are independent and can be implemented in any order. Each produces a testable change.

## Amendment 1: Materialization from Substrate

**Bachelard**: Reverie must be "written with emotion" in the act — not recounted. Images do not appear; they materialize. The image and its space are co-emergent.

**Current**: Content textures fade in uniformly via opacity ramp (0.0 → target over ~0.5s). Content appears ON TOP of the procedural field via screen blend.

**Change**: Content should condense FROM the procedural field. The content layer shader should derive its initial visibility from the procedural noise — where the gradient's FBM is brightest, content crystallizes first. As the fragment's fade progresses, the noise threshold drops until the full content is visible.

Additionally, low-salience content should first appear at the periphery (corners, edges) and migrate inward as salience increases. High-salience content materializes near center immediately.

### Implementation

In `content_layer.wgsl`, modify `content_opacity()` to gate visibility by procedural noise:

```wgsl
// Materialization: content crystallizes from the procedural noise field
let materialization_noise = hash21(uv * 30.0 + u.time * 0.05);
let materialization = smoothstep(1.0 - base_opacity, 1.0 - base_opacity + 0.3, materialization_noise);
opacity *= materialization;
```

For corner incubation, modify `modulate_uv()`:

```wgsl
// Low salience → peripheral placement. High salience → center.
let center_pull = base_opacity;  // salience drives centering
let corner_offset = (1.0 - center_pull) * 0.3;
muv += (muv - 0.5) * corner_offset;  // push toward edges when low salience
```

### Files
- Modify: `hapax-logos/crates/hapax-visual/src/shaders/content_layer.wgsl`

---

## Amendment 2: Dwelling and Trace

**Bachelard**: Images that have dwelt should leave traces. The space remembers. "The past is never recalled as-is; it is always transformed by the present mind."

**Current**: Feedback shader applies uniform decay (0.97 L per frame, 0.5° hue shift) to the entire previous frame. When content fades, it decays uniformly. No fragment-specific trace.

**Change**: When content fades out, its final state persists in the feedback buffer with locally reduced decay. The feedback shader receives a trace intensity value from the content layer — regions where content recently dwelt decay slower, creating a ghostly afterimage that persists 3-5 seconds longer than the background.

### Implementation

Add `trace_center: vec2<f32>` and `trace_radius: f32` and `trace_strength: f32` to feedback uniforms. The content layer updates these when a slot transitions from active to inactive.

In `feedback.wgsl`:

```wgsl
let dist_to_trace = distance(vec2<f32>(f32(pos.x) / f32(dims.x), f32(pos.y) / f32(dims.y)), params.trace_center);
let trace_factor = smoothstep(params.trace_radius, 0.0, dist_to_trace) * params.trace_strength;
let effective_decay = mix(params.decay, min(params.decay * 1.03, 0.999), trace_factor);
lab.x *= effective_decay;
```

### Files
- Modify: `hapax-logos/crates/hapax-visual/src/shaders/feedback.wgsl`
- Modify: `hapax-logos/crates/hapax-visual/src/techniques/feedback.rs` — add trace uniforms
- Modify: `hapax-logos/crates/hapax-visual/src/content_layer.rs` — write trace on slot deactivation
- Modify: `hapax-logos/crates/hapax-visual/src/bridge.rs` — pass trace info

---

## Amendment 3: Material Quality on Fragments

**Bachelard**: The four elements (water, fire, earth, air) are "the hormones of imagination." Material imagination gives images weight, resistance, texture. Formal imagination is cheap; material imagination sustains reverie.

**Current**: `ImaginationFragment` has 9 expressive dimensions but no material quality. All content interacts with the substrate identically.

**Change**: Add a `material` field to `ImaginationFragment` — one of `"water"`, `"fire"`, `"earth"`, `"air"`, `"void"`. The content layer shader varies how content interacts with the substrate:

| Material | Interaction |
|----------|------------|
| **water** | Dissolves at edges, flows downward, reflects/doubles. Soft, pooling. |
| **fire** | Burns outward from center, consumes adjacent texture, vertical. Rapid. |
| **earth** | Dense, persistent, resistant to dissolution. Hard edges. Slow appear/fade. |
| **air** | Translucent, drifts upward, disperses quickly. High diffusion. |
| **void** | Darkens substrate rather than brightening. Inverse blend. |

### Implementation

Add `material: str = "water"` to `ImaginationFragment`.

Add `material: u32` to `ContentUniforms` (0=water, 1=fire, 2=earth, 3=air, 4=void).

In `content_layer.wgsl`, branch on material for UV modulation, opacity curves, and blend behavior.

Add `material` to the LLM system prompt so imagination chooses elemental quality.

### Files
- Modify: `agents/imagination.py` — add `material` field
- Modify: `hapax-logos/crates/hapax-visual/src/content_layer.rs` — material uniform
- Modify: `hapax-logos/crates/hapax-visual/src/shaders/content_layer.wgsl` — material-specific rendering
- Modify: `hapax-logos/crates/hapax-visual/src/visual/state.rs` — read material
- Modify: `tests/test_imagination.py` — serialization test

---

## Amendment 4: Reverberation in the Feedback Loop

**Bachelard**: Resonance is recognition. Reverberation is transformation — the image changes the receiver. Without reverberation, imagination converges and repeats. With it, the system surprises itself.

**Current**: DMN evaluative tick assesses trajectory (improving/degrading/stable). No mechanism to detect that rendered output is surprising relative to what was generated.

**Change**: The imagination loop compares its most recent fragment's predicted character (narrative, dimensions) against the DMN's perceived visual description. When difference is high (reverberation), salience is boosted and cadence accelerates — the system is "onto something" it didn't predict.

### Implementation

Add `reverberation_check(perceived_description: str) -> float` to `ImaginationLoop`. Simple word-overlap similarity inverted: high reverberation = low similarity between narrative and perception.

DMN evaluative tick writes visual observation to `/dev/shm/hapax-dmn/visual-observation.txt`. Imagination loop reads it on next tick.

When reverberation > 0.5: boost context with "the visual output surprised you", accelerate cadence.

### Files
- Modify: `agents/imagination.py` — `reverberation_check()`, read visual observation
- Modify: `agents/dmn/__main__.py` — write visual observation to shm
- Create: `tests/test_reverberation.py`

---

## Amendment 5: Immensity Through Depth

**Bachelard**: "Immensity is within ourselves." Produced by intensity, not scale. The surface should feel immense — content should suggest continuation beyond the viewport.

**Current**: Content renders entirely within [0,1] UV. No off-screen origin or departure. Background fills frame without spatial depth suggestion.

**Change**: Content fragments arrive from off-screen space, sliding in during materialization. The entry direction varies per slot. Parallax offset on the gradient layer creates subtle depth when operator head position shifts.

### Implementation

In `content_layer.wgsl`, modify `modulate_uv()`:

```wgsl
let entry_progress = smoothstep(0.0, 0.5, base_opacity);
let entry_offset = (1.0 - entry_progress) * 0.4;
let entry_direction = vec2<f32>(sin(slot_index * 2.1), cos(slot_index * 1.7));
muv += entry_direction * entry_offset;
```

In `gradient.wgsl`, add parallax if not already wired:

```wgsl
let parallax = vec2<f32>(u.parallax_x, u.parallax_y) * 0.02;
let flow_uv = (uv + parallax) * 3.0 + ...;
```

### Files
- Modify: `hapax-logos/crates/hapax-visual/src/shaders/content_layer.wgsl`
- Modify: `hapax-logos/crates/hapax-visual/src/shaders/gradient.wgsl` — parallax (if not wired)

---

## Amendment 6: Soft Escalation

**Bachelard**: Reverie's urgency is not binary. The transition from background to "I must speak" is gradual.

**Current**: Hard thresholds — 0.6 for cascade escalation, 0.8 for proactive utterance.

**Change**: Sigmoid-gated probabilistic escalation. Salience 0.5 → ~12% chance. Salience 0.6 → ~50%. Salience 0.8 → ~95%. Continuation boosts probability by ~30%.

### Implementation

```python
def maybe_escalate(fragment):
    probability = 1.0 / (1.0 + math.exp(-8.0 * (fragment.salience - 0.55)))
    if fragment.continuation:
        probability = min(1.0, probability * 1.3)
    if random.random() > probability:
        return None
    return Impingement(...)
```

Similarly soften `ProactiveGate.should_speak()` salience check with sigmoid around 0.75.

### Files
- Modify: `agents/imagination.py` — sigmoid `maybe_escalate()`
- Modify: `agents/proactive_gate.py` — sigmoid salience gate
- Modify: `tests/test_imagination.py` — probabilistic escalation tests
- Modify: `tests/test_proactive_gate.py` — probabilistic gate tests

---

## Implementation Order

Recommended by value and risk:

1. **Amendment 1** (Materialization) — shader-only, highest visual impact
2. **Amendment 3** (Material quality) — adds elemental vocabulary
3. **Amendment 5** (Immensity) — shader-only, spatial feel
4. **Amendment 6** (Soft escalation) — Python-only, behavioral realism
5. **Amendment 2** (Dwelling/trace) — shader + Rust, moderate complexity
6. **Amendment 4** (Reverberation) — Python, new feedback mechanism
