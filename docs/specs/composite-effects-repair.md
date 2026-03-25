# Composite Effects Repair — Design Specification

**Status**: Implemented
**Date**: 2026-03-25
**Scope**: CompositeCanvas, CameraHero, StudioDetailPane, compositePresets

## 1. Problem Statement

The composite and HLS rendering layers in Logos have six identified defects spanning dead code paths, non-functional UI controls, and architectural mismatches. Three are critical (user-facing features that produce no visible output), two are significant (behavioral regression under specific conditions), and one is a resource waste.

## 2. Defect Catalog

### 2.1 Warp Dead for All Presets (Critical)

**Location**: `CompositeCanvas.tsx:435,483`

Every preset has `trail.count >= 2` and `trail.opacity > 0`, so `trailActive` is always `true`. When trails are active, `drawMainFrame` is called with `skipWarp = true`. The warp configurations on 9 presets (Ghost, Trails, Screwed, VHS, Neon, Trap, Pixsort, Slit-scan, Feedback) are entirely dead.

**Root cause**: Animated warp + persistence = directional smearing. The disable was correct — persistence accumulates warped positions into motion blur that obliterates the scene. This is a first-principles raster graphics problem, not a bug in the implementation.

**Design constraint**: Warp cannot be naively re-enabled in the persistence path. The back buffer accumulates trail content via `destination-out` fade. Warped positions from successive ticks overlap and smear.

### 2.2 Effect Toggles Non-Functional for Non-Native Effects (Critical)

**Location**: `StudioDetailPane.tsx:104-116`, `CompositeCanvas.tsx:277-334`

`toggleEffect()` sets the boolean (e.g., `bandDisplacement: true`) but not the associated numeric parameters. `NO_EFFECTS` defaults have `bandChance: 0`, `bandMaxShift: 0`, `vignetteStrength: 0`, `syrupColor: "0, 0, 0"`. Result:

| Toggle | Behavior when activated on non-native preset |
|--------|----------------------------------------------|
| Scanlines | Works (no parameter dependency) |
| Glitch Bands | Silent no-op (`Math.random() < 0` = false) |
| Vignette | Invisible (strength 0) |
| Syrup | Invisible (black-on-black gradient) |

### 2.3 Overlay Drift Disabled by Filter Selection (By Design — No Fix)

**Location**: `CompositeCanvas.tsx:231,243-254`

When per-layer filter overrides are active, overlay drift snaps to static (0,0) positioning. This was a deliberate commit (5c4e16b6): filter overrides signal "composite mode" where spatial alignment matters. FX presets retain drift when no filter overrides are set. **This is correct behavior — no change needed.**

### 2.4 smoothSource Falls Through to FX Endpoint for Camera Source (Significant)

**Location**: `CameraHero.tsx:86`

```tsx
const smoothSource = compositeMode ? (effectUrl ?? "/api/studio/stream/fx") : undefined;
```

When source is "camera", `effectUrl` is `undefined`, so `smoothSource` becomes `/api/studio/stream/fx`. The CompositeCanvas smooth ring buffer fetches from the FX endpoint even though the user selected "Camera" — showing stale or unrelated GPU-processed frames as the overlay layer.

### 2.5 HLS Streams Invisibly in Composite-Only Mode (Minor)

**Location**: `CameraHero.tsx:107`

`<HlsPlayer enabled={smoothMode || compositeMode} />` — in composite-only mode (smoothMode=false, compositeMode=true), HLS initializes and streams segments at opacity 0. Decodes video nobody sees, consuming bandwidth and CPU.

### 2.6 Warp Configs on Presets Are Unreachable Spec (Informational)

9 presets declare warp configurations that never execute. These configurations represent design intent — they describe the spatial character of each effect — but are currently dead data.

## 3. Design Decisions

### 3.1 Warp Recovery: Pre-Warp Rendering Model

**Approach**: Render the warped main frame to a **separate scratch canvas**, then composite that result (as a flat image) onto the trail back buffer. The back buffer never sees the raw transform — only the already-rendered warped output.

**Pipeline change**:
```
Current (trails active):
  main frame → drawImage(backBuffer, 0, 0, w, h)  [skipWarp=true]

Proposed:
  main frame → drawMainFrame(scratchCanvas, warp)  [warp applied]
  scratchCanvas → drawImage(backBuffer, 0, 0, w, h)  [flat copy, no smear]
```

