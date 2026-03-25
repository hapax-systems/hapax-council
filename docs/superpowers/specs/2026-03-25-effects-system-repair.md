# Effects System Repair — Design Specification

**Date**: 2026-03-25
**Scope**: All 18 composite/HLS effects, smooth live filter settings, systemic issues
**Type**: Epic (multi-batch implementation)
**Authority**: `docs/research/visual-effects-source-characteristics.md` defines the 4-5 characteristics each effect must achieve.

---

## 1. Problem Statement

The Logos composite and HLS effects system has 18 visual effects. Evaluated against their documented source characteristics, most are broken or mediocre:

- **0-0.5/5 (fundamentally broken)**: Night Vision, Silhouette, Slit-scan
- **1-1.5/5 (wrong approach)**: Ghost, Datamosh, Trails, Trap, Ambient
- **2-2.5/5 (missing key features)**: VHS, Neon, Thermal, Feedback, Screwed, Pixsort, Halftone, Glitch Blocks
- **4/5 (minor gaps)**: Diff, ASCII

Additionally, smooth live filter transitions are hard-cut (no interpolation), and overlay drift silently disables when filter overrides are active.

Frontend (`compositePresets.ts`) and backend (`studio_effects.py`) presets diverge significantly for the same effects.

---

## 2. Architecture Context

### Two-Layer System

**Backend (GPU)**: GStreamer pipeline with 11 GLSL shaders in fixed order, all always present with uniform-based passthrough:

```
color_grade → vhs → thermal → halftone → glitch_blocks → pixsort → ascii → slitscan → warp → gleffects → temporalfx → post_process
```

- Preset switching updates uniforms only (no pipeline rebuild)
- Beat-reactive modulation at 30fps via audio energy
- `temporalfx` Rust plugin provides FBO ping-pong for temporal accumulation
- `gleffects` provides native glow (15) and Sobel (16) effects (mutually exclusive — single element, one effect at a time)

**Frontend (Canvas 2D)**: `CompositeCanvas.tsx` polls JPEG snapshots at 10fps, composites with:
- Trail persistence (ping-pong back buffer with destination-out fade)
- Spatial drift (sinusoidal, fractional pixel accumulation)
- Warp (pan/rotate/zoom/slice, pre-rendered to scratch canvas)
- Stutter engine (play/freeze/replay state machine)
- Post-effects (scanlines, band displacement, vignette, syrup gradient)
- Hue rotation (Neon/Feedback)
- Overlay layer (delayed smooth source)

### Constraints

- GLSL ES 2.0 (no compute shaders)
- Canvas 2D: no per-pixel noise via ImageData (kills 60fps at 1080p)
- SVG `<feTurbulence>` available via inline SVG + `ctx.filter = "url(#id)"`
- All shader stages must support passthrough (uniform sentinel values)
- Frontend JPEG polling at 100ms limits temporal resolution to 10fps

---

## 3. Systemic Fixes

These fixes affect multiple effects and should be implemented first.

### 3.1 SVG Noise Overlay System

**Problem**: Multiple effects need noise (Night Vision scintillation, VHS tape grain, Trap degradation, Diff noise floor) but the frontend has no noise capability.

**Design**: Use a small offscreen canvas (240x135, 1/8 of 1080p) filled with random grayscale pixels via `ImageData` + `Math.random()`. Scale up to full resolution with `imageSmoothingEnabled = false` for crunchy grain. This avoids SVG feTurbulence performance problems (CPU-bound, too slow at full resolution even with GPU acceleration).

**Implementation**:
```typescript
// Setup (once, in useEffect)
const noiseCanvas = document.createElement("canvas");
noiseCanvas.width = 240;
noiseCanvas.height = 135;
const noiseCtx = noiseCanvas.getContext("2d")!;
const noiseData = noiseCtx.createImageData(240, 135);

// Per-frame (when noise.animated) or once (when static)
function regenerateNoise() {
  const d = noiseData.data;
  for (let i = 0; i < d.length; i += 4) {
    const v = Math.random() * 255;
    d[i] = d[i+1] = d[i+2] = v;
    d[i+3] = 255;
  }
  noiseCtx.putImageData(noiseData, 0, 0);
}
```

**Application**: After main composite, draw noise overlay:
```typescript
ctx.save();
ctx.imageSmoothingEnabled = false;  // nearest-neighbor = crunchy grain
ctx.globalAlpha = noise.intensity;
ctx.globalCompositeOperation = "overlay";
ctx.drawImage(noiseCanvas, 0, 0, w, h);
ctx.restore();
```

**Performance**: 240x135 ImageData fill with Math.random() takes <0.1ms. drawImage upscale is GPU-accelerated. For animated noise, regenerate every 2-3 frames (20-30fps grain) to save CPU. For static noise, generate once at mount.

