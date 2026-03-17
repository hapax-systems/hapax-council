# Multi-Technique Rendering Architecture Research

Research into the technical substrate for compositing multiple simultaneous generative visual techniques (reaction-diffusion, particle flow, Voronoi tessellation, framebuffer feedback, gradient fields) into a single ambient display at 60fps on an RTX 3090.

## Current System Baseline

The existing studio compositor uses GStreamer with CUDA compositing (`cudacompositor`), NVENC hardware encoding, and a chain of GL filter elements:

- **Custom Rust GstGLFilter plugin** (`temporalfx`) — FBO ping-pong for temporal feedback with decay, hue shift, and blend modes (Add/Multiply/Difference/SourceOver). Already does the exact pattern needed: accumulation texture, per-frame shader, CopyTexSubImage2D feedback loop.
- **glshader elements** — Custom GLSL fragment shaders for color grading, VHS simulation, FBM ambient noise, slice warp, post-processing (vignette, scanlines, band displacement, syrup gradient).
- **Multiple effect presets** — 10 presets (ghost, trails, screwed, datamosh, vhs, neon, trap, diff, clean, ambient) composed from configurable shader chains.
- **Dual output** — v4l2sink to loopback device + HLS via hlssink2 for browser preview + JPEG snapshots to /dev/shm.

The system already does multi-pass GL composition through GStreamer's pipeline. The question is whether this architecture scales to 5+ simultaneous generative techniques with compute-shader-class simulation.

---

## 1. WebGPU Compute Shaders (wgpu / wgpu-native)

### What It Is

WebGPU is the successor to WebGL, designed around modern GPU APIs (Vulkan, Metal, DX12). **wgpu** is the Rust implementation; **wgpu-native** provides a C API with bindings for Python (wgpu-py), Go, Zig, and 10+ other languages.

### Architecture for Multi-Technique Composition

WebGPU's command encoder model is purpose-built for this workload:

```
CommandEncoder {
    // Simulation phase — all run as compute dispatches
    ComputePass {
        dispatch reaction_diffusion_step (ping-pong textures A↔B)
        dispatch particle_position_update (storage buffer, millions of agents)
        dispatch voronoi_jfa_pass (log2(N) dispatches, storage texture)
        dispatch gradient_field_update (storage buffer → texture)
    }

    // Render phase — read simulation outputs as textures
    RenderPass {
        draw fullscreen_quad with reaction_diffusion_texture (layer 0)
        draw particle_instances from storage buffer (layer 1)
        draw fullscreen_quad with voronoi_texture (layer 2)
        draw fullscreen_quad with gradient_field_texture (layer 3)
        draw fullscreen_quad with feedback_texture (layer 4)
        // Each draw uses blend state for composition
    }

    // Feedback — copy render output to feedback input
    copyTextureToTexture(output → feedback_input)
}
```

All within a single command buffer submission per frame. No CPU round-trips between passes.

### Key Technical Details

- **Compute shaders**: First-class. `@compute @workgroup_size(64)` with storage buffers and storage textures. Workgroup size product limited to 256 threads.
- **Storage textures**: Compute shaders can write to textures via `textureStore()`. Formats: rgba8unorm, rgba16float, rgba32float, etc. Read-write access limited to r32float/r32sint/r32uint; others require separate read/write textures (ping-pong).
- **Ping-pong**: Natural pattern. Two textures, two bind groups, swap each frame. The Google WebGPU Game of Life tutorial demonstrates exactly this for cellular automata.
- **Blend states**: Per-render-target blend configuration (source/dest factors, blend ops). Covers all Porter-Duff operators and additive/subtractive blending.
- **Multiple render targets**: Supported. Each attachment gets independent blend state.
- **Browser support**: Chrome 113+ (2023), Edge 113+, Firefox behind flag (Nightly), Safari 18+ (preview). Not yet Baseline.

### For This Project: wgpu (Rust, standalone)

- **wgpu** runs natively on Linux via Vulkan backend. No browser needed for dedicated display.
- Same codebase can compile to WASM + WebGPU for browser embedding.
- **wgpu-py** (Python bindings via wgpu-native) enables prototyping and integration with the existing Python agent system.
- Active project: 816 commits, v27.0.4.0 (Dec 2025), 100% test coverage.