The scratch canvas already exists for drift operations. Reuse it for warp pre-rendering. After warp draws to scratch, copy the result to the back buffer as a flat image at (0,0). The back buffer accumulates flat frames — no position drift from warp, no smearing.

**Key insight**: The smearing problem occurs because warp draws each frame at a **different position on the back buffer**. By pre-rendering warp to scratch and copying the result at a fixed position, the back buffer sees a stable frame each tick.

**Cost**: One extra `drawImage` per frame when warp + trails are both active. At canvas resolution this is negligible.

**Risk**: Warp still draws a full frame each tick to scratch. If the warp transform includes scale > 1 (zoom), the edges of the warped frame extend beyond canvas bounds. When copied to back buffer, the visible portion changes per tick as pan/rotation shift. This creates a subtle "window into a moving scene" effect rather than "the scene itself moves" — which is actually the desired artistic result for persistence effects.

### 3.2 Effect Toggle Defaults: Render-Side Fallback

**Approach**: Apply sensible defaults in `drawPostEffects` when a boolean is `true` but its numeric parameter is zero/empty. This is simpler than modifying `toggleEffect` and ensures correctness regardless of how the state arrives.

**Default values** (derived from median of presets that use each effect):

| Parameter | Default | Derivation |
|-----------|---------|------------|
| `bandChance` | 0.25 | Median of 0.18, 0.2, 0.4, 0.5 |
| `bandMaxShift` | 20 | Midpoint of 12–40 range |
| `vignetteStrength` | 0.35 | Mode value across 16 presets |
| `syrupColor` | `"30, 15, 45"` | Midpoint between Screwed and Trap purples |

**Implementation**: Fallback at render time, not at toggle time. This avoids polluting the override state with synthetic parameters and keeps the toggle logic clean.

```tsx
// In drawPostEffects:
const bandChance = fx.bandChance || 0.25;
const bandMaxShift = fx.bandMaxShift || 20;
const vignetteStrength = fx.vignetteStrength || 0.35;
const syrupColor = fx.syrupColor === "0, 0, 0" ? "30, 15, 45" : fx.syrupColor;
```

### 3.3 smoothSource Camera Fallback

**Approach**: When source is "camera", don't set a smoothSource at all. The overlay layer should use the live ring's delayed frames (which it already supports — see `CompositeCanvas.tsx:229-235`).

```tsx
// CameraHero.tsx:86
const smoothSource = compositeMode && effectUrl ? effectUrl : undefined;
```

When `smoothSource` is undefined, CompositeCanvas falls back to delayed frames from the live ring buffer (`frameIdx - p.overlay.delayFrames`). This is the correct behavior — the overlay shows a delayed version of the same camera feed, not unrelated GPU-processed frames.

### 3.4 HLS Gating

**Approach**: Only enable HLS when `smoothMode` is true, not when composite-only.

```tsx
<HlsPlayer enabled={smoothMode} />
```

If HLS is later needed for composite+HLS dual mode, the user can toggle smoothMode on from the UI. Idle streaming at opacity 0 is pure waste.

## 4. Files Changed

| File | Changes |
|------|---------|
| `CompositeCanvas.tsx` | Pre-warp scratch canvas path; effect parameter defaults |
| `CameraHero.tsx` | smoothSource fix; HLS gating |

No changes to: `compositePresets.ts` (warp configs become live again), `compositeFilters.ts`, `effectSources.ts`, `GroundStudioContext.tsx`, `StudioDetailPane.tsx`.

## 5. Testing Strategy

Manual visual verification (no automated test for canvas rendering):

1. **Warp recovery**: Select Ghost preset → confirm slow pan/rotate visible. Select Screwed → confirm slice warp visible with trails persisting underneath.
2. **Effect toggles**: On Ghost preset (no native bands), toggle Glitch Bands → confirm visible horizontal displacement. Toggle Syrup → confirm purple gradient overlay.
3. **Camera source overlay**: Select Camera source, enable FX → confirm overlay shows delayed camera frames, not stale FX content.
4. **HLS gating**: Enable FX only (no HLS) → confirm no network requests to `/api/studio/hls/stream.m3u8`.
5. **Regression**: Verify Neon hue cycling, VHS head-switch noise, stutter/freeze, ping-pong trail persistence all still function.

## 6. Non-Goals

- Redesigning the persistence model (destination-out fade is correct)
- Adding CSS transitions for filter changes (canvas context.filter doesn't support transitions)
- Changing overlay drift behavior with filter overrides (deliberate design)
- Adding new effects or presets
- Modifying the backend compositor or GPU shader pipeline