**Configuration**: Add optional `noise` field to `CompositePreset`:

```typescript
noise?: {
  enabled: boolean;
  intensity: number;    // 0-1, overlay alpha
  animated: boolean;     // if true, regenerate grain every 2-3 frames (scintillation)
};
```

**Presets using noise**: Night Vision (animated, 0.15), VHS (static, 0.06), Trap (static, 0.12), Diff (animated, 0.03).

### 3.2 Frontend/Backend Preset Alignment

**Problem**: Frontend and backend define the same effects with divergent parameters.

**Design**: Backend presets are authoritative for GPU shader parameters. Frontend presets are authoritative for canvas compositing parameters. Neither should duplicate the other's domain.

Specific alignment needed:

| Effect | Parameter | Frontend (current) | Backend (current) | Aligned Value | Owner |
|--------|-----------|--------------------|--------------------|---------------|-------|
| Ghost | trail blend | source-over | add | lighter | Frontend |
| Screwed | trail opacity | 0.2 | 0.7 | 0.55 | Frontend |
| Neon | saturation | 3.5 | 1.4 | Frontend: 2.5, Backend: 1.4 | Split (different layers) |
| Ambient | brightness | 0.7 | 0.3 | Frontend: 0.45, Backend: 0.3 | Split |
| Feedback | trail opacity | 0.7 | 0.92 | 0.85 | Frontend |

The backend color_grade affects the GPU output that the frontend then composites. They stack multiplicatively. Values must be tuned together, not independently.

### 3.3 Smooth Filter Transition

**Problem**: Filter changes are instantaneous hard cuts. Overlay drift disabled when filter overrides active.

**Design**:

**Filter crossfade**: When `liveFilter` or `smoothFilter` changes, crossfade over 300ms:
1. On filter change, store `prevFilter` and start a 300ms timer
2. During crossfade: render frame twice (once with old filter, once with new), blend by progress
3. After crossfade completes: discard old filter, render normally

**Implementation**: Track `prevLiveFilter`, `filterTransitionStart`, `filterTransitionDuration` in the render loop. On each tick during transition:
```typescript
const progress = Math.min(1, (now - filterTransitionStart) / 300);
// Render with old filter at (1-progress) alpha, then new filter at progress alpha
```

**Overlay drift fix**: Remove the `hasFilterOverrides` condition that disables drift. Overlay drift should always apply when the overlay config specifies it. The filter override only changes the CSS filter string, not the spatial behavior.

### 3.4 Warp Animation Complexity

**Problem**: All warp is purely sinusoidal — predictable, cyclic. Effects like Screwed and Feedback need organic, non-repeating motion.

**Design**: Replace single-frequency sine with multi-harmonic sum for presets that need organic motion:

```typescript
// Organic drift: sum of incommensurate frequencies
const organicX = Math.sin(t * 1.0) * 0.5 + Math.sin(t * 0.618) * 0.3 + Math.sin(t * 0.237) * 0.2;
```

Use golden-ratio-derived frequency ratios (1.0, 0.618, 0.237) to prevent visible repetition. Apply to Screwed, Feedback, and Ghost warp parameters.

---

## 4. Per-Effect Fixes

Ordered by severity (worst first). Each effect lists its source characteristics and the specific change needed to achieve it.

### 4.1 Night Vision (0/5 → target 4/5)

**Source characteristics**:
1. Monochrome green phosphor — entire image in P-43 green
2. Scintillation noise — crawling, sparkling grain
3. Bright-source blooming/halo — point lights wash out with halos
4. Circular field of view — round tube viewport
5. Fixed-pattern noise (blemishes) — static spots

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Green phosphor | Replace CSS `saturate(0)` + green syrup gradient with `saturate(0) sepia(1) hue-rotate(70deg) saturate(3) brightness(1.3)`. This maps grayscale → sepia → green, making the ENTIRE image green, not just the bottom gradient |
| 2 | Scintillation | Enable animated noise overlay (systemic §3.1). High baseFrequency (1.5), animated seed, moderate intensity (0.15) |
| 3 | Bloom | Bloom post-effect via 1/4-resolution temp canvas: `bloomCtx.filter = "brightness(0.3) contrast(100) blur(4px)"`, drawImage from main at 1/4 size (bright-pass + blur in one GPU call), then composite back at full size with `lighter` blend at 0.4 alpha. The 4px blur at 1/4 res looks like 16px at full res. See §3.1a for bloom engine details |
| 4 | Circular FOV | Replace radial gradient vignette with hard circular clip. `ctx.arc(w/2, h/2, radius, 0, TAU)` + `ctx.clip()`. Outside the circle: black. Inside: content. Radius = ~42% of canvas width (simulating NVG tube) |
| 5 | Fixed-pattern | Draw 3-5 small circles at fixed positions (seeded by canvas dimensions) with slight brightness variation. These persist across frames as tube blemishes |

