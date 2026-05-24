# DarkPlaces Engine Capabilities Audit

**Date:** 2026-05-23
**Context:** Evaluating DarkPlaces Quake engine as migration target for hapax-imagination (wgpu/WGSL) visual rendering pipeline.
**Source:** DarkPlaces `r10781.d93f9c42` (CachyOS `darkplaces-git` package), source audited from upstream `DarkPlacesEngine/darkplaces`.

---

## 1. GLSL Post-Processing Capabilities

### Current System (hapax-imagination)

12 serial `glfeedback` GLSL slots in the GStreamer compositor pipeline (`fx_chain.py`, configurable up to 24 via `HAPAX_COMPOSITOR_FX_SLOTS`). Each slot runs an independent fragment shader with per-slot uniforms. Effects include colorgrade, bloom, film grain, vignette, chromatic aberration, and custom algorithmic effects.

### DarkPlaces Post-Processing Architecture

DarkPlaces has a **single-pass** post-processing pipeline, not a serial slot chain. The pipeline is in `MODE_POSTPROCESS` in `shader_glsl.h` (lines 221-395) and rendered via `R_BlendView()` in `gl_rmain.c`.

**Built-in post-processing features (all compile-time `#define` flags):**

| Feature | Define | CVars | Notes |
|---------|--------|-------|-------|
| Bloom | `USEBLOOM` | `r_bloom`, `r_bloom_colorscale`, `r_bloom_brighten`, `r_bloom_blur`, `r_bloom_resolution`, `r_bloom_colorexponent`, `r_bloom_colorsubtract`, `r_bloom_scenebrightness` | Multi-pass Gaussian blur via `MODE_BLOOMBLUR`, composited additively in the postprocess pass. Resolution-independent (default 320px). |
| Saturation | `USESATURATION` | `r_glsl_saturation`, `r_glsl_saturation_redcompensate` | Luminance-based desaturation with optional red compensation ("vampire sight"). Applied before gamma. |
| Gamma Ramps | `USEGAMMARAMPS` | `v_glslgamma` | 1D texture lookup per-channel. Full arbitrary color grading via custom ramp textures. |
| View Tint | `USEVIEWTINT` | (engine-internal) | Full-screen color overlay with alpha blend. |
| Color Fringe | `USECOLORFRINGE` | `r_colorfringe` | Chromatic aberration — radial R/B offset from screen center. |
| FXAA | `USEFXAA` | `r_fxaa` | NVIDIA FXAA implementation (Timothy Lottes white paper). |
| Motion Blur | (framebuffer ghost) | `r_motionblur`, `r_damageblur` | Ghost texture accumulation in `r_fb.ghosttexture`. |
| Custom Post-Process | `USEPOSTPROCESSING` | `r_glsl_postprocess`, `r_glsl_postprocess_uservec1..4` | 4 user-defined vec4 uniforms (`UserVec1..4`), plus `PixelSize`, `ClientTime`. Default code: Sobel edge detect + directional blur. |
| HDR/Iris Adaptation | `R_HDR_UpdateIrisAdaptation()` | `r_hdr_irisadaptation` | Automatic exposure adjustment. |
| Trippy | `USETRIPPY` | `r_trippy` | Vertex-space sinusoidal distortion (vertex shader, not post-process, but affects full scene). |

**Custom shader override mechanism:**

1. Run `r_glsl_dumpshader` in console — writes internal shaders to `glsl/default.glsl`
2. Edit the dumped file — the engine loads from disk if present, falling back to built-in
3. The 4 `uservec` uniforms are specifically designed for custom post-processing parameters controlled at runtime via cvars

### Equivalence Assessment

| Our Slot | DarkPlaces Equivalent | Gap? |
|----------|----------------------|------|
| Colorgrade | `USEGAMMARAMPS` (1D LUT) + `USESATURATION` | **Partial.** No 3D LUT or per-channel curves. 1D gamma ramps cover basic grading but not split-tone, lift/gamma/gain, or hue rotation. |
| Bloom | `USEBLOOM` (full pipeline) | **Full.** Multi-pass blur with subtract/exponent/scale controls. |
| Film grain | Custom `USEPOSTPROCESSING` shader | **Achievable.** Must be written as custom GLSL via `UserVec` uniforms for grain intensity/scale. `ClientTime` available for animation. |
| Vignette | Custom `USEPOSTPROCESSING` shader | **Achievable.** Radial falloff from `TexCoord1.xy` center. |
| Chromatic aberration | `USECOLORFRINGE` | **Full.** Built-in radial R/B split. |
| Edge detect / sharpen | Default `USEPOSTPROCESSING` code (Sobel) | **Full.** Built-in Sobel + directional blur blend. |
| Custom algorithmic FX | `USEPOSTPROCESSING` + custom `glsl/default.glsl` | **Constrained.** Only 4 `UserVec` uniforms for parameter injection. No multi-pass chaining without engine modification. |