### Performance Assessment (RTX 3090)

An RTX 3090 has 10,496 CUDA cores and 82 SMs. At 1080p:
- Reaction-diffusion: 1920x1080 ping-pong compute at 60fps is trivial (2M texels, ~32K workgroups of 64).
- Particle flow: 10M particles in a storage buffer, each agent reads trail map and writes position — well within compute budget.
- Voronoi JFA: log2(1920) ≈ 11 passes, each a full-screen compute dispatch. ~22M texel writes total per frame. Trivial.
- 5-layer composition: 5 fullscreen quads with alpha blend. Negligible.
- **Total GPU utilization at 1080p60**: estimated <5% of RTX 3090 capacity.

### Dual Output

- **Dedicated display**: wgpu presents to a native window (winit on Linux/Wayland).
- **Web view**: Two options:
  1. Compile to WASM+WebGPU, run in browser directly (same shaders, same code).
  2. Readback framebuffer to CPU, encode to JPEG/H264, stream via WebSocket/HLS (like current system).
  3. GStreamer integration: render offscreen, inject frames into GStreamer pipeline via appsrc.

### Composability

Techniques are compute dispatches and render draws. Adding/removing a technique = adding/removing a dispatch and a draw call. Intensity = uniform value (opacity, blend factor). Fully dynamic, zero pipeline rebuilds.

### Beauty Ceiling

WebGPU/wgpu is the substrate behind: Vello (GPU-accelerated 2D renderer, 177fps on complex scenes), numerous Shadertoy-class demonstrations, real-time VJ tools. The ceiling is the artist, not the technology. Compute shaders unlock algorithms (Physarum, Gray-Scott R-D, JFA Voronoi) that are impossible in fragment-only pipelines.

### Verdict: **PRIMARY RECOMMENDATION**

---

## 2. Multi-Pass WebGL2 Composition

### What It Is

The proven approach: multiple framebuffer objects (FBOs), each running a different technique as a fragment shader, composited in a final pass.

### Architecture

```
FBO_0: reaction_diffusion.frag (ping-pong with FBO_0b)
FBO_1: particle_trails.frag (read particle positions from texture, stamp sprites)
FBO_2: voronoi_jfa.frag (11 passes between FBO_2a/2b)
FBO_3: gradient_field.frag
FBO_4: feedback_accum.frag (reads previous composite)
Final: composite.frag — samples all FBOs with blend weights
```

### Limitations

- **No compute shaders**. Particle simulation must be faked as texture operations (position stored in RGBA texels, updated by fragment shader). Works but awkward for millions of particles — you need a texture large enough to hold all particle positions (e.g., 1024x1024 = 1M particles).
- **Max color attachments**: GL_MAX_COLOR_ATTACHMENTS is typically 8 on desktop (spec minimum 4 in WebGL2). Sufficient for 5 layers but limits future expansion.
- **Transform feedback**: WebGL2 has it, but it's clunky for particle update compared to compute.
- **Ping-pong JFA**: Works fine. 11 passes with two FBOs. Standard technique.
- **Browser support**: Universal. Every browser, every device.

### Performance Assessment (RTX 3090)

Reaction-diffusion ping-pong as fragment shader: fast, well-proven. Voronoi JFA: fast. Particle simulation as texture: viable for 1M particles, increasingly awkward beyond that. The fragment-shader-only constraint means some algorithms are clumsier but still fast enough.

### Dual Output

- Runs in browser natively (this IS the browser approach).
- Can run standalone via headless EGL + readback, but that's a worse version of using wgpu.

### Composability

Adding a technique = adding an FBO + a shader + a texture sampler in the composite pass. Straightforward but requires manual FBO management. No dynamic pipeline — you manage the render loop yourself.

### Beauty Ceiling

Shadertoy proves that extraordinary beauty is achievable with fragment shaders alone. Reaction-diffusion, Voronoi, noise fields — all well-documented in WebGL2. However, particle-heavy techniques (Physarum with millions of agents) are constrained.