**Backend**: Route to "clean" preset (no GPU shader needed — all processing is canvas-side CSS filters).

**Frontend preset**:
```typescript
{
  name: "NightVision",
  colorFilter: "saturate(0) sepia(1) hue-rotate(70deg) saturate(3) brightness(1.3) contrast(1.4)",
  trail: { filter: "saturate(0) brightness(0.7)", blendMode: "lighter", opacity: 0.2, count: 3, driftX: 0, driftY: 0 },
  noise: { enabled: true, intensity: 0.15, baseFrequency: 1.5, animated: true },
  effects: { scanlines: true, vignette: false, vignetteStrength: 0, ... },
  circularMask: true,  // new field
  bloom: { enabled: true, threshold: 0.8, radius: 12, alpha: 0.4 },  // new field
}
```

### 4.2 Silhouette (0.5/4 → target 4/4)

**Source characteristics**:
1. Binary tonal reduction — subject black, background bright
2. Luminous rim/edge light — thin bright edge at contour
3. Shape as sole information carrier
4. High-key background — bright, not dark

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Binary reduction | Increase contrast further: `contrast(5) brightness(0.8)`. The extreme contrast crushes all midtones to near-binary |
| 2 | Rim light | New canvas post-effect: draw frame with Sobel-approximation edge detection (draw frame offset ±1px in each direction with `difference` blend, then brighten). Alternatively, enable Sobel on backend via `gleffects` effect 16, route to GPU edge-detected output |
| 3 | Shape only | The high contrast + edge detection achieves this |
| 4 | High-key background | Invert the image AFTER contrast crush: `contrast(5) brightness(0.8) invert(1)`. This makes bright areas (background after IR processing) white and dark areas (subject) black, with bright rim edges |

**Backend**: Use `gleffects` Sobel (effect 16) + high contrast color grade. This gives GPU-accelerated edge detection.

**Frontend preset**:
```typescript
{
  name: "Silhouette",
  colorFilter: "saturate(0) contrast(5) brightness(0.8) invert(1)",
  trail: { filter: "saturate(0) contrast(3) brightness(0.5) invert(1)", blendMode: "source-over", opacity: 0.15, count: 2, driftX: 0, driftY: 0 },
  effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
}
```

**Backend preset**: Enable `use_sobel: True` on gleffects element.

### 4.3 Slit-scan (0.5/5 → target 3.5/5)

**Source characteristics**:
1. Temporal stratification — different positions = different moments
2. Motion-dependent stretching
3. Infinite corridor/tunnel convergence
4. Scan-line interlace artifacts
5. Fluid elastic warping

**Changes**:

True slit-scan requires a temporal frame buffer. The `temporalfx` plugin provides FBO ping-pong but is designed for accumulation, not per-scanline temporal indexing. A new approach:

| # | Characteristic | Change |
|---|---|---|
| 1 | Temporal stratification | **Cannot achieve perfectly in single-pass GLSL.** Improve approximation: increase displacement magnitude so center-vs-edge UV offset is visually dramatic (0.15 → 0.4). Add scan_pos exponent to create more visible temporal banding |
| 2 | Motion-dependent | Increase warp_amount so moving objects distort more. Add chromatic separation proportional to displacement (already present, increase spread from 3 to 8 texels) |
| 3 | Tunnel convergence | Add zoom convergence: scale UV toward center proportional to scan_pos. `displaced_uv = mix(displaced_uv, vec2(0.5), scan_pos * 0.15)` |
| 4 | Interlace artifacts | Add visible banding: quantize scan_pos to discrete steps. `scan_pos = floor(scan_pos * 24.0) / 24.0` creates 24 visible temporal bands |
| 5 | Elastic warping | Increase warp wave amplitudes. Add secondary and tertiary harmonics |

**Shader changes** (`slitscan.frag`):
- Increase displacement quadratic coefficient from 0.15 to 0.4
- Quantize scan_pos for visible banding
- Add center-convergence zoom
- Increase chromatic spread from 3 to 8 texels
- Add second and third warp harmonics at incommensurate frequencies

**Frontend preset**: Increase trail count to 8 with vertical drift to enhance temporal smear feel.

### 4.4 Ghost (1/5 → target 4/5)

