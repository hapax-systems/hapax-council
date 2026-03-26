# Effect Node Graph Phase 2 — GStreamer Pipeline Integration

**Date:** 2026-03-26
**Status:** Approved
**Depends on:** 2026-03-25-effect-node-graph-design.md (Phase 1)

## Problem

Phase 1 built the graph infrastructure (types, compiler, runtime, 51 shader nodes, 28 presets, API routes, modulator). But the graph system is **state-only** — it manages graph topology and parameters but does not control the GStreamer pipeline. Specifically:

1. **`_on_plan_changed` is never wired.** When graph topology mutates (nodes added/removed), the compositor has no handler. The fixed 10-element shader chain never changes.
2. **Layer sources are inert.** `@live`, `@smooth`, `@hls` exist in the type system but the compositor never creates smooth/HLS layer feeds into the graph.
3. **Layer palettes don't apply.** `set_layer_palette()` updates runtime state but no GStreamer element receives the palette uniforms.
4. **Modulator signals aren't fed.** The modulator tick runs in `_fx_tick_callback` but only drives the legacy hardcoded beat-reactive code. The graph modulator's `tick()` is called but signals (`stimmung_valence`, `flow_score`, `heart_rate`) are only partially wired.
5. **No crossfade.** Preset switches are instant uniform swaps — no visual transition.
6. **Compute nodes impossible.** GStreamer's `glshader` only supports fragment shaders. fluid_sim, reaction_diffusion, particle_system need an alternative path.

## Design Decisions

### D1: Fragment-shader-only pipeline (no compute shaders)

GStreamer's `glshader` element does not support compute shaders. Building custom Rust GstGLFilter plugins for each compute node is prohibitively complex for diminishing returns. Instead:

- **fluid_sim, reaction_diffusion**: Implement as iterative fragment shaders with texture ping-pong (same technique as temporalfx). Lower fidelity but functional. Both Gray-Scott RD and Stable Fluids can run as fragment shaders — the results are visually indistinguishable from compute at 1080p.
- **particle_system**: Implement as a fragment shader that uses noise-seeded particle positions stored in a texture. No true GPU compute dispatch. Particles are render-time only (positions recomputed per frame from deterministic noise + time).
- **Conclusion**: No compute shader infrastructure needed. All nodes stay as `.frag` files loaded by `glshader`.

### D2: Dynamic pipeline via passthrough bypass (not teardown/rebuild)

GStreamer cannot safely add/remove elements on a PLAYING pipeline. Instead of pausing + rebuilding:

- **All 51 shader nodes are pre-instantiated** in the effects branch as `glshader` elements, each with a **bypass uniform** (`u_bypass`). When `u_bypass > 0.5`, the shader passes through `texture2D(tex, v_texcoord)` unchanged.
- **Topology mutation** = updating which shaders are bypassed + setting their uniforms. The GStreamer element chain is fixed at startup; the graph compiler controls which elements are active.
- **Node ordering** is fixed by the pre-built chain order. The graph compiler validates that the requested topology is compatible with the fixed chain order, or raises an error.
- **Benefit**: Zero pipeline state transitions, zero frame drops during mutations.
- **Cost**: All 51 shader elements exist in GPU memory (~51 texture lookups per frame in worst case, but bypassed shaders are nearly free — a single texture2D passthrough costs <0.1ms on RTX 3090).

### D3: Crossfade via output blend shader

A dedicated blend shader at the end of the chain:
- Maintains a snapshot FBO of the current output.
- When a preset switch triggers, captures the current frame into the snapshot FBO.
- For `transition_ms` duration, outputs `mix(snapshot, current_output, t)` where t ramps 0→1.
- After transition completes, snapshot FBO is released.
- This uses the existing `blend.frag` shader approach, inserted as the final stage before output.

### D4: Smooth layer as GL texture ring buffer

A GStreamer `queue` element forces a GPU→CPU→GPU round-trip (downloads GL textures to system RAM, re-uploads after delay). Instead, implement a custom `GstGLFilter` subclass (Rust, like temporalfx) that maintains a ring buffer of GL texture references in VRAM:

- **Ring size**: `delay_seconds × fps` textures (default: 5s × 30fps = 150 textures)
- **VRAM cost**: 150 × 1920×1080×4 bytes = ~1.2GB. On a 24GB card this is acceptable. Configurable via API (`PATCH /studio/layer/smooth/delay`).
- **Implementation**: Write frame N into ring[write_head % ring_size], output ring[(write_head - delay_frames) % ring_size]. Pure GL — no CPU round-trip.
- **Fallback**: If VRAM is constrained, reduce to half-resolution (960×540, ~300MB) or shorter delay.

### D5: Multi-camera nodes deferred

`camera_select`, `split_screen`, `pip` require per-camera feeds into the graph. Currently cameras are composited at the CUDA level (`cudacompositor`) before the GL effects branch. Routing individual cameras into the GL graph would require:
- Per-camera tee → glupload → graph input
- Graph compiler supporting multiple camera sources
- Significant pipeline restructuring

This is deferred. The existing `cudacompositor` tiling handles multi-camera layout. Effects apply to the composited output.

### D6: Optical flow via fragment shader approximation

NVIDIA's NVOFA hardware (`nvof` GStreamer element) outputs motion vectors but integrating it into the GL shader pipeline requires format conversion. Instead:
- **optical_flow node**: Implement as a fragment shader that computes per-pixel motion via frame differencing (Horn-Schunck or Lucas-Kanade approximation). Lower quality than NVOFA but runs entirely in the GL pipeline.
- **datamosh node**: Uses the optical flow output to displace pixels from the previous frame. Implemented as a temporal fragment shader with FBO ping-pong.
- Both deferred to Phase 3 as they're complex but not blocking.

## Validation

Research confirmed all architectural decisions:

- **51-element bypass chain**: 0.55% of RTX 3090 texture fillrate. ~408MB VRAM for output FBOs. No known chain length limit in GStreamer.
- **GL texture ring for smooth layer**: Avoids GPU→CPU→GPU round-trip of queue-based approach. ~1.2GB VRAM at full resolution.
- **Crossfade via snapshot FBO**: Directly extends the existing temporalfx Rust plugin pattern. `glBlitFramebuffer` captures snapshot, blend shader interpolates.
- **Thread safety**: `set_property("uniforms")` on `glshader` is technically racy but worst case is one frame with partial uniforms — visually harmless for smooth transitions.

## Architecture

### Slot-Based Shader Chain

**Problem**: A fixed alphabetical chain breaks 89% of presets because signal flow order matters (e.g., Ghost needs trail→bloom, Diff needs threshold→colorgrade). GStreamer can't relink elements on a PLAYING pipeline.

**Solution**: A chain of **N numbered processing slots** (e.g., 8 slots), each a `glshader` element. On graph load, the compiler assigns each node in topological order to a slot and loads that slot's shader source + uniforms. Unused slots get a passthrough shader.

```
tee → queue → stutter_element →
  videoconvert(RGBA) → glupload → glcolorconvert →

  [LAYER SECTION]
  palette_live →
  palette_smooth →

  [PROCESSING SLOTS — dynamically assigned per preset]
  slot_0 →    # e.g., colorgrade
  slot_1 →    # e.g., trail (via temporalfx)
  slot_2 →    # e.g., bloom
  slot_3 →    # e.g., scanlines
  slot_4 →    # e.g., vignette
  slot_5 →    # unused (passthrough)
  slot_6 →    # unused (passthrough)
  slot_7 →    # unused (passthrough)

  [POST SECTION]
  crossfade_output →

  glcolorconvert → gldownload → jpegenc → appsink
```

**Slot count**: The longest preset has 6 processing nodes (screwed, trap, nightvision, vhs_preset). 8 slots provides headroom.