### Verdict: **GOOD FALLBACK** for browser-only path. Not recommended as primary architecture because compute shaders unlock better algorithms.

---

## 3. Shadertoy / ISF / GLSL Fragment Shader Composition

### Shadertoy Model

Shadertoy uses multi-pass rendering with 4 buffer channels (Buffer A/B/C/D), each a persistent fullscreen render target. Buffers can read from each other (with one-frame delay to avoid cycles). This enables:
- Ping-pong simulation (Buffer A writes, reads from Buffer B, next frame swap)
- Accumulation/feedback (buffer reads from itself = previous frame)
- Multi-technique composition (each buffer = different technique, Image tab composites all)

This is exactly the architecture needed, but limited to 4 intermediate buffers and fragment shaders only.

### ISF (Interactive Shader Format)

ISF is a JSON+GLSL standard for composable shader modules. Key features:
- **PERSISTENT buffers**: Declared in JSON header, retain contents between frames. Enables feedback/accumulation without external ping-pong management.
- **PASSES array**: Multi-pass rendering declared in metadata. Each pass can target a named buffer.
- **Uniform declaration**: Inputs (float, color, image, audio) declared in JSON, auto-generating UI controls.
- **Portability**: Supported by VDMX, CoGe, MadMapper, Resolume (via conversion). WebGL player exists.

ISF is the most elegant format for individual shader effects but lacks a composition model — there's no ISF standard for "layer these 5 ISF shaders with these blend modes." The host application handles composition.

### Fragment-Only Feasibility

Can all required techniques be done in fragment shaders?
- **Reaction-diffusion**: Yes. Classic ping-pong. Well-proven in Shadertoy.
- **Particle flow (Physarum)**: Partially. Agent positions stored as texels, trail map as separate buffer. Limited to texture-resolution agent count (~1M at 1024x1024). Doable but constrained.
- **Voronoi JFA**: Yes. Multi-pass fragment shader, well-documented.
- **Framebuffer feedback**: Yes. Buffer reads its own previous frame.
- **Gradient fields**: Yes. Trivial fragment shader.

### Verdict: **VALUABLE for shader authoring and prototyping**, not for the final composition architecture. Write individual techniques as GLSL fragment shaders (or ISF modules), then host them in a compute-capable runtime. The shaders are portable — they work in WebGL2, WebGPU fragment stage, GStreamer glshader, or any GLSL host.

---

## 4. GStreamer GL Pipeline

### What It Is

The current system's native substrate. GStreamer provides:
- **glshader** — Takes arbitrary GLSL fragment shader + uniforms as GstStructure. Pipeline: `glupload ! glshader fragment="..." ! gldownload`.
- **GstGLFilter** (subclass) — The `temporalfx` Rust plugin already demonstrates this pattern: custom GL code with manual FBO management, texture ping-pong, uniform control. Full OpenGL access within the filter_texture callback.
- **glvideomixer** / **GstGLMixer** — VideoAggregator subclass for compositing GL textures. Multiple inputs with alpha, positioning.
- **GstGLOverlayCompositor** — Overlay composition.
- **gleffects** — Built-in effects (glow, blur, etc.).

### Architecture for Multi-Technique

Each technique becomes a custom GstGLFilter plugin (Rust or C):
```
videotestsrc ! glupload !
  reaction_diffusion_filter !
  voronoi_filter !
  particle_filter !
  gradient_filter !
  temporalfx !
  composite_filter !
  gldownload ! autovideosink
```

Or use glvideomixer to composite multiple parallel branches:
```
reaction_diffusion ! glvideomixer.sink_0
voronoi_source     ! glvideomixer.sink_1
particle_source    ! glvideomixer.sink_2
glvideomixer ! output
```

### Limitations

- **No compute shaders in GStreamer GL stack**. Fragment shaders only via glshader/GstGLFilter. The `temporalfx` plugin proves sophisticated effects are possible (FBO ping-pong, multi-texture, custom GL calls), but simulation-class compute (millions of particles) would need raw GL compute shader calls within a custom filter — possible but fighting the framework.
- **Serial pipeline model**: GStreamer processes frames linearly. Multi-branch composition via glvideomixer adds latency and complexity. Each branch is a separate pipeline path with its own buffering.
- **Uniform control**: glshader's `uniforms` property uses GstStructure, which is workable but not as fluid as direct uniform setting. Custom GstGLFilter plugins (like temporalfx) have proper GObject properties with real-time control.
- **GL context sharing**: All GL elements in a pipeline share a context. Cross-pipeline sharing requires explicit management.