**Source characteristics**:
1. Exponential opacity decay ✅ (already works)
2. Temporal offset with spatial coherence
3. Additive luminance accumulation
4. Color channel smearing
5. Soft edge dissolution

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 2 | Spatial coherence | Reduce drift from 18x/24y to 3x/4y. Echoes should barely separate from the source — phosphor afterimages stay close |
| 3 | Additive | Change `blendMode` from `"source-over"` to `"lighter"`. Ghost layers add light, never subtract |
| 4 | Color smearing | Add `blur(1px)` and slight hue shift to trail filter: `"saturate(0.7) brightness(0.6) blur(1px) hue-rotate(5deg)"`. The blur + hue shift simulates differential chroma/luma decay |
| 5 | Soft dissolution | Increase blur progressively. Since all trails share one filter, use `blur(2px)` on the trail filter — older echoes accumulate more blur through the persistence buffer |

**Frontend preset**:
```typescript
trail: {
  filter: "saturate(0.7) brightness(0.6) blur(2px) hue-rotate(5deg)",
  blendMode: "lighter",
  opacity: 0.45,
  count: 5,
  driftX: 3,
  driftY: 4,
},
```

### 4.5 Datamosh (1/5 → target 3/5)

**Source characteristics**:
1. Pixel bleeding across scene boundaries
2. Block-structured distortion
3. Motion vector hallucination
4. Color smearing with palette preservation
5. Temporal instability

**Changes**:

True datamosh (I-frame removal, P-frame manipulation) is impossible in this pipeline. But the approximation can improve dramatically:

| # | Characteristic | Change |
|---|---|---|
| 1 | Pixel bleeding | Keep `difference` blend but lower contrast so colors bleed rather than XOR. Reduce trail filter contrast from 2.2 to 1.3. Increase trail opacity to create persistent color bleed |
| 2 | Block structure | Route to GPU `glitch_blocks` shader with large block size (32px) and moderate intensity (0.4). The block corruption gives macroblock-like structure. Reduce RGB split to keep colors recognizable |
| 3 | Motion vectors | Increase drift significantly (12x, 10y) with organic warp. The drift creates directional flow that approximates motion vector displacement |
| 4 | Palette preservation | **Remove all hue-rotate** from main and trail filters. Source colors must persist. Use `saturate(0.8)` only — no hue shifting |
| 5 | Temporal instability | Keep stutter engine. Increase freeze chance slightly |

**Backend preset**: Enable `use_glitch_blocks_shader` with large blocks + low RGB split. This gives the macroblock structure that pure canvas difference blend cannot.

**Frontend preset**:
```typescript
colorFilter: "saturate(0.8) contrast(1.4) brightness(1.1)",
trail: {
  filter: "saturate(0.9) contrast(1.3) brightness(1.2)",
  blendMode: "difference",
  opacity: 0.9,
  count: 6,
  driftX: 12,
  driftY: 10,
},
```

### 4.6 Trails (1.5/5 → target 4/5)

**Source characteristics**:
1. Saturated, luminous, additive color
2. Continuous smear (not discrete copies)
3. Bright-on-dark bias
4. No decay within trail body
5. Motion-dependent thickness

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Saturated color | Main filter: increase saturation to 1.4. Trail filter: `saturate(1.8) brightness(1.3)` — hyper-saturated, not muted. Remove sepia tint |
| 2 | Continuous smear | Reduce fade alpha (slower decay) so trails blend into each other. Increase trail count to 12. The 10fps limitation means we can't get truly continuous, but denser trails with slower fade approximate it |
| 3 | Bright-on-dark | Already correct with `lighter` blend ✅ |
| 4 | No body decay | Reduce fadeAlpha in `computeTrailAlphas`. For `lighter` mode, reduce baseFade from 0.05 to 0.03 — trails persist longer before fading |
| 5 | Motion-dependent | Cannot be achieved at JPEG polling level — motion magnitude is unknown. Accept this limitation |

**Frontend preset**:
```typescript
colorFilter: "saturate(1.4) brightness(1.15)",
trail: {
  filter: "saturate(1.8) brightness(1.3)",
  blendMode: "lighter",
  opacity: 0.75,
  count: 12,
  driftX: 2,
  driftY: 3,
},
```

### 4.7 Trap (1.5/4 → target 3.5/4)

**Source characteristics**:
1. Dominant black with selective accent color
2. Heavy vignette ✅
3. Strobe / flash synchronization
4. Grain, noise, degradation

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Black + accent | Keep multiply blend (darkens). Add accent: on random intervals (every 30-60 ticks), briefly flash `blendMode` to `lighter` for 2-3 ticks with high brightness filter. This creates the "warning signal" accent flashes |
| 3 | Strobe | New stutter-like mechanism: `strobe` field on preset. Every N ticks at random chance, draw a full-frame flash (white or accent color) for 1-2 ticks. `strobe: { chance: 0.03, color: "rgba(255, 40, 40, 0.3)", duration: 2 }` |
| 4 | Grain/noise | Enable noise overlay (systemic §3.1). Medium intensity (0.12), static (not animated), fine grain (baseFrequency 1.0) |

