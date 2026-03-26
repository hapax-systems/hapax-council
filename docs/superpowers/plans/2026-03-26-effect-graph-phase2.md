# Effect Node Graph Phase 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the graph system actually control the GStreamer pipeline — bypass-based shader chain, smooth layer, crossfade transitions, full modulator wiring.

**Architecture:** Pre-instantiate all 51 shader nodes as `glshader` elements with `u_bypass` uniforms. Graph topology mutations toggle bypass flags. Crossfade via snapshot FBO. Smooth layer via GL texture ring buffer in a Rust GstGLFilter plugin.

**Tech Stack:** Python 3.12, GStreamer (glshader, GstGLFilter), Rust (smooth-delay + crossfade plugins), GLSL ES 1.0, FastAPI

**Spec:** `docs/superpowers/specs/2026-03-26-effect-graph-phase2-design.md`

---

## Task 1: Slot-based pipeline builder

**Files:**
- Create: `agents/effect_graph/pipeline.py`
- Modify: `agents/studio_compositor.py`
- Create: `tests/effect_graph/test_pipeline.py`

The pipeline builder creates 8 numbered `glshader` slots. On graph load, the compiler assigns nodes to slots in topological order and hot-swaps each slot's fragment shader source.

- [ ] **Step 1: Create pipeline builder**

`agents/effect_graph/pipeline.py`:
- `SlotPipeline.__init__(registry, Gst, num_slots=8)` — creates 8 glshader elements with passthrough shader
- `activate_plan(plan: ExecutionPlan)` — for each step in plan, assign to next slot (set `fragment` property to GLSL source + set uniforms). Clear remaining slots to passthrough.
- `set_slot_uniforms(slot_idx, params)` — builds GstStructure from params dict
- `PASSTHROUGH_SHADER` constant — minimal passthrough GLSL

- [ ] **Step 2: Replace `_add_effects_branch` in compositor**

Replace the hardcoded 10-element chain with SlotPipeline. Wire `_on_plan_changed` to `slot_pipeline.activate_plan()`.

- [ ] **Step 3: Write tests (mock GStreamer)**

Test slot assignment, passthrough clearing, uniform building. Use mock Gst elements.

- [ ] **Step 4: Commit**

---

## Task 3: Crossfade Rust plugin

**Files:**
- Create: `plugins/gst-crossfade/Cargo.toml`
- Create: `plugins/gst-crossfade/src/lib.rs`
- Create: `plugins/gst-crossfade/src/crossfade.rs`

- [ ] **Step 1: Scaffold Rust plugin**

Based on `plugins/gst-temporalfx/` structure. GstGLFilter subclass with:
- `snapshot_tex: Option<GLuint>` — captured frame
- `crossfade_alpha: f32` — ramps 1.0→0.0
- `transition_ms: u32` property (default 500)
- `trigger_snapshot()` method — captures current input into snapshot_tex, sets alpha=1.0

- [ ] **Step 2: Implement filter_texture**

```rust
fn filter_texture(&self, input: &GLMemory, output: &GLMemory) -> Result<(), Error> {
    if self.crossfade_alpha > 0.0 && self.snapshot_tex.is_some() {
        // Blend: mix(input, snapshot, alpha)
        self.render_blend(input, self.snapshot_tex, self.crossfade_alpha, output);
        self.crossfade_alpha -= frame_decrement;
        if self.crossfade_alpha <= 0.0 {
            self.release_snapshot();
        }
    } else {
        // Passthrough
        self.render_passthrough(input, output);
    }
}
```

- [ ] **Step 3: Build, install, test with compositor**
- [ ] **Step 4: Wire into compositor after effects chain**
- [ ] **Step 5: Commit**

---

## Task 4: Smooth delay Rust plugin

**Files:**
- Create: `plugins/gst-smooth-delay/Cargo.toml`
- Create: `plugins/gst-smooth-delay/src/lib.rs`
- Create: `plugins/gst-smooth-delay/src/delay.rs`