### Performance Assessment

The overhead is in the pipeline infrastructure (queue elements, caps negotiation, buffer copying between elements). For a linear chain of 5 shader passes, this is negligible. For parallel branch composition via glvideomixer, each branch adds a queue + sync overhead. Still fast on an RTX 3090 but architecturally heavier than a direct wgpu render loop.

### Dual Output

This is where GStreamer excels. The existing system already does it:
- `tee ! v4l2sink` (dedicated display via loopback)
- `tee ! hlssink2` (browser via HLS)
- `tee ! appsink` (JPEG snapshots to /dev/shm)
- Recording via splitmuxsink

### Composability

Adding a technique = adding a GstGLFilter plugin to the pipeline. Dynamic pipeline modification (adding/removing elements while running) is possible but complex. GStreamer is designed for static-ish pipelines with property-driven parameter changes.

### Beauty Ceiling

Limited by fragment-shader-only constraint and the overhead of pipeline infrastructure. The `temporalfx` plugin shows what's possible — temporal feedback with blend modes and hue shifting — but compute-class algorithms like Physarum need GL compute calls smuggled into filter_texture callbacks.

### Verdict: **EXCELLENT for output routing**, but not the right layer for generative simulation. Best used as the delivery pipeline: render in wgpu, inject via appsrc, route through GStreamer to all outputs.

---

## 5. Vulkan Compute + Present

### What It Is

Direct GPU access. Maximum control over everything: memory allocation, command buffer recording, pipeline barriers, synchronization.

### Architecture

Identical to the wgpu architecture (wgpu IS a Vulkan abstraction) but without the safety guardrails. You manage:
- VkInstance, VkDevice, VkQueue
- VkCommandBuffer recording with vkCmdDispatch (compute) and vkCmdDraw (render)
- Pipeline barriers between compute write and fragment read
- Swapchain management for presentation
- Memory allocation (VMA or manual)

### When Is It Justified?

**Never for this project.** wgpu provides the same Vulkan backend with:
- Memory safety (Rust)
- Automatic synchronization barriers
- Cross-platform portability (Metal, DX12 fallback)
- WASM compilation for browser path
- No 2000-line boilerplate for "hello triangle"

Raw Vulkan is justified when you need:
- Async compute queues (multiple concurrent compute dispatches on separate queues)
- Fine-grained memory management (sparse binding, aliased memory)
- Vendor-specific extensions (RT cores, mesh shaders)

None of these apply to 1080p60 generative art on a single GPU.

### Verdict: **OVERKILL**. wgpu gives you Vulkan's compute pipeline without the ceremony.

---

## 6. Creative Coding Frameworks

### TouchDesigner

- **Architecture**: TOP (textures) / CHOP (channels) / SOP (surfaces) node graph. GLSL TOP runs custom fragment+compute shaders. Feedback TOP provides temporal persistence. Composite TOP layers with blend modes.
- **Multi-technique**: Purpose-built for this. Multiple GLSL TOPs, each running a different technique, composited via Composite TOP. Feedback TOP handles persistence. CHOP data (audio, sensors) exports to TOP uniforms.
- **Audio-reactive**: CHOP→TOP export is the standard pattern. Audio Spectrum CHOP → export → GLSL TOP uniform.
- **Compute shaders**: Yes, GLSL TOP supports compute mode (GLSL 4.30+).
- **Limitations**: Windows-only (no Linux). Proprietary, $2200 commercial license. Cannot compile to web. Black-box performance. Fundamentally a live-performance tool, not a programmable system.
- **Beauty ceiling**: Extremely high. TouchDesigner is used for world-class installations (teamLab, Refik Anadol scale).

### nannou (Rust)