**Frontend preset changes**:
```typescript
noise: { enabled: true, intensity: 0.12, baseFrequency: 1.0, animated: false },
strobe: { chance: 0.03, color: "rgba(255, 40, 40, 0.3)", duration: 2 },
effects: { ...current, scanlines: true },  // add scanlines for degradation
```

### 4.8 Ambient (1.5/5 → target 3.5/5)

**Source characteristics**:
1. Glacial rate of change
2. Soft color fields with dissolving boundaries
3. Low information density
4. Generative non-repetition
5. Environmental integration

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Glacial change | Reduce fetch interval to 500ms (2fps). Add heavy blur to main filter: `blur(8px)`. Changes become imperceptible transitions |
| 2 | Soft color fields | Heavy blur dissolves edges. Reduce contrast to 0.8 to flatten detail. Low saturation (0.3) mutes colors to soft washes |
| 3 | Low density | The blur + low contrast + low saturation strips information |
| 4 | Non-repetition | Backend ambient_fbm shader already provides generative FBM noise. Increase ambient_brightness from 0.25 to 0.5 so the generative layer contributes more |
| 5 | Environmental | Extreme vignette (0.6) + very dim overall (brightness 0.4) makes it function as ambient light |

**Frontend preset**:
```typescript
colorFilter: "saturate(0.3) brightness(0.4) contrast(0.8) blur(8px)",
trail: { filter: "saturate(0.2) brightness(0.3) blur(12px)", blendMode: "lighter", opacity: 0.15, count: 3, driftX: 0, driftY: 1 },
effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.6 },
livePullIntervalMs: 500,
```

### 4.9 VHS (2.5/6 → target 5/6)

**Source characteristics**:
1. Head-switching noise ✅
2. Tracking misalignment — wider, drifting bands
3. Chroma bleed ✅
4. Dropout / oxide shedding — white/black horizontal streaks
5. Tape noise / luminance instability
6. Color palette — cool, washed-out blue/cyan (NOT warm sepia)

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 2 | Tracking | Widen noise band from 1.2% to 4% of frame height. Add a second band. Make bands drift at different speeds |
| 4 | Dropout | Add dropout effect to shader: random horizontal white streaks (1-3px tall, full width) at low probability per scanline per frame. `if (hash(vec2(floor(uv.y * u_height), u_time)) < 0.003) color.rgb = vec3(1.0);` |
| 5 | Tape noise | Enable noise overlay (systemic §3.1) at low intensity (0.06). Also add per-line luminance jitter in shader |
| 6 | Cool palette | **Replace sepia warmth with cool shift** in shader. Change line 73-74 from warm sepia `(1.15, 1.0, 0.85)` to cool cyan `(0.85, 0.95, 1.1)`. Mix at 0.3 instead of 0.35 |

**Shader changes** (`vhs.frag`):
- Change sepia target from `(1.15, 1.0, 0.85)` to `(0.85, 0.95, 1.1)` — cool shift
- Widen noise band from 0.012 to 0.04
- Add second scrolling noise band at different speed
- Add dropout: random white scanlines at 0.3% probability
- Add per-line luminance jitter: `color.rgb += (hash(vec2(floor(uv.y * u_height * 0.5), u_time * 3.0)) - 0.5) * 0.03`

### 4.10 Neon (2/5 → target 4/5)

**Source characteristics**:
1. Core-to-edge luminance gradient (bloom)
2. Chromatic aberration fringing
3. Color cycling ✅
4. High saturation against deep black
5. Phosphor persistence trails ✅

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Bloom | Add bloom post-effect (same technique as Night Vision §4.1 but with saturated colors). Threshold-based bright extraction + blur + additive composite |
| 2 | Chromatic aberration | Add chromatic aberration as a canvas post-effect: draw frame three times with slight offset — red channel +2px right, blue channel +2px left. Use `ctx.globalCompositeOperation = "lighter"` with color-channel isolation via CSS filters |
| 4 | Deep black | Change main filter: reduce brightness from 1.45 to 1.1. Add `contrast(1.8)` to crush blacks while keeping highlights. The bloom pass restores brightness to highlights only |

**Chromatic aberration implementation**: After main composite, draw two additional passes:
```typescript
// Red channel offset
ctx.save();
ctx.filter = "saturate(0) brightness(1.5) sepia(1) hue-rotate(-30deg) saturate(5)";
ctx.globalAlpha = 0.15;
ctx.globalCompositeOperation = "lighter";
ctx.drawImage(canvas, 2, 0);  // offset right
ctx.restore();
// Blue channel offset
ctx.save();
ctx.filter = "saturate(0) brightness(1.5) sepia(1) hue-rotate(200deg) saturate(5)";
ctx.globalAlpha = 0.15;
ctx.globalCompositeOperation = "lighter";
ctx.drawImage(canvas, -2, 0);  // offset left
ctx.restore();
```

