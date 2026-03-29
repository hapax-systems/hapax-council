# Dynamic Shader Pipeline — Effect Graph → WGPU

**Date:** 2026-03-29
**Status:** Design approved

## Overview

Replace the hardcoded 6-technique WGPU render pipeline with a dynamic shader graph executor. Python compiles effect graph presets to WGSL (via naga transpilation) and writes execution plans to `/dev/shm`. The Rust `hapax-imagination` binary hot-reloads shader graphs and executes them as ordered render/compute passes. All 54 existing GLSL nodes become available on the WGPU surface. The content layer becomes a composable graph node.

## Architecture

```
Python (authority)                    Rust (executor)

effect_graph/compiler.py              hapax-imagination binary
  ↓ compile preset                      ↓ file watcher
effect_graph/wgsl_transpiler.py       dynamic_pipeline.rs
  ↓ naga GLSL→WGSL                     ↓ create_shader_module()
/dev/shm/hapax-imagination/pipeline/  render passes (ordered)
  plan.json                             ↓ ping-pong textures
  *.wgsl                              uniform_buffer.rs
  uniforms.json                         ↓ per-frame upload
                                      window surface + shm JPEG
```

Python is the shader authority. Rust is a generic executor. The filesystem-as-bus pattern (`/dev/shm`) carries both the execution plan and per-frame uniform updates.

## Python Compilation Pipeline

### GLSL→WGSL Transpiler

New module `agents/effect_graph/wgsl_transpiler.py`. Uses `naga` CLI for transpilation:

```
naga input.frag output.wgsl
```

Each GLSL fragment shader is transpiled with a standard adapter preamble that maps GStreamer conventions to wgpu bind groups:

| GStreamer convention | wgpu equivalent |
|---------------------|-----------------|
| `uniform sampler2D tex` | `@group(0) @binding(0) var tex: texture_2d<f32>` |
| `uniform float time` | `uniforms.time` (struct member) |
| `gl_FragCoord` | `@builtin(position)` |
| `varying vec2 texCoord` | Vertex shader output (fullscreen quad) |

The transpiler pre-processes GLSL source to inject the adapter before calling naga. All 54 nodes are transpiled ahead of time and checked into the repo as `agents/shaders/nodes/*.wgsl` alongside the existing `.frag` files.

### Compiled Output

On preset activation, the compiler writes to `/dev/shm/hapax-imagination/pipeline/`:

- `plan.json` — execution plan: ordered list of passes

```json
{
  "version": 1,
  "passes": [
    {
      "node_id": "gradient_0",
      "shader": "gradient.wgsl",
      "type": "render",
      "inputs": [],
      "output": "layer_0",
      "uniforms": {"hue_base": 180.0, "hue_range": 60.0}
    },
    {
      "node_id": "reaction_diff_0",
      "shader": "reaction_diffusion.wgsl",
      "type": "compute",
      "steps_per_frame": 8,
      "inputs": ["layer_0"],
      "output": "layer_1",
      "uniforms": {"feed": 0.055, "kill": 0.062}
    },
    {
      "node_id": "content_layer_0",
      "shader": "content_layer.wgsl",
      "type": "render",
      "inputs": ["layer_1"],
      "output": "layer_2",
      "uniforms": {}
    },
    {
      "node_id": "postprocess_0",
      "shader": "postprocess.wgsl",
      "type": "render",
      "inputs": ["layer_2"],
      "output": "final",
      "uniforms": {"vignette_strength": 0.3}
    }
  ]
}
```

- `<node_id>.wgsl` — transpiled shader source per node (copied from repo cache, not re-transpiled at runtime)
- `uniforms.json` — current uniform values, updated by the modulator on each perception tick (~2.5s)

### Content Layer Node

The content layer becomes a graph node type `content_layer`. Its shader handles texture slot sampling (4 slots) + 9-dimension modulation + screen-blend with previous pass output. Presets that want imagination content wire this node into their graph. Presets without it simply omit the node.