- **Architecture**: Creative coding framework built on wgpu. Provides windowing, audio, event loop.
- **wgpu access**: Direct. You can create compute pipelines, render pipelines, manage textures.
- **Status**: 6.6k stars but "still early days." Last active development unclear. The framework adds convenience (windowing, audio capture) but you're writing wgpu code underneath.
- **Web output**: Not directly. Would need separate web compilation target.
- **Assessment**: Using nannou is essentially using wgpu with a convenience layer. If the convenience layer fits, great. If it constrains, you're fighting it. For this project, raw wgpu is likely better — the "convenience" needed is specific (GStreamer integration, audio data from existing agents, parameter control from cockpit API).

### openFrameworks (C++)

- **Architecture**: C++ creative coding toolkit. OpenGL-based. ofShader, ofFbo for shader/FBO management.
- **Compute shaders**: Yes, via raw OpenGL compute (GL 4.3+).
- **Multi-technique**: Manual FBO management, straightforward but verbose.
- **Web output**: No native path. Would need separate web implementation.
- **Assessment**: Mature and proven for installations but C++ adds friction for a Python-based system. No advantage over wgpu for this architecture.

### Processing / p5.js

- **Assessment**: Not suitable. No compute shaders, performance ceiling too low for millions of particles.

### Verdict: **TouchDesigner proves the architecture works** (multi-technique GPU composition with audio-reactive parameters) but is wrong for this project (Windows-only, proprietary, no programmatic integration). The learning is architectural, not technological: use the same TOP-style pattern but in wgpu.

---

## 7. Compositing Theory

### Porter-Duff Operators

12 operators defining how source (S) and destination (D) combine based on alpha coverage:

| Operator | Formula | Use for Generative Layers |
|----------|---------|--------------------------|
| Source Over | S + D(1-αS) | Default. New layer on top. |
| Screen | 1-(1-S)(1-D) | Brightens. Luminous organic glow. |
| Multiply | S×D | Darkens. Shadow layering, depth. |
| Overlay | Screen if D>0.5, else Multiply | Contrast-preserving combination. |
| Soft Light | Dodge/burn | Subtle organic blending. |
| Add (Lighter) | S+D | Raw additive. Particle trails, light emission. |
| Difference | |S-D| | Interference patterns. Datamosh aesthetic. |

### What Produces Beautiful Organic Composition

From the W3C Compositing spec and practical VJ/installation work:

1. **Screen blend for luminous layers**: Reaction-diffusion output (bright patterns on dark) screened onto particle trails creates bioluminescent depth. Screen never darkens — light adds to light.

2. **Multiply for shadow/depth**: Voronoi cell edges multiplied into the base create organic shadow boundaries without harsh alpha edges.

3. **Additive for emission**: Particle trails and gradient fields as additive layers create the "living light" quality of bioluminescent organisms.

4. **Soft light for subtle modulation**: Gradient fields as soft-light layers gently shift the tonality of underlying techniques without dominating.

5. **Per-layer opacity as the primary artistic control**: The most important parameter isn't which blend mode but at what intensity. A reaction-diffusion layer at 0.05 opacity is a subtle texture; at 0.8 it's the dominant visual.

6. **Non-separable modes (hue, saturation, luminosity)** operate in perceptual color space. Applying a "hue" blend from a gradient field recolors the underlying reaction-diffusion while preserving its luminance structure — extremely powerful for ambient mood shifting.

### Depth-Based Composition

Beyond 2D alpha blending:
- **Stencil masking**: Voronoi cells as stencil regions, each filled with a different technique.
- **Depth buffer layering**: Assign z-depth to each technique. Closer techniques occlude farther ones with soft depth-of-field blur.
- **Signed distance field compositing**: SDF operations (union, intersection, smooth blend) between technique shapes create organic boundaries.

### Recommendation for This Project

Use **premultiplied alpha with per-layer blend mode and opacity**:
```
Layer 0 (base):      Gradient field, full opacity, normal blend
Layer 1 (structure): Voronoi tessellation, 0.3 opacity, multiply blend
Layer 2 (life):      Reaction-diffusion, 0.4 opacity, screen blend
Layer 3 (movement):  Particle flow, 0.6 opacity, additive blend
Layer 4 (memory):    Framebuffer feedback, 0.2 opacity, soft-light blend
```