### 4.11 Thermal (2/5 → target 4/5)

**Source characteristics**:
1. Temperature-mapped false color ✅ (Ironbow palette good)
2. No texture detail — only thermal contours
3. Hot-source blooming/halo
4. Cool-edge vignette ✅
5. Low spatial resolution with smooth gradients

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 2 | No texture | **Heavily increase blur**: change blur from 4-sample cross to proper Gaussian. Sample in a 5x5 grid with distance-weighted kernel. Effective downsampling to ~480x270 equivalent |
| 3 | Bloom | **Remove Sobel edge glow** (it enhances detail, contradicting thermal look). Replace with bloom: bright pixels (high luminance → hot in thermal) get radial bloom. Add `float bloom = smoothstep(0.7, 1.0, lum) * 0.3; color += bloom * vec3(1.0, 0.9, 0.7)` |
| 5 | Low resolution | Quantize UV to coarser grid before sampling: `uv = floor(uv * vec2(u_width, u_height) * 0.25) / (vec2(u_width, u_height) * 0.25)`. This reduces effective resolution to 480x270 |

**Shader changes** (`thermal.frag`):
- Replace Sobel edge detection with bloom on hot regions
- Add resolution reduction (UV quantization to 1/4 native)
- Increase blur kernel to 5x5 Gaussian
- Keep thermal noise but increase frequency for per-pixel scintillation

### 4.12 Feedback (2/5 → target 3.5/5)

**Source characteristics**:
1. Infinite recursive tunnel
2. Fractal self-similarity
3. Sensitivity to physical parameters
4. Time-delay evolution ✅
5. Luminance accumulation and color shift ✅

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Recursive tunnel | Increase zoom from 1.015 to 1.04. Increase zoom breath from 0.01 to 0.02. This makes each accumulated frame noticeably smaller, creating visible regression |
| 2 | Self-similarity | The increased zoom + high trail opacity (0.85) + additive blend creates recursive patterns as each frame's accumulated content appears within the next frame's accumulation |
| 3 | Parameter sensitivity | Use organic warp (§3.4) with incommensurate frequency ratios. Small pan/rotate changes create dramatically different patterns because they compound through the accumulation buffer |

**Frontend preset**:
```typescript
warp: { panX: 4, panY: 3, rotate: 0.012, zoom: 1.04, zoomBreath: 0.02, sliceCount: 0, sliceAmplitude: 0 },
trail: { filter: "saturate(3.0) contrast(1.1) brightness(1.4)", blendMode: "lighter", opacity: 0.85, count: 12, driftX: 2, driftY: 3 },
```

### 4.13 Screwed (2/5 → target 4/5)

**Source characteristics**:
1. Temporal drag / slowed time
2. Purple/violet color cast
3. Chopped repetition / stutter
4. Lo-fi degradation / blur
5. Dream-like spatial distortion ✅

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 1 | Temporal drag | Increase `livePullIntervalMs` from 180 to 300 (3.3fps — visibly slow). Increase trail opacity from 0.2 to 0.55. The combination of slow frame rate + high trail persistence creates the syrupy, viscous feel |
| 2 | Purple cast | Strengthen: increase hue-rotate from 250° to 260°, increase sepia from 0.4 to 0.5, add syrup gradient alpha. The purple should be unmistakable |
| 3 | Stutter | Reduce freeze chance from 0.5 to 0.2, increase freeze duration min/max from 3-10 to 8-20 ticks. Fewer stutters, but longer holds — mimics the rhythmic chopping of slowed records |
| 4 | Degradation | Add blur to main filter: `blur(2px)`. Enable noise overlay at low intensity (0.08). Reduce contrast slightly. The image should be soft and hazy |

**Frontend preset**:
```typescript
colorFilter: "saturate(0.5) sepia(0.5) hue-rotate(260deg) contrast(1.0) brightness(0.85) blur(2px)",
trail: { filter: "saturate(0.25) brightness(0.5) sepia(0.6) hue-rotate(270deg) blur(3px)", blendMode: "lighter", opacity: 0.55, count: 5, driftX: 0, driftY: 6 },
stutter: { checkInterval: 15, freezeChance: 0.2, freezeMin: 8, freezeMax: 20, replayFrames: 2 },
noise: { enabled: true, intensity: 0.08, baseFrequency: 0.8, animated: false },
livePullIntervalMs: 300,
```

### 4.14 Pixsort (2/5 → target 3.5/5)

**Source characteristics**:
1. Directional streaking along sort axis
2. Threshold-bounded intervals ✅
3. Color gradient within streaks
4. Preserved recognizability ✅
5. Textural rhythm

**Changes**:

Replace the weighted-average shader with a pseudo-sort approach (haxademic/Shadertoy 4lBBRz style):