## Rust Dynamic Shader Engine

### DynamicPipeline

New module `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`. Replaces the fixed technique list, compositor, content layer, and postprocess with a single generic pipeline executor.

**Pipeline hot-reload:** A file watcher (notify crate) monitors `/dev/shm/hapax-imagination/pipeline/plan.json`. On change:

1. Read `plan.json`
2. For each pass, read the `.wgsl` file from the same directory
3. Call `device.create_shader_module()` for each shader
4. Create render/compute pipelines with bind group layouts matching the standard uniform struct
5. Swap the active pipeline atomically (behind a RwLock)

**Pass execution per frame:**

1. Read `uniforms.json`, upload to GPU uniform buffer
2. Poll stimmung + imagination state (StateReader), merge into uniform buffer
3. Execute passes in plan order:
   - Render passes: fullscreen quad with input textures + uniform buffer → output texture
   - Compute passes: dispatch with `steps_per_frame` iterations
4. Final pass output → window surface (present) + shm JPEG output

**Texture pool:** Ping-pong textures at render resolution. Passes declare inputs/outputs by name (`layer_0`, `layer_1`, `final`). The engine resolves names to texture views. Content layer slots (4 textures) are managed as named textures in the same pool.

### UniformBuffer

New module `hapax-logos/crates/hapax-visual/src/uniform_buffer.rs`. Single shared GPU buffer updated per frame.

Standard struct (accessible to every shader):

```rust
struct Uniforms {
    time: f32,
    dt: f32,
    resolution: [f32; 2],
    // Stimmung
    stance: u32,  // 0=nominal, 1=cautious, 2=degraded, 3=critical
    color_warmth: f32,
    speed: f32,
    turbulence: f32,
    brightness: f32,
    // 9 expressive dimensions
    intensity: f32,
    tension: f32,
    depth: f32,
    coherence: f32,
    spectral_color: f32,
    temporal_distortion: f32,
    degradation: f32,
    pitch_displacement: f32,
    formant_character: f32,
    // Content layer
    slot_opacities: [f32; 4],
    // Per-node custom (from plan.json uniforms field)
    custom: [f32; 32],
}
```

Matching WGSL struct included by every transpiled shader via a shared `uniforms.wgsl` import.

## Node Adaptation

### Current 6 techniques → graph nodes

| Technique | Node ID | Type | Notes |
|-----------|---------|------|-------|
| gradient | `gradient` | render | oklch palette, warmth-driven hue |
| reaction_diff | `reaction_diffusion` | compute | Gray-Scott, `steps_per_frame: 8` |
| voronoi | `voronoi` | compute | One-shot (first frame only flag) |
| wave | `wave` | compute | Ripple propagation |
| physarum | `physarum` | compute | Particle sim + trail decay |
| feedback | `feedback` | render | Frame-to-frame feedback loop |

Each gets a GLSL `.frag` source + JSON manifest in `agents/shaders/nodes/`, plus a transpiled `.wgsl`. The existing WGSL shaders in `crates/hapax-visual/src/shaders/` are deleted — the transpiled versions replace them.

### All 54 nodes

Every existing GLSL shader in `agents/shaders/nodes/*.frag` gets transpiled to WGSL. The adapter preamble handles uniform convention mapping. Shaders that use GLSL features unsupported by naga are hand-ported.

### Content layer

The existing `content_layer.wgsl` shader is adapted to the graph node interface: standard uniform buffer + input texture binding. The 4 texture slots are bound as `@group(1) @binding(0..3)`. The content upload logic moves to the engine's texture pool — when imagination state changes, the engine decodes JPEG files and uploads to the slot textures (same logic as current `ContentLayer::upload_to_slot`).

## Stimmung + Modulation Flow

**StateReader** (unchanged): polls `/dev/shm/hapax-stimmung/` and `/dev/shm/hapax-imagination/`. Smoothed values feed into the uniform buffer.