All blend modes are single-line WGSL/GLSL functions. The artistic work is tuning the layer stack, not implementing blending.

---

## 8. Audio-Reactive Rendering

### The System's Audio Data

The existing `hapax_voice` system already produces:
- Audio energy/volume levels (via AudioProcessor)
- Spectral analysis is feasible from the existing audio pipeline

### Integration Architecture

TouchDesigner's CHOP→TOP pattern is the right model:

1. **Audio analysis agent** produces spectral data (bass, mid, high energy + beat detection) as JSON to a shared memory file or Unix socket.
2. **Render loop** reads these values each frame and maps them to shader uniforms:
   - Bass energy → reaction-diffusion feed rate (organic pulse)
   - Mid energy → particle emission rate
   - High energy → Voronoi cell count / turbulence
   - Beat detection → feedback amount spike (flash on beat)
   - Overall energy → global brightness/opacity

3. **Mapping functions** (linear, exponential, smoothed) prevent jarring visual jumps. Exponential smoothing with different attack/decay rates:
   ```
   smoothed = smoothed * (1 - alpha) + raw * alpha
   // attack alpha = 0.3 (fast response to onset)
   // decay alpha = 0.05 (slow fade after sound stops)
   ```

4. **Spectral bands to uniforms**: FFT → bark scale bands → normalize → smooth → map to shader parameters. Standard approach used by every VJ tool.

### Implementation

This is purely a data-flow problem, not a rendering problem. The render architecture doesn't need to know about audio — it just reads uniform values that happen to be driven by audio analysis. The audio→uniform mapping runs on CPU at 60fps with negligible cost.

---

## Structured Comparison

| Criterion | wgpu (Rust) | WebGL2 | GStreamer GL | Vulkan | TouchDesigner |
|-----------|-------------|--------|-------------|--------|---------------|
| **All 5 techniques** | Yes (compute+render) | Partial (no compute) | Partial (fragment only) | Yes | Yes |
| **Millions of particles** | Yes (compute buffer) | ~1M (texture hack) | Awkward | Yes | Yes |
| **Reaction-diffusion** | Yes (compute ping-pong) | Yes (FBO ping-pong) | Yes (FBO ping-pong) | Yes | Yes |
| **Voronoi JFA** | Yes (compute, 11 passes) | Yes (fragment, 11 FBO passes) | Possible | Yes | Yes |
| **Framebuffer feedback** | Yes (texture copy) | Yes (FBO read-self) | Yes (temporalfx exists) | Yes | Yes (Feedback TOP) |
| **5+ layer composition** | Yes (blend states) | Yes (final composite pass) | Yes (glvideomixer) | Yes | Yes (Composite TOP) |
| **60fps on RTX 3090** | Trivial (<5% GPU) | Easy | Easy | Trivial | Unknown |
| **Dedicated display** | Yes (winit/Wayland) | No (needs browser) | Yes (v4l2sink/autovideosink) | Yes | Yes (Windows only) |
| **Web embedding** | Yes (WASM+WebGPU) | Yes (native) | Yes (HLS/WebSocket) | No | No |
| **Dynamic technique add/remove** | Yes (bind groups) | Manual FBO mgmt | Pipeline modification | Yes | Yes (node graph) |
| **Audio-reactive** | Uniforms | Uniforms | GObject properties | Uniforms | CHOP→TOP export |
| **Linux support** | Yes (Vulkan backend) | Yes (browser) | Yes (native) | Yes | No |
| **Integration with existing system** | appsrc→GStreamer | Separate process | Native | appsrc→GStreamer | Impossible |
| **Language** | Rust (or Python via wgpu-py) | JavaScript | Python/Rust | C/Rust | Proprietary |
| **Beauty ceiling** | Unlimited | High | Moderate | Unlimited | Very high |

---

## Recommendation

### Primary Architecture: **wgpu (Rust) with GStreamer output routing**