| # | Characteristic | Change |
|---|---|---|
| 1 | Directional streaking | Sample N pixels (12-16) within the detected interval along sort direction. The fixed direction (pure horizontal or pure vertical, not diagonal) gives strong directional signature |
| 3 | Color gradient | Sort the N samples with a small bubble sort in the shader. Map the current pixel's position within the interval to the sorted array. This produces actual dark-to-light gradients within streaks |
| 5 | Textural rhythm | The sorted intervals create regular gradient bands — rain-like texture emerges from consistent sorting |

**Shader rewrite** (`pixsort.frag`):
1. Walk backward along sort direction to find interval start (pixel below threshold_low)
2. Walk forward to find interval end (pixel above threshold_high)
3. Sample 12 evenly-spaced pixels within the interval into a fixed-size array
4. Bubble sort the 12 samples by luminance (66 comparisons — within fragment shader budget)
5. Map current pixel's position-in-interval to sorted array index
6. Interpolate between nearest sorted samples for smooth gradient

**Direction**: Change default from 0.15 (diagonal) to 0.0 (pure horizontal) for canonical pixsort look. Add 1.0 (pure vertical) as the Asendorf "rain" variant.

### 4.15 Halftone (2.5/5 → target 4/5)

**Source characteristics**:
1. Uniform dot grid ✅
2. CMYK color through optical mixing
3. Screen angle moire potential ✅
4. Hard dot edges — no anti-aliasing
5. Tonal steps

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 2 | CMYK mixing | Fix subtractive color math. Current cyan subtraction `vec3(0.0, c_dot * 0.7, c_dot)` is wrong. Correct: cyan subtracts red → `color.r -= c_dot`. Magenta subtracts green → `color.g -= m_dot`. Yellow subtracts blue → `color.b -= y_dot`. Black subtracts all → `color -= vec3(k_dot)` |
| 4 | Hard edges | Replace `smoothstep(radius + 0.02, radius - 0.02, dist)` with `step(dist, radius)`. No anti-aliasing — mechanical crispness |
| 5 | Tonal steps | The hard `step()` edges naturally create more visible tonal quantization |

**Shader changes** (`halftone.frag`):
- Fix CMYK subtraction to correct channels
- Replace smoothstep with step in `halftone_dot` function

### 4.16 Glitch Blocks (2.5/5 → target 4/5)

**Source characteristics**:
1. Macroblock fragmentation ✅
2. Color banding / posterization
3. Horizontal displacement / scan offset
4. Data visualization bleed
5. Abrupt discontinuous boundaries ✅

**Changes**:

| # | Characteristic | Change |
|---|---|---|
| 2 | Posterization | Add color quantization to corrupted blocks: `color.rgb = floor(color.rgb * 4.0) / 4.0` — reduces to 4 levels per channel, creating hard color steps |
| 3 | Horizontal bias | Change displacement from 2D to primarily horizontal. Set `shiftY` coefficient to 0.1× of `shiftX`. Real codec corruption shifts scanlines horizontally |
| 4 | Data bleed | Add a fifth corruption type: "data pattern" — fill block with repeating gradient based on block position. `float pattern = mod(pixel.x + pixel.y * 3.0, 8.0) / 8.0; color.rgb = vec3(pattern)` |

### 4.17 Diff (4/5 → target 5/5)

**Source characteristics**: All good except noise floor.

**Change**: Enable animated noise overlay (§3.1) at very low intensity (0.03). The faint scintillation across static areas gives the "alive" quality that distinguishes real frame differencing from a clean mask.

### 4.18 ASCII (4/5 → target 4.5/5)

**Source characteristics**: All good except procedural shapes vs actual characters.

**Change**: The geometric fill patterns are a reasonable approximation of character density mapping. The gap is aesthetic, not functional. Accept this limitation — rendering actual font glyphs in a fragment shader would require a font atlas texture, which adds pipeline complexity for marginal visual improvement.

**Minor tweak**: Increase default cell_size from 8 to 10 for more visible character structure at 1080p.

---

## 5. New Preset Fields

The following new fields are added to `CompositePreset`:

```typescript
interface CompositePreset {
  // ... existing fields ...

  noise?: {
    enabled: boolean;
    intensity: number;     // 0-1
    baseFrequency: number; // 0.1-2.0
    animated: boolean;     // per-tick seed change
  };

  bloom?: {
    enabled: boolean;
    threshold: number;     // 0-1, brightness cutoff
    radius: number;        // blur radius in px
    alpha: number;         // composite opacity
  };

  strobe?: {
    chance: number;        // per-tick probability (0-0.1)
    color: string;         // rgba() string
    duration: number;      // ticks
  };

  circularMask?: boolean;  // Night Vision hard circular clip

  livePullIntervalMs?: number;  // already exists
}
```