### Critical Limitation: No Serial Shader Chain

DarkPlaces renders post-processing in a **single pass**: scene → bloom blur → composite + postprocess → screen. There is no equivalent of our 12-slot serial chain where each slot reads the previous slot's output. The `r_viewfbo` system manages the main rendertarget but doesn't expose a configurable multi-pass chain.

**To replicate the serial chain, you would need to either:**
- (a) Pack all effects into a single monolithic fragment shader (loses modularity)
- (b) Modify the engine C code to add FBO ping-pong passes (requires engine fork)
- (c) Use CSQC + render-to-texture tricks (limited, engine doesn't expose arbitrary FBO access to QuakeC)

---

## 2. Dynamic Texture Replacement

### Engine Texture Loading

DarkPlaces supports **TGA, PNG, JPG, PCX, WAL, LMP** formats. Texture search paths (in priority order for textures):

```
%s.tga → %s.png → %s.jpg → %s.pcx → %s.wal
```

For overrides:
```
override/%s.tga → override/%s.png → override/%s.jpg → textures/%s.tga → ...
```

### SkinFrame System

The `R_SkinFrame` system (`gl_rmain.c:2157-2460`) manages all model/entity textures:

- `R_SkinFrame_Find(name, flags, ...)` — CRC-hashed lookup table (1024 buckets)
- `R_SkinFrame_LoadExternal(name, flags, ...)` — loads from disk using `loadimagepixelsbgra()`
- `R_SkinFrame_PrepareForPurge()` / `R_SkinFrame_Purge()` — generation-based cache eviction (sequence counter wraps at 200)
- Textures support `_norm`, `_gloss`, `_glow`, `_pants`, `_shirt`, `_reflect`, `_bump`, `_alpha` suffixes for material channels

### Dynamic Updates

- `R_UpdateTexture(rt, data, x, y, z, w, h, d, combine)` — uploads raw pixel data to an existing GPU texture. Supports partial updates (`R_UploadPartialTexture`). The `combine` flag defers upload for batch efficiency.
- `GLTEXF_DYNAMIC` flag marks textures as frequently updated (optimizes GL state)
- `R_LoadTexture2D(pool, name, w, h, data, type, flags, miplevel, palette)` — creates new textures programmatically

### Runtime Texture Refresh

**File-based replacement:** DarkPlaces loads textures on demand via `loadimagepixelsbgra()`. If you overwrite a TGA/PNG on disk, the texture will reload on:
- `r_restart` (full texture reload command)
- Map change
- `R_SkinFrame_Purge()` cycle (generation-based, automatic)

**Programmatic replacement via QuakeC:** Not directly exposed. CSQC can `precache_pic()` and `drawpic()` but cannot upload raw pixel data to arbitrary textures.

**Per-frame texture injection:** Possible at the C level via `R_UpdateTexture()`, but not exposed to QuakeC scripting. Would require engine modification to add a `R_UpdateTexture` builtin for CSQC.

### Assessment

| Requirement | Supported? | Notes |
|-------------|-----------|-------|
| Write TGA → auto-reload | **Partial.** Requires `r_restart` or purge cycle. Not per-frame. |
| Per-frame texture update | **C API only.** `R_UpdateTexture()` exists but not exposed to QuakeC. |
| Per-second texture update | **Achievable** with engine modification (add CSQC builtin wrapping `R_UpdateTexture`). |
| Material channel replacement | **Yes.** `_norm`, `_glow`, `_gloss` suffix convention. |
| Skinframe hot-swap | **Yes.** Re-calling `R_SkinFrame_LoadExternal()` with same name replaces the texture after purge. |

---

## 3. Particle System

### Architecture

DarkPlaces has a sophisticated **data-driven particle system** via `effectinfo.txt`:

- **Particle types** (`ptype_t`): `alphastatic`, `static`, `spark`, `beam`, `rain`, `raindecal`, `snow`, `bubble`, `blood`, `smoke`, `decal`, `entityparticle`, `explode`, `explode2`
- **Orientations** (`porientation_t`): `BILLBOARD` (camera-facing), `SPARK` (velocity-stretched), `ORIENTED_DOUBLESIDED` (world-space plane), `VBEAM`/`HBEAM` (point-to-point beams)
- **Blend modes** (`pblend_t`): `ALPHA`, `ADD`, `INVMOD`

### effectinfo.txt Parameters

Each named effect can specify (per `particleeffectinfo_t`, 40+ fields):

- `color` — hex RRGGBB range (interpolated randomly)
- `tex` — texture atlas range
- `size` — min/max/growth
- `alpha` — min/max/fade
- `time` — lifetime range
- `gravity`, `bounce`, `airfriction`, `liquidfriction`
- `originjitter`, `velocityjitter` — randomization volumes
- `stretchfactor` — velocity-based elongation
- `rotate` — base angle + spin speed
- `lightradiusstart`, `lightradiusfade`, `lighttime`, `lightcolor` — **dynamic light per particle**
- `lightshadow`, `lightcubemapnum` — shadow-casting + cubemap projection per-particle light
- `lightcorona` — corona effect around particle light
- `staincolor`, `staintex`, `stainalpha`, `stainsize` — surface stain decals on impact

### CSQC Particle Control

```c
particleeffectnum(string name)     // resolve effect name → index
pointparticles(effectnum, origin, vel, count)  // spawn burst
trailparticles(entity, effectnum, start, end)  // spawn trail
```

Effects are reloaded at runtime via `cl_particles_reloadeffects`. Per-map overrides: `maps/<mapname>_effectinfo.txt`.

### Volumetric Capabilities Assessment

| Effect | Possible? | How |
|--------|-----------|-----|
| Volumetric light beams | **Yes** — `PARTICLE_HBEAM`/`PARTICLE_VBEAM` with additive blend + stretch. Plus corona system on dynamic lights. Not true volumetric scattering but visually convincing. |
| Ambient dust motes | **Yes** — `pt_alphastatic` with slow velocity, small size, long lifetime, `BILLBOARD` orientation. Standard effectinfo pattern. |
| Energy effects around entities | **Yes** — `pt_entityparticle` (orbiting particles) + `pt_static` additive billboards + dynamic lights. `CL_EntityParticles()` provides built-in orbital ring. |
| Fog-interacting particles | **Partial** — particles are fogged by the engine's distance fog, but no volumetric fog interaction (no light scattering through particle clouds). |
| Particle-emitted dynamic lights | **Yes** — `lightradiusstart/fade/time/color` per particle effect, with optional shadow casting and cubemap projection. |

### Limitations

- No GPU particle simulation (all CPU-side)
- Maximum `MAX_PARTICLEEFFECTINFO` effects (compile-time limit, typically 4096)
- No particle collision callbacks to QuakeC (bounce is physics-only)
- No volumetric scattering / god rays (billboard-only rendering)
- Particle count limited by `cl_maxparticles` (default 16384)

---

## 4. Fog System

### Implementation

DarkPlaces has a **multi-mode fog system** implemented in both C (`gl_rmain.c`) and GLSL (`shader_glsl.h`):

**Fog modes:**
- `USEFOGOUTSIDE` — fog outside a plane (standard distance fog)
- `USEFOGINSIDE` — fog inside a plane
- `USEFOGHEIGHTTEXTURE` — height-gradient fog with texture-driven color

**Core parameters** (all in `r_refdef.fog_*`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `fog_density` | 0 | Exponential fog density |
| `fog_red/green/blue` | 0/0/0 | Fog color (RGB) |
| `fog_alpha` | 1.0 | Fog opacity |
| `fog_start` | 0 | Distance where fog begins |
| `fog_end` | 16384 | Distance where fog is fully opaque |
| `fog_height` | 1<<30 | Height plane for height fog |
| `fog_fadedepth` | 128 | Vertical fade distance |
| `fog_height_texturename` | "" | Texture for height-based fog color gradient |

**Fog models:**
- `r_fog_exp2 = 0` → GL_EXP: `alpha = exp(-density * 0.004 * d)` (linear exponential)
- `r_fog_exp2 = 1` → GL_EXP2: `alpha = exp(-density^2 * 0.0001 * d^2)` (quadratic, Nehahra style)
- Height fog: per-pixel fog plane distance calculation with fade, optionally textured

### Height Fog with Gradient Texture

The `fog_height_texturename` parameter loads an image whose pixel column encodes fog color at different heights. The GLSL reads:

```glsl
vec4 fogheightpixel = dp_texture2D(Texture_FogHeightTexture,
    vec2(1,1) + vec2(FogPlaneVertexDist, FogPlaneViewDist) * (-2.0 * FogHeightFade));
fogfrac = fogheightpixel.a;
return mix(fogheightpixel.rgb * fc, surfacecolor.rgb,
    dp_texture2D(Texture_FogMask, ...));
```

This allows colored fog gradients that vary by height — e.g., warm fog at ground level fading to cool fog above.

### CSQC Runtime Control

Full fog control via `setproperty()` / `getproperty()` in CSQC:

```
VF_FOG_DENSITY, VF_FOG_COLOR, VF_FOG_COLOR_R/G/B,
VF_FOG_ALPHA, VF_FOG_START, VF_FOG_END,
VF_FOG_HEIGHT, VF_FOG_FADEDEPTH
```

All parameters can be changed **per-frame** from QuakeC, enabling dynamic fog that responds to game state.

### Per-Entity Fog

**Not directly supported.** Fog is a global scene property applied uniformly to all geometry via the fragment shader's `FogVertex()` function. There is no per-entity or per-material fog override.

However, entities can use `USEGLOW` textures (fullbright/emissive) which render at full brightness regardless of fog, effectively "punching through" fog. Combined with `MATERIALFLAG_NOFOG` (if supported by the entity's material), individual entities can opt out of fog.

### Assessment

| Requirement | Supported? | Notes |
|-------------|-----------|-------|
| Global distance fog | **Yes** — exp/exp2 with density/start/end |
| Colored fog | **Yes** — full RGB control |
| Fog gradients | **Yes** — via height texture (1D color gradient) |
| Per-entity fog | **No** — global only. Entities can opt out via glow/nofog but not have different fog. |
| Dynamic fog (runtime) | **Yes** — full CSQC `setproperty()` access, per-frame updates |
| Height-based fog | **Yes** — fog plane + fade depth + optional gradient texture |
| Volumetric fog | **No** — screen-space distance fog only, no ray-marched volumes |

---

## 5. Summary: Migration Feasibility

### What DarkPlaces Does Well

1. **Bloom** — production-quality multi-pass pipeline, superior to what most game engines shipped in the Quake era
2. **Particles** — extremely rich data-driven system with per-particle dynamic lights, shadow casting, cubemap projection
3. **Fog** — height-aware with texture gradients, full CSQC runtime control
4. **Lighting** — real-time shadow mapping, coronas, cubemap-projected lights, up to hundreds of dynamic lights
5. **Custom shader injection** — `r_glsl_dumpshader` → edit `glsl/default.glsl` → engine loads from disk
6. **CSQC scripting** — full 2D drawing primitives, entity spawning, particle emission, fog control, dynamic lights

### Critical Gaps vs. hapax-imagination

1. **No serial shader chain.** Our 12-slot glfeedback pipeline has no equivalent. DarkPlaces post-processing is single-pass. Replicating our modular effect chain would require either a monolithic uber-shader or engine modification to add FBO ping-pong.

2. **No per-frame texture injection from script.** `R_UpdateTexture()` exists in C but is not exposed to CSQC. Runtime texture replacement requires `r_restart` or engine modification. This blocks our pattern of writing compositor output frames and having the engine display them.

3. **No 3D LUT color grading.** Only 1D gamma ramps. Split-tone, lift/gamma/gain, and hue rotation would need custom GLSL.

4. **4 user vec uniforms only.** Our system passes 9+ expressive dimensions per shader node. The `UserVec1..4` mechanism gives 16 floats total for custom post-processing. Would need engine extension for more.

5. **CPU-only particles.** For large particle counts (dust fields, energy effects), the CPU particle system may become a bottleneck compared to GPU compute particles.

6. **No wgpu/Vulkan path.** DarkPlaces is OpenGL-only. Our current WGSL shaders would need complete rewrite to GLSL. The 62-node vocabulary in `agents/shaders/nodes/` is not portable.

### Recommendation

DarkPlaces is a viable **3D scene renderer** with strong lighting, particles, and fog. For the migration, it makes sense as a **scene host** (3D environment, entities, lights, particles, fog) with post-processing handled either by:

- A custom DarkPlaces fork adding multi-pass FBO support and additional uniforms
- An external post-processing pipeline (e.g., the compositor reading DarkPlaces output via v4l2loopback and applying our existing glfeedback chain on top)

The particle and fog systems are immediately usable for ambient environmental effects. The post-processing gap is the primary engineering challenge.