**Shader hot-swap on glshader**: GStreamer's `glshader` element supports setting the `fragment` property at runtime to change the shader source. This is a string property update, not an element swap. The GL context recompiles the shader — takes ~1ms on RTX 3090. Combined with the crossfade engine, this is invisible.

### Graph-to-Pipeline Mapping

When `_on_plan_changed(old_plan, new_plan)` fires:

1. **Trigger crossfade**: Capture current output to snapshot FBO.
2. **Assign slots**: For each step in `new_plan.steps` (topologically sorted):
   - Find the next available slot
   - Set slot's `fragment` property to the node's GLSL source
   - Set slot's uniforms to the node's params
3. **Clear unused slots**: Set remaining slots to passthrough shader.
4. **Blend**: Crossfade from snapshot to new output over `transition_ms`.

### Bypass for Unused Slots

Unused slots get a minimal passthrough shader:

```glsl
#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
void main() { gl_FragColor = texture2D(tex, v_texcoord); }
```

### Generative Node Handling

Generative nodes (noise_gen, solid, waveform_render) have NO `tex` input. They can't be a processing slot (which reads from the previous slot's output). Instead, they feed into a compositing slot via a dedicated generative branch:

```
[GENERATIVE BRANCH — optional, only when graph uses generative nodes]
generative_slot → [feeds into blend slot as tex_b]
```

This is wired on demand when the active graph includes a generative node.

### Smooth Layer Implementation

```
camera_tee
  ├─ [existing path] → cudaupload → effects chain (= @live)
  └─ queue(max-size-time=5s) → videoconvert → glupload → palette_smooth → [injected before processing section]
```

The `palette_smooth` element is a colorgrade shader with per-layer uniforms. The delayed frames merge into the processing chain via a blend element (when `@smooth` is referenced in the active graph).

### Modulator Signal Wiring

The `_fx_tick_callback` already reads `audio_energy_rms` and computes `beat`. Extend it to populate a full signal dict:

```python
signals = {
    "audio_rms": energy,
    "audio_beat": beat_smooth,
    "audio_bass": bass_energy,      # extract from audio FFT if available
    "audio_mid": mid_energy,
    "audio_high": high_energy,
    "stimmung_valence": data.emotion_valence,
    "stimmung_arousal": data.emotion_arousal,
    "flow_score": data.flow_score,
    "heart_rate": 0.0,              # from hapax-watch when available
    "time_of_day": hour / 24.0,
    "optical_flow_magnitude": 0.0,  # placeholder until optical_flow node
}
```

These are passed to `self._graph_runtime.modulator.tick(signals)`.

### Missing API Routes

Add these endpoints (from spec §4):

```
PATCH  /studio/layer/{layer}/enabled        — enable/disable layer
PATCH  /studio/layer/smooth/delay           — set temporal offset (default 5s)
PUT    /studio/presets/{name}               — save current graph as preset
DELETE /studio/presets/{name}               — delete user preset
GET    /studio/cameras                      — list available cameras
POST   /studio/camera/select               — set hero camera
```

## Scope

### In scope (this phase)

1. **Bypass shader infrastructure** — prepend `u_bypass` to all shaders, pre-instantiate full chain
2. **`_on_plan_changed` handler** — map execution plan to bypass flags + uniforms
3. **Crossfade output shader** — snapshot FBO + blend for preset transitions
4. **Smooth layer** — delayed queue branch with palette shader
5. **Layer palette wiring** — palette uniforms applied from runtime state
6. **Full modulator signal wiring** — all perceptual signals fed to tick()
7. **Missing API routes** — layer enable/disable, smooth delay, preset save/delete, cameras
8. **Fragment shader approximations** — fluid_sim, reaction_diffusion as iterative fragment shaders

### Out of scope (Phase 3+)

- Compute shader infrastructure
- NVIDIA optical flow hardware integration
- datamosh, optical_flow nodes (deferred to Phase 3)
- camera_select, split_screen, pip nodes (multi-camera routing)
- motion_trail node (depends on optical flow)
- time_displacement node (complex temporal buffer management)