These are optional fields. Presets that don't use them omit them (undefined = disabled).

---

## 6. Files Modified

### Backend (GPU shaders)
| File | Changes |
|------|---------|
| `agents/shaders/vhs.frag` | Cool color shift, wider noise bands, dropout, per-line jitter |
| `agents/shaders/thermal.frag` | Remove Sobel, add bloom, UV quantization, heavier blur |
| `agents/shaders/pixsort.frag` | Full rewrite: pseudo-sort with fixed-size array |
| `agents/shaders/halftone.frag` | Fix CMYK channels, step() instead of smoothstep() |
| `agents/shaders/glitch_blocks.frag` | Add posterization, horizontal bias, data pattern |
| `agents/shaders/slitscan.frag` | Increase displacement, add banding, center convergence |
| `agents/shaders/ascii.frag` | Increase default cell_size |

### Backend (Python)
| File | Changes |
|------|---------|
| `agents/studio_effects.py` | Align preset params with frontend, add Sobel for silhouette, update thermal/datamosh params |

### Frontend
| File | Changes |
|------|---------|
| `hapax-logos/src/components/studio/compositePresets.ts` | All 18 presets updated per §4; new fields (noise, bloom, strobe, circularMask) |
| `hapax-logos/src/components/studio/CompositeCanvas.tsx` | Add noise overlay system, bloom pass, strobe engine, circular mask, filter crossfade, overlay drift fix, organic warp |

### No changes needed
| File | Reason |
|------|--------|
| `agents/shaders/color_grade.frag` | Works correctly |
| `agents/shaders/post_process.frag` | Works correctly |
| `agents/shaders/ambient_fbm.frag` | Works correctly |
| `agents/shaders/slice_warp.frag` | Works correctly |
| `agents/studio_compositor.py` | Pipeline structure unchanged; uniform updates via existing mechanism |
| `compositeFilters.ts` | CSS filter library unchanged |
| `effectSources.ts` | Source routing unchanged |

---

## 7. Implementation Batches (Priority Order)

### Batch 1: Systemic Infrastructure
- SVG noise overlay system (§3.1)
- Filter crossfade (§3.3)
- Overlay drift fix (§3.3)
- Bloom post-effect engine
- Strobe engine
- Circular mask support
- Organic warp (§3.4)
- New preset fields (§5)

### Batch 2: Fundamentally Broken Effects (0-1.5/5)
- Night Vision (§4.1) — depends on noise, bloom, circular mask
- Silhouette (§4.2) — depends on backend Sobel
- Slit-scan shader rewrite (§4.3)
- Ghost preset fix (§4.4)
- Datamosh preset + backend wiring (§4.5)
- Trails preset fix (§4.6)
- Trap preset + strobe (§4.7)
- Ambient preset fix (§4.8)

### Batch 3: Shader Fixes (2-2.5/5)
- VHS shader cool shift + dropout + wider bands (§4.9)
- Neon bloom + chromatic aberration (§4.10)
- Thermal blur + bloom + resolution (§4.11)
- Feedback zoom + organic warp (§4.12)
- Screwed temporal drag + degradation (§4.13)
- Pixsort shader rewrite (§4.14)
- Halftone CMYK fix + hard edges (§4.15)
- Glitch blocks posterization + horizontal bias (§4.16)

### Batch 4: Polish
- Diff noise floor (§4.17)
- ASCII cell size (§4.18)
- Frontend/backend preset alignment audit (§3.2)
- End-to-end visual verification of all 18 effects

---

## 8. Testing Strategy

No automated tests for visual effects. Verification is manual:

1. For each effect, switch to it in the Logos studio view
2. Compare against the source characteristics document
3. Verify each of the 4-5 characteristics is visually present
4. Check that passthrough still works (effects don't bleed into "Clean" preset)
5. Check filter crossfade transitions are smooth
6. Check noise overlay performance (should not drop below 30fps)

---

## 9. Risk Assessment

| Risk | Mitigation |
|------|------------|
| Noise overlay performance | Pre-baked Math.random() ImageData at 240x135 is <0.1ms. Verified viable |
| Pixsort shader rewrite complexity | GLSL ES 2.0 supports vec3[12] arrays, nested constant-bound loops, variable-indexed swaps. 12 texture fetches + 132 comparisons verified within budget on RTX 3090. Use bubble sort approach |
| Bloom post-effect performance | 1/4 resolution temp canvas (480x270). brightness(0.3)+contrast(100)+blur(4px) in single drawImage. Verified viable at 60fps |
| Chromatic aberration performance (Neon) | Two extra drawImage calls per frame. Measure before/after FPS |
| Filter crossfade double-render cost | Only during 300ms transitions. Negligible overall |