**Python modulator** (`agents/effect_graph/modulator.py`): already maps stimmung → uniform overrides. Now writes `uniforms.json` to `/dev/shm/hapax-imagination/pipeline/` on each tick (~2.5s). The Rust engine reads this every frame and merges with StateReader values before GPU upload.

**9 expressive dimensions**: flow from imagination state → uniform buffer → every shader. Shaders access `uniforms.intensity`, `uniforms.tension`, etc.

## File Map

### New files

| File | Purpose |
|------|---------|
| `agents/effect_graph/wgsl_transpiler.py` | GLSL→WGSL via naga CLI |
| `agents/effect_graph/wgsl_compiler.py` | Compile graph → plan.json + WGSL files |
| `agents/shaders/nodes/*.wgsl` | Transpiled WGSL for all 54 nodes |
| `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` | Pipeline hot-reload + pass execution |
| `hapax-logos/crates/hapax-visual/src/uniform_buffer.rs` | Shared uniform struct + per-frame upload |
| `hapax-logos/crates/hapax-visual/src/shaders/uniforms.wgsl` | Shared WGSL uniform struct |
| `hapax-logos/crates/hapax-visual/src/shaders/fullscreen_quad.wgsl` | Shared vertex shader |
| `tests/effect_graph/test_wgsl_transpiler.py` | Transpilation round-trip tests |
| `tests/effect_graph/test_wgsl_compiler.py` | Plan generation tests |

### Deleted files

| File | Reason |
|------|--------|
| `crates/hapax-visual/src/techniques/*.rs` | Replaced by dynamic graph nodes |
| `crates/hapax-visual/src/techniques/mod.rs` | Empty |
| `crates/hapax-visual/src/compositor.rs` | Replaced by dynamic pipeline |
| `crates/hapax-visual/src/content_layer.rs` | Replaced by content_layer graph node |
| `crates/hapax-visual/src/postprocess.rs` | Becomes postprocess graph node |
| `crates/hapax-visual/src/shaders/*.wgsl` (except new shared ones) | Replaced by transpiled versions |

### Modified files

| File | Change |
|------|--------|
| `crates/hapax-visual/src/lib.rs` | Replace modules with dynamic_pipeline, uniform_buffer |
| `src-imagination/src/main.rs` | Replace hardcoded render loop with DynamicPipeline |
| `agents/effect_graph/compiler.py` | Add WGSL compilation stage |
| `agents/effect_graph/runtime.py` | Write plan.json + WGSL to /dev/shm |
| `agents/effect_graph/modulator.py` | Write uniforms.json to /dev/shm |
| `logos/api/routes/studio.py` | Trigger WGSL compilation on preset select |
| `presets/*.json` | Update node references, add content_layer node |

## Acceptance Criteria

1. `hapax-imagination` renders visual surface using presets loaded dynamically from `/dev/shm`
2. All 54 GLSL nodes transpile to WGSL (tested)
3. All 29 presets render correctly (visual verification)
4. Content layer works as a graph node (imagination fragments visible)
5. Preset switching hot-reloads the pipeline within 1 frame
6. Stimmung modulation flows through uniform buffer to all nodes
7. No hardcoded techniques remain in the Rust crate
8. 9 expressive dimensions accessible to every shader

## Constraints

- **naga GLSL frontend limitations** — some GLSL extensions may not parse. Hand-port any failures.
- **GPU budget** — RTX 3090 shared with Ollama, voice. Dynamic compilation adds brief stalls on preset switch (~50-100ms for shader compilation). Acceptable for non-realtime switches.
- **Frame budget** — 30fps target. Complex presets with many compute passes may drop frames. The plan.json can include a `target_fps` hint for the engine to skip frames.
- **Filesystem latency** — `/dev/shm` reads are sub-millisecond. `uniforms.json` read per frame is ~0.1ms.