- [ ] **Step 1: Scaffold Rust plugin**

GstGLFilter subclass with:
- `ring: Vec<GLuint>` — GL texture ring buffer
- `write_head: usize`
- `capacity: usize` (delay_seconds × fps)
- `delay_seconds: f32` property (default 5.0)

- [ ] **Step 2: Implement filter_texture**

Each frame: copy input to `ring[write_head % capacity]`, output `ring[(write_head - capacity + 1) % capacity]` (oldest frame). Increment write_head.

- [ ] **Step 3: Build, install, wire into compositor as @smooth source**
- [ ] **Step 4: Commit**

---

## Task 5: Modulator signal wiring + layer palettes

**Files:**
- Modify: `agents/studio_compositor.py`

- [ ] **Step 1: Extend _fx_tick_callback signal dict**

Add all perceptual signals:
```python
signals = {
    "audio_rms": energy,
    "audio_beat": beat_smooth,
    "stimmung_valence": data.emotion_valence,
    "stimmung_arousal": data.emotion_arousal,
    "flow_score": data.flow_score,
    "time_of_day": time.localtime().tm_hour / 24.0,
    "time": t,
}
```

- [ ] **Step 2: Apply modulator updates via pipeline builder**

Route `modulator.tick(signals)` results through `pipeline.set_uniforms()`.

- [ ] **Step 3: Wire layer palette changes to palette shader elements**

When `set_layer_palette()` is called, update the corresponding `palette_live` or `palette_smooth` element's uniforms.

- [ ] **Step 4: Commit**

---

## Task 6: Missing API routes

**Files:**
- Modify: `logos/api/routes/studio.py`

- [ ] **Step 1: Add endpoints**

```python
PATCH  /studio/layer/{layer}/enabled       — enable/disable layer
PATCH  /studio/layer/smooth/delay          — set temporal offset
PUT    /studio/presets/{name}              — save graph as preset
DELETE /studio/presets/{name}              — delete user preset
GET    /studio/cameras                     — list cameras from compositor status
POST   /studio/camera/select              — set hero camera
```

- [ ] **Step 2: Commit**

---

## Task 7: Fragment shader compute approximations

**Files:**
- Create: `agents/shaders/nodes/fluid_sim.frag` + `.json`
- Create: `agents/shaders/nodes/reaction_diffusion.frag` + `.json`
- Create: `agents/shaders/nodes/particle_system.frag` + `.json`

- [ ] **Step 1: Stable Fluids fragment shader**

Iterative advection + diffusion via texture ping-pong. temporal=true, temporal_buffers=1. Params: viscosity, vorticity, dissipation, inject_source. Reads tex (velocity/density field from previous frame via tex_accum), writes updated field.

- [ ] **Step 2: Gray-Scott reaction diffusion fragment shader**

Two-chemical system with feed/kill rates. temporal=true, temporal_buffers=1. Reads tex_accum (previous state), writes next state. Can seed from camera luminance.

- [ ] **Step 3: Noise-based particle renderer**

Deterministic particles from hash(time, particle_id). Not true compute — positions recalculated each frame. Params: emit_rate, lifetime, size, color. Renders additive points.

- [ ] **Step 4: Update smoke test expectations to 54 node types**
- [ ] **Step 5: Commit**

---

## Task 8: Integration smoke tests

- [ ] **Step 1: Extend test_smoke.py**

Add tests for bypass injection, pipeline builder (with mocks), new API routes, compute approximation nodes loading.

- [ ] **Step 2: Full test suite run**
- [ ] **Step 3: Commit**

---

## Execution Order

```
Task 1 (bypass) ──→ Task 2 (pipeline builder) ──→ Tasks 3-6 (parallel)
                                                 ├─ Task 3 (crossfade plugin)
                                                 ├─ Task 4 (smooth delay plugin)
                                                 ├─ Task 5 (modulator + palettes)
                                                 └─ Task 6 (API routes)
Task 7 (compute shaders) ── independent
Task 8 (smoke tests) ── after all above
```