```
┌─────────────────────────────────────────────────────┐
│  wgpu Render Engine (Rust binary, Vulkan backend)   │
│                                                     │
│  Compute Pass:                                      │
│    ├─ reaction_diffusion.wgsl (ping-pong textures)  │
│    ├─ particle_physarum.wgsl (storage buffer, 5M+)  │
│    ├─ voronoi_jfa.wgsl (11-pass compute)            │
│    └─ gradient_field.wgsl (perlin/fbm compute)      │
│                                                     │
│  Render Pass:                                       │
│    ├─ Layer 0: gradient field (normal blend)         │
│    ├─ Layer 1: voronoi cells (multiply blend)       │
│    ├─ Layer 2: reaction-diffusion (screen blend)    │
│    ├─ Layer 3: particle trails (additive blend)     │
│    ├─ Layer 4: temporal feedback (soft-light blend) │
│    └─ Post-process: vignette, color grade           │
│                                                     │
│  Uniform Sources:                                   │
│    ├─ Visual layer state (JSON from /dev/shm)       │
│    ├─ Audio energy (from hapax_voice agent)          │
│    └─ Cockpit API parameters (HTTP/WebSocket)       │
│                                                     │
│  Output:                                            │
│    ├─ Window (winit/Wayland → dedicated monitor)    │
│    └─ Framebuffer readback → shared memory          │
└──────────────┬──────────────────────────────────────┘
               │ raw frames via /dev/shm or appsrc
┌──────────────▼──────────────────────────────────────┐
│  GStreamer Output Pipeline (existing infrastructure) │
│    ├─ v4l2sink → loopback device                    │
│    ├─ hlssink2 → browser preview                    │
│    ├─ appsink → JPEG snapshots                      │
│    └─ splitmuxsink → recording                      │
└─────────────────────────────────────────────────────┘
```

### Why This Architecture

1. **Compute shaders unlock the algorithms that matter.** Physarum with 5M+ agents, reaction-diffusion at full resolution, JFA Voronoi — all run as compute dispatches. Fragment-only approaches can approximate these but with worse code and artificial constraints.

2. **Single command buffer per frame.** All simulation + all rendering + all composition in one GPU submission. No pipeline overhead, no inter-element buffering, no caps negotiation. The RTX 3090 will be bored.

3. **Same shaders, two outputs.** The wgpu render engine presents to a native Wayland window for the dedicated display. The same framebuffer copies to shared memory where GStreamer picks it up for HLS/web streaming. The existing GStreamer output infrastructure remains untouched.

4. **Web path exists.** The same WGSL shaders compile to WASM+WebGPU for a browser-native version. Chrome and Edge support WebGPU now. This is the future-proof path — when browser support is universal, the web view can run the same render engine directly instead of streaming frames.

5. **Rust integrates with the existing system.** The `temporalfx` GstGLFilter plugin is already written in Rust. A standalone wgpu binary reads state from the same /dev/shm files and cockpit API. No new language, no new paradigm.

6. **wgpu-py exists for prototyping.** Quick iteration on shader parameters and layer composition in Python before committing to the Rust binary.

### Migration Path

1. **Phase 1**: Write reaction-diffusion compute shader in WGSL, render to window via wgpu. Prove the pipeline. Port existing fragment shaders (FBM, post-process) to WGSL.
2. **Phase 2**: Add particle system (Physarum) as compute dispatch + instanced draw. Add Voronoi JFA.
3. **Phase 3**: Implement multi-layer composition with blend modes. Wire uniform sources (visual layer state, audio energy).
4. **Phase 4**: Add framebuffer readback → GStreamer appsrc for web/recording output. Wire to dedicated display.
5. **Phase 5**: WASM+WebGPU compilation for browser-native rendering (replaces HLS stream with direct GPU rendering in browser).

### What NOT to Do

- **Don't rewrite GStreamer output routing.** It works. Use it for delivery.
- **Don't use raw Vulkan.** wgpu gives you Vulkan's compute without the ceremony.
- **Don't try to add compute shaders to GStreamer GL filters.** You'd be smuggling GL compute calls into filter_texture callbacks, fighting the framework's fragment-shader-only model.
- **Don't use TouchDesigner.** It proves the architecture but it's Windows-only, proprietary, and can't integrate with the existing system.
- **Don't write everything as fragment shaders.** It works for some techniques but not for millions-of-particles simulation. Compute shaders exist for a reason.
