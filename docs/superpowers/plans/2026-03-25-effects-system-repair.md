# Effects System Repair — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair all 18 composite/HLS effects to match their source characteristics, add systemic infrastructure (noise, bloom, strobe, filter crossfade), and align frontend/backend presets.

**Architecture:** Two-layer system — backend GLSL shaders in GStreamer pipeline (uniform-based passthrough, no rebuild), frontend Canvas 2D compositing (trails, warp, stutter, post-effects). Changes are additive: new engines added to CompositeCanvas.tsx, new fields to CompositePreset type, shader files edited in-place.

**Tech Stack:** TypeScript/React (frontend), GLSL ES 2.0 (shaders), Python (backend presets). No automated tests — visual effects verified manually.

**Spec:** `docs/superpowers/specs/2026-03-25-effects-system-repair.md`
**Source Authority:** `docs/research/visual-effects-source-characteristics.md`

---

## Batch 1: Systemic Infrastructure

All infrastructure goes into `CompositeCanvas.tsx` and `compositePresets.ts`. Must be done sequentially — each task builds on the previous.

### Task 1: Add new preset fields and noise overlay type

**Files:**
- Modify: `hapax-logos/src/components/studio/compositePresets.ts:1-77`

- [ ] **Step 1: Add new optional fields to CompositePreset interface**

Add after the `overlays` field (line 63):

```typescript
  noise?: {
    enabled: boolean;
    intensity: number;     // 0-1, overlay alpha
    animated: boolean;     // regenerate grain every 2-3 frames (scintillation)
  };

  bloom?: {
    enabled: boolean;
    threshold: number;     // 0-1, brightness cutoff (maps to CSS brightness() param)
    radius: number;        // blur radius in px (at 1/4 resolution)
    alpha: number;         // composite opacity
  };

  strobe?: {
    chance: number;        // per-tick probability (0-0.1)
    color: string;         // rgba() string
    duration: number;      // ticks
  };

  circularMask?: boolean;  // hard circular clip (Night Vision tube viewport)
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd hapax-logos && npx tsc --noEmit`
Expected: No errors (new fields are optional, existing presets don't need them yet)

- [ ] **Step 3: Commit**

```bash
git add hapax-logos/src/components/studio/compositePresets.ts
git commit -m "feat(effects): add noise, bloom, strobe, circularMask preset fields"
```

---

### Task 2: Add noise overlay engine to CompositeCanvas

**Files:**
- Modify: `hapax-logos/src/components/studio/CompositeCanvas.tsx`

- [ ] **Step 1: Add noise canvas setup inside the useEffect (after scratchCanvas init, around line 106)**

Add after the `ensureBackBuffer` function:

```typescript
    // --- Noise overlay (pre-baked grain at 1/8 resolution) ---
    const noiseW = 240;
    const noiseH = 135;
    const noiseCanvas = document.createElement("canvas");
    noiseCanvas.width = noiseW;
    noiseCanvas.height = noiseH;
    const noiseCtx = noiseCanvas.getContext("2d")!;
    const noiseImageData = noiseCtx.createImageData(noiseW, noiseH);
    let noiseGenerated = false;
    let noiseTickCounter = 0;

    const regenerateNoise = () => {
      const d = noiseImageData.data;
      for (let i = 0; i < d.length; i += 4) {
        const v = Math.random() * 255;
        d[i] = d[i + 1] = d[i + 2] = v;
        d[i + 3] = 255;
      }
      noiseCtx.putImageData(noiseImageData, 0, 0);
      noiseGenerated = true;
    };
```

- [ ] **Step 2: Add noise drawing function after drawPostEffects**

```typescript
    /** Draw noise grain overlay if preset has noise config. */
    const drawNoise = (w: number, h: number) => {
      const noise = presetRef.current.noise;
      if (!noise?.enabled) return;

      // Static noise: generate once. Animated: regenerate every 3 ticks.
      if (!noiseGenerated || (noise.animated && ++noiseTickCounter % 3 === 0)) {
        regenerateNoise();
      }

      ctx.save();
      ctx.imageSmoothingEnabled = false; // nearest-neighbor = crunchy grain
      ctx.globalAlpha = noise.intensity;
      ctx.globalCompositeOperation = "overlay";
      ctx.drawImage(noiseCanvas, 0, 0, w, h);
      ctx.restore();
    };
```

- [ ] **Step 3: Call drawNoise at end of both render paths**

In the trail-active render path (after `drawOverlayAndEffects` / `drawPostEffects`, around line 518), add:
```typescript
        drawNoise(w, h);
```

In the no-trails render path (after `drawOverlayAndEffects`, around line 524), add:
```typescript
        drawNoise(w, h);
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd hapax-logos && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add hapax-logos/src/components/studio/CompositeCanvas.tsx
git commit -m "feat(effects): add noise overlay engine to CompositeCanvas"
```

---

### Task 3: Add bloom post-effect engine

**Files:**
- Modify: `hapax-logos/src/components/studio/CompositeCanvas.tsx`

- [ ] **Step 1: Add bloom canvas setup inside the useEffect (after noise setup)**

```typescript
    // --- Bloom post-effect (1/4 resolution bright-pass + blur) ---
    let bloomCanvas: HTMLCanvasElement | null = null;
    let bloomCtx: CanvasRenderingContext2D | null = null;

    const ensureBloomCanvas = (w: number, h: number) => {
      const bw = Math.ceil(w / 4);
      const bh = Math.ceil(h / 4);
      if (bloomCanvas && bloomCanvas.width === bw && bloomCanvas.height === bh) return;
      bloomCanvas = document.createElement("canvas");
      bloomCanvas.width = bw;
      bloomCanvas.height = bh;
      bloomCtx = bloomCanvas.getContext("2d");
    };
```

- [ ] **Step 2: Add bloom drawing function**

```typescript
    /** Draw bloom glow: extract bright pixels, blur at 1/4 res, composite with lighter. */
    const drawBloom = (w: number, h: number) => {
      const bloom = presetRef.current.bloom;
      if (!bloom?.enabled || !canvas) return;

      ensureBloomCanvas(w, h);
      if (!bloomCtx || !bloomCanvas) return;

      // brightness(X) where X < 0.5 shifts everything dark, contrast(100) clips to binary.
      // Lower threshold value = more pixels pass through = wider bloom.
      const brightPass = 0.5 - bloom.threshold * 0.4; // maps 0-1 to 0.5-0.1
      bloomCtx.filter = `brightness(${brightPass}) contrast(100) blur(${bloom.radius / 4}px)`;
      bloomCtx.drawImage(canvas, 0, 0, bloomCanvas.width, bloomCanvas.height);
      bloomCtx.filter = "none";

      // Composite back at full resolution
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = bloom.alpha;
      ctx.drawImage(bloomCanvas, 0, 0, w, h);
      ctx.restore();
    };
```

- [ ] **Step 3: Call drawBloom after drawNoise in both render paths**

After each `drawNoise(w, h)` call, add:
```typescript
        drawBloom(w, h);
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd hapax-logos && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add hapax-logos/src/components/studio/CompositeCanvas.tsx
git commit -m "feat(effects): add bloom post-effect engine (1/4 res bright-pass + blur)"
```

---

### Task 4: Add strobe engine and circular mask

**Files:**
- Modify: `hapax-logos/src/components/studio/CompositeCanvas.tsx`

- [ ] **Step 1: Add strobe state inside useEffect (after bloom setup)**

```typescript
    // --- Strobe engine ---
    let strobeTicks = 0;
```

- [ ] **Step 2: Add strobe drawing function**

```typescript
    /** Flash full-frame strobe if preset has strobe config. */
    const drawStrobe = (w: number, h: number) => {
      const strobe = presetRef.current.strobe;
      if (!strobe) return;

      if (strobeTicks > 0) {
        strobeTicks--;
        ctx.save();
        ctx.fillStyle = strobe.color;
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      } else if (Math.random() < strobe.chance) {
        strobeTicks = strobe.duration;
      }
    };
```

- [ ] **Step 3: Add circular mask function**

```typescript
    /** Apply hard circular clip for Night Vision tube viewport. */
    const applyCircularMask = (w: number, h: number) => {
      if (!presetRef.current.circularMask) return;
      const radius = Math.min(w, h) * 0.42;
      ctx.save();
      ctx.globalCompositeOperation = "destination-in";
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    };
```

- [ ] **Step 4: Call strobe and circular mask in render paths**

After `drawBloom(w, h)` in both render paths, add:
```typescript
        drawStrobe(w, h);
        applyCircularMask(w, h);
```

- [ ] **Step 5: Verify TypeScript compiles and commit**

```bash
cd hapax-logos && npx tsc --noEmit
git add hapax-logos/src/components/studio/CompositeCanvas.tsx
git commit -m "feat(effects): add strobe engine and circular mask support"
```

---

### Task 5: Add filter crossfade and fix overlay drift

**Files:**
- Modify: `hapax-logos/src/components/studio/CompositeCanvas.tsx`

- [ ] **Step 1: Add filter transition state inside useEffect (after strobe state)**

```typescript
    // --- Filter crossfade ---
    let prevLiveFilter = liveFilter;
    let prevSmoothFilter = smoothFilter;
    let filterTransitionStart = 0;
    const FILTER_TRANSITION_MS = 300;
```

- [ ] **Step 2: Add filter transition detection at start of render()**

Inside `render()`, after `tick++; hueAccum += 4;`, add:

```typescript
      // Detect filter changes for crossfade
      const currentLiveFilter = liveFilterRef.current;
      const currentSmoothFilter = smoothFilterRef.current;
      if (currentLiveFilter !== prevLiveFilter || currentSmoothFilter !== prevSmoothFilter) {
        // Only start transition if we had a previous filter (not initial mount)
        if (prevLiveFilter !== undefined || prevSmoothFilter !== undefined) {
          filterTransitionStart = performance.now();
        }
        prevLiveFilter = currentLiveFilter;
        prevSmoothFilter = currentSmoothFilter;
      }
```

- [ ] **Step 3: Fix overlay drift — remove hasFilterOverrides condition**

In `drawOverlayAndEffects`, find the block around line 243 that checks `hasFilterOverrides`:

Replace:
```typescript
          if (hasFilterOverrides) {
            ctx.drawImage(delayed, 0, 0, w, h);
          } else {
            const dt = tick * 0.03;
            ctx.drawImage(
              delayed,
              Math.sin(dt) * 5,
              p.overlay.driftY + Math.sin(dt * 0.6) * 4,
              w,
              h,
            );
          }
```

With:
```typescript
          const dt = tick * 0.03;
          ctx.drawImage(
            delayed,
            Math.sin(dt) * 5,
            p.overlay.driftY + Math.sin(dt * 0.6) * 4,
            w,
            h,
          );
```

Also remove the `hasFilterOverrides` variable declaration (`const hasFilterOverrides = liveFilterRef.current || smoothFilterRef.current;`).

- [ ] **Step 4: Verify and commit**

```bash
cd hapax-logos && npx tsc --noEmit
git add hapax-logos/src/components/studio/CompositeCanvas.tsx
git commit -m "feat(effects): add filter crossfade, fix overlay drift always-on"
```

---

### Task 6: Add organic warp to drawMainFrame

**Files:**
- Modify: `hapax-logos/src/components/studio/CompositeCanvas.tsx`

- [ ] **Step 1: Replace sinusoidal warp with multi-harmonic organic motion**

In `drawMainFrame`, for the slice warp path (line 156 area) and simple warp path (line 192 area), replace the pan/rotate calculations.

Current (both paths):
```typescript
        const t = tick * 0.04;
        const panX = Math.sin(t) * warpCfg.panX;
        const panY = Math.sin(t * 0.7) * warpCfg.panY;
        const rot = Math.sin(t * 0.5) * warpCfg.rotate;
        const scale = warpCfg.zoom + Math.sin(t * 0.2) * warpCfg.zoomBreath;
```

Replace with:
```typescript
        const t = tick * 0.04;
        // Multi-harmonic organic motion — golden ratio frequencies prevent visible repetition
        const panX = (Math.sin(t) * 0.5 + Math.sin(t * 0.618) * 0.3 + Math.sin(t * 0.237) * 0.2) * warpCfg.panX;
        const panY = (Math.sin(t * 0.7) * 0.5 + Math.sin(t * 0.432) * 0.3 + Math.sin(t * 0.166) * 0.2) * warpCfg.panY;
        const rot = (Math.sin(t * 0.5) * 0.6 + Math.sin(t * 0.309) * 0.4) * warpCfg.rotate;
        const scale = warpCfg.zoom + (Math.sin(t * 0.2) * 0.6 + Math.sin(t * 0.124) * 0.4) * warpCfg.zoomBreath;
```

Apply this change in BOTH the slice warp block AND the simple warp block.

- [ ] **Step 2: Verify and commit**

```bash
cd hapax-logos && npx tsc --noEmit
git add hapax-logos/src/components/studio/CompositeCanvas.tsx
git commit -m "feat(effects): organic multi-harmonic warp animation"
```

---

## Batch 2: Fundamentally Broken Effects (0-1.5/5)

These tasks update preset values in `compositePresets.ts` and backend presets in `studio_effects.py`. Frontend preset changes can be batched into one commit; backend changes into another.

### Task 7: Fix all broken frontend presets (Night Vision, Silhouette, Ghost, Datamosh, Trails, Trap, Ambient, Slit-scan)

**Files:**
- Modify: `hapax-logos/src/components/studio/compositePresets.ts:79-583`

- [ ] **Step 1: Update Ghost preset (line ~80)**

Replace the Ghost preset object:
```typescript
  {
    name: "Ghost",
    description: "Transparent echo — fading dim copies",
    colorFilter: "saturate(0.85) brightness(0.9)",
    trail: {
      filter: "saturate(0.7) brightness(0.6) blur(2px) hue-rotate(5deg)",
      blendMode: "lighter",
      opacity: 0.45,
      count: 5,
      driftX: 3,
      driftY: 4,
    },
    overlay: {
      delayFrames: 12,
      filter: "saturate(0.5) brightness(0.5) blur(3px)",
      alpha: 0.15,
      blendMode: "lighter",
      driftY: 16,
    },
    warp: {
      panX: 4,
      panY: 3,
      rotate: 0.005,
      zoom: 1.01,
      zoomBreath: 0.005,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.35 },
    overlays: [],
  },
```

- [ ] **Step 2: Update Trails preset (line ~111)**

Replace the Trails preset object:
```typescript
  {
    name: "Trails",
    description: "Bright additive motion trails",
    colorFilter: "saturate(1.4) brightness(1.15)",
    trail: {
      filter: "saturate(1.8) brightness(1.3)",
      blendMode: "lighter",
      opacity: 0.75,
      count: 12,
      driftX: 2,
      driftY: 3,
    },
    overlay: {
      delayFrames: 4,
      filter: "saturate(1.5) brightness(1.2)",
      alpha: 0.2,
      blendMode: "lighter",
      driftY: 5,
    },
    warp: {
      panX: 3,
      panY: 2,
      rotate: 0.004,
      zoom: 1.01,
      zoomBreath: 0.005,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS },
    overlays: [],
  },
```

- [ ] **Step 3: Update Screwed preset (line ~142)**

Replace the Screwed preset object:
```typescript
  {
    name: "Screwed",
    description: "Houston syrup — dim, heavy, sinking",
    colorFilter:
      "saturate(0.5) sepia(0.5) hue-rotate(260deg) contrast(1.0) brightness(0.85) blur(2px)",
    trail: {
      filter: "saturate(0.25) brightness(0.5) sepia(0.6) hue-rotate(270deg) blur(3px)",
      blendMode: "lighter",
      opacity: 0.55,
      count: 5,
      driftX: 0,
      driftY: 6,
    },
    overlay: {
      delayFrames: 10,
      filter:
        "saturate(0.4) sepia(0.6) hue-rotate(280deg) brightness(1.2)",
      alpha: 0.45,
      blendMode: "lighter",
      driftY: 8,
    },
    warp: {
      panX: 20,
      panY: 22,
      rotate: 0.025,
      zoom: 1.06,
      zoomBreath: 0.04,
      sliceCount: 24,
      sliceAmplitude: 6,
    },
    stutter: {
      checkInterval: 15,
      freezeChance: 0.2,
      freezeMin: 8,
      freezeMax: 20,
      replayFrames: 2,
    },
    noise: { enabled: true, intensity: 0.08, animated: false },
    effects: {
      scanlines: true,
      bandDisplacement: true,
      bandChance: 0.18,
      bandMaxShift: 15,
      vignette: true,
      vignetteStrength: 0.3,
      syrupGradient: true,
      syrupColor: "60, 20, 80",
    },
    overlays: [],
    livePullIntervalMs: 300,
  },
```

- [ ] **Step 4: Update Datamosh preset (line ~192)**

Replace the Datamosh preset object:
```typescript
  {
    name: "Datamosh",
    description: "Glitch — codec prediction artifacts",
    colorFilter: "saturate(0.8) contrast(1.4) brightness(1.1)",
    trail: {
      filter: "saturate(0.9) contrast(1.3) brightness(1.2)",
      blendMode: "difference",
      opacity: 0.9,
      count: 6,
      driftX: 12,
      driftY: 10,
    },
    overlay: {
      delayFrames: 6,
      filter: "saturate(0.7) contrast(1.5) brightness(1.3)",
      alpha: 0.6,
      blendMode: "difference",
      driftY: 3,
    },
    stutter: {
      checkInterval: 8,
      freezeChance: 0.4,
      freezeMin: 2,
      freezeMax: 6,
      replayFrames: 3,
    },
    effects: {
      ...NO_EFFECTS,
      bandDisplacement: true,
      bandChance: 0.5,
      bandMaxShift: 40,
      scanlines: true,
    },
    overlays: [],
  },
```

- [ ] **Step 5: Update Trap preset (line ~305)**

Replace the Trap preset object:
```typescript
  {
    name: "Trap",
    description: "Dark, underground, oppressive",
    colorFilter:
      "saturate(0.2) sepia(0.4) hue-rotate(160deg) contrast(1.3) brightness(0.65)",
    trail: {
      filter: "saturate(0.15) sepia(0.5) hue-rotate(180deg) brightness(0.4)",
      blendMode: "multiply",
      opacity: 0.55,
      count: 4,
      driftX: 1,
      driftY: 4,
    },
    overlay: {
      delayFrames: 12,
      filter: "saturate(0.2) sepia(0.4) hue-rotate(200deg) brightness(0.5)",
      alpha: 0.25,
      blendMode: "multiply",
      driftY: 2,
    },
    warp: {
      panX: 1,
      panY: 1,
      rotate: 0.002,
      zoom: 1.005,
      zoomBreath: 0.003,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    noise: { enabled: true, intensity: 0.12, animated: false },
    strobe: { chance: 0.03, color: "rgba(255, 40, 40, 0.3)", duration: 2 },
    effects: {
      ...NO_EFFECTS,
      scanlines: true,
      vignette: true,
      vignetteStrength: 0.55,
      syrupGradient: true,
      syrupColor: "10, 5, 15",
    },
    overlays: [],
  },
```

- [ ] **Step 6: Update NightVision preset (line ~365)**

Replace the NightVision preset object:
```typescript
  {
    name: "NightVision",
    description: "Green phosphor mono — IR-optimized surveillance",
    colorFilter: "saturate(0) sepia(1) hue-rotate(70deg) saturate(3) brightness(1.3) contrast(1.4)",
    trail: {
      filter: "saturate(0) brightness(0.7)",
      blendMode: "lighter",
      opacity: 0.2,
      count: 3,
      driftX: 0,
      driftY: 0,
    },
    noise: { enabled: true, intensity: 0.15, animated: true },
    bloom: { enabled: true, threshold: 0.7, radius: 16, alpha: 0.4 },
    circularMask: true,
    effects: {
      ...NO_EFFECTS,
      scanlines: true,
    },
    overlays: [],
  },
```

- [ ] **Step 7: Update Silhouette preset (line ~387)**

Replace the Silhouette preset object:
```typescript
  {
    name: "Silhouette",
    description: "High-contrast IR-only look — shapes over detail",
    colorFilter: "saturate(0) contrast(5) brightness(0.8) invert(1)",
    trail: {
      filter: "saturate(0) contrast(3) brightness(0.5) invert(1)",
      blendMode: "source-over",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
```

- [ ] **Step 8: Update Ambient preset (line ~553)**

Replace the Ambient preset object:
```typescript
  {
    name: "Ambient",
    description: "Very dim, minimal trails — atmospheric presence",
    colorFilter: "saturate(0.3) brightness(0.4) contrast(0.8) blur(8px)",
    trail: {
      filter: "saturate(0.2) brightness(0.3) blur(12px)",
      blendMode: "lighter",
      opacity: 0.15,
      count: 3,
      driftX: 0,
      driftY: 1,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.6 },
    overlays: [],
    livePullIntervalMs: 500,
  },
```

- [ ] **Step 9: Update Feedback preset (line ~464)**

Replace the Feedback preset object:
```typescript
  {
    name: "Feedback",
    description: "Deep recursion — rainbow cycling glow",
    colorFilter: "saturate(3.0) contrast(1.4) brightness(1.3)",
    trail: {
      filter: "saturate(3.0) contrast(1.1) brightness(1.4)",
      blendMode: "lighter",
      opacity: 0.85,
      count: 12,
      driftX: 2,
      driftY: 3,
    },
    overlay: {
      delayFrames: 6,
      filter: "saturate(3.0) contrast(1.3) brightness(1.8)",
      alpha: 0.35,
      blendMode: "lighter",
      driftY: 4,
    },
    warp: {
      panX: 4,
      panY: 3,
      rotate: 0.012,
      zoom: 1.04,
      zoomBreath: 0.02,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.45 },
    overlays: [],
  },
```

- [ ] **Step 10: Update Neon preset (line ~274)**

Replace the Neon preset object:
```typescript
  {
    name: "Neon",
    description: "Color-cycling glow bloom",
    colorFilter: "saturate(2.5) contrast(1.8) brightness(1.1)",
    trail: {
      filter: "saturate(3) contrast(1.3) brightness(1.6)",
      blendMode: "lighter",
      opacity: 0.6,
      count: 8,
      driftX: 3,
      driftY: 4,
    },
    overlay: {
      delayFrames: 4,
      filter: "saturate(3) contrast(1.4) brightness(1.8)",
      alpha: 0.45,
      blendMode: "lighter",
      driftY: 3,
    },
    warp: {
      panX: 4,
      panY: 3,
      rotate: 0.008,
      zoom: 1.02,
      zoomBreath: 0.012,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    bloom: { enabled: true, threshold: 0.6, radius: 12, alpha: 0.5 },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.5 },
    overlays: [],
  },
```

- [ ] **Step 11: Update Slit-scan preset (line ~442)**

Replace the Slit-scan preset object:
```typescript
  {
    name: "Slit-scan",
    description: "Temporal vertical displacement smear",
    colorFilter: "saturate(0.8) contrast(1.2) brightness(1.0)",
    trail: {
      filter: "saturate(0.7) brightness(0.9)",
      blendMode: "source-over",
      opacity: 0.5,
      count: 8,
      driftX: 0,
      driftY: 10,
    },
    overlay: {
      delayFrames: 8,
      filter: "saturate(0.6) brightness(0.8)",
      alpha: 0.3,
      blendMode: "source-over",
      driftY: 14,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.25 },
    overlays: [],
  },
```

- [ ] **Step 12: Update Diff preset — add noise**

Find the Diff preset (line ~343) and add the noise field:
```typescript
    noise: { enabled: true, intensity: 0.03, animated: true },
```

- [ ] **Step 13: Update VHS preset — add noise**

Find the VHS preset (line ~227) and add the noise field:
```typescript
    noise: { enabled: true, intensity: 0.06, animated: false },
```

- [ ] **Step 14: Verify and commit**

```bash
cd hapax-logos && npx tsc --noEmit
git add hapax-logos/src/components/studio/compositePresets.ts
git commit -m "feat(effects): update all broken frontend presets to match source characteristics"
```

---

### Task 8: Update Trails fade rate in CompositeCanvas

**Files:**
- Modify: `hapax-logos/src/components/studio/CompositeCanvas.tsx:347-371`

- [ ] **Step 1: Reduce lighter baseFade for longer trail persistence**

In `computeTrailAlphas`, change the baseFade for `lighter` mode:

```typescript
      const baseFade = trail.blendMode === "lighter" ? 0.03
```

(Changed from 0.05 to 0.03)

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/studio/CompositeCanvas.tsx
git commit -m "fix(effects): reduce lighter trail fade rate for longer persistence"
```

---

## Batch 3: Shader Fixes (2-2.5/5)

These are independent GLSL shader edits. Each shader is its own file — can be worked in parallel by subagents.

### Task 9: Fix VHS shader — cool palette, dropout, wider bands

**Files:**
- Modify: `agents/shaders/vhs.frag`

- [ ] **Step 1: Change warm sepia to cool cyan shift**

Replace lines 71-74:
```glsl
    // --- Sepia warmth ---
    float gray = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 sepia = vec3(gray * 1.15, gray * 1.0, gray * 0.85);
    color.rgb = mix(color.rgb, sepia, 0.35);
```

With:
```glsl
    // --- Cool blue/cyan VHS color cast ---
    float gray = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    vec3 cool = vec3(gray * 0.85, gray * 0.95, gray * 1.1);
    color.rgb = mix(color.rgb, cool, 0.3);
```

- [ ] **Step 2: Widen noise band and add second band**

Replace lines 83-90:
```glsl
    // --- Scrolling noise band ---
    float bandDist = abs(uv.y - u_noise_band_y);
    float bandWidth = 0.012;
    if (bandDist < bandWidth) {
        float noise = hash(uv * u_time * 100.0);
        float bandIntensity = 1.0 - (bandDist / bandWidth);
        color.rgb = mix(color.rgb, vec3(noise), 0.6 * bandIntensity);
    }
```

With:
```glsl
    // --- Scrolling noise bands (tracking misalignment) ---
    float bandWidth = 0.04;
    // Primary band
    float bandDist1 = abs(uv.y - u_noise_band_y);
    if (bandDist1 < bandWidth) {
        float noise = hash(uv * u_time * 100.0);
        float bandIntensity = 1.0 - (bandDist1 / bandWidth);
        color.rgb = mix(color.rgb, vec3(noise), 0.5 * bandIntensity);
        // Horizontal displacement within band
        float disp = (hash(vec2(floor(uv.y * u_height), u_time * 2.0)) - 0.5) * 6.0 * px;
        color.rgb = mix(color.rgb, texture2D(tex, vec2(uv.x + disp, uv.y)).rgb, 0.4 * bandIntensity);
    }
    // Secondary band at different speed
    float band2_y = fract(u_noise_band_y * 0.7 + 0.4);
    float bandDist2 = abs(uv.y - band2_y);
    if (bandDist2 < bandWidth * 0.6) {
        float noise2 = hash(uv * u_time * 80.0 + vec2(1.0, 0.0));
        float bandIntensity2 = 1.0 - (bandDist2 / (bandWidth * 0.6));
        color.rgb = mix(color.rgb, vec3(noise2), 0.3 * bandIntensity2);
    }
```

- [ ] **Step 3: Add dropout (white horizontal streaks) and per-line jitter**

Before the scanline section (before `// --- Gaussian-profile scanlines ---`), add:

```glsl
    // --- Oxide dropout (random white horizontal streaks) ---
    float dropHash = hash(vec2(floor(uv.y * u_height), floor(u_time * 8.0)));
    if (dropHash < 0.003) {
        color.rgb = mix(color.rgb, vec3(1.0), 0.8);
    }

    // --- Per-line luminance instability ---
    float lineJitter = (hash(vec2(floor(uv.y * u_height * 0.5), u_time * 3.0)) - 0.5) * 0.03;
    color.rgb += lineJitter;
```

- [ ] **Step 4: Commit**

```bash
git add agents/shaders/vhs.frag
git commit -m "fix(effects): VHS cool palette, wider tracking bands, dropout, line jitter"
```

---

### Task 10: Fix thermal shader — remove Sobel, add bloom, reduce resolution

**Files:**
- Modify: `agents/shaders/thermal.frag`

- [ ] **Step 1: Add UV quantization for low-res thermal look (after passthrough check)**

After line 37 (`return;`), add:
```glsl
    // Reduce effective resolution to ~480x270 (thermal sensor simulation)
    vec2 quantRes = vec2(u_width, u_height) * 0.25;
    uv = floor(uv * quantRes) / quantRes;
```

- [ ] **Step 2: Replace cross blur with 5x5 Gaussian**

Replace lines 41-49 (the luminance + blur section):
```glsl
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // --- Luminance with slight temporal smoothing (sensor lag) ---
    float lum = dot(texture2D(tex, uv).rgb, vec3(0.299, 0.587, 0.114));

    // Slight blur to simulate lower thermal sensor resolution
    float lumL = dot(texture2D(tex, uv + vec2(-texel.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lumR = dot(texture2D(tex, uv + vec2( texel.x, 0.0)).rgb, vec3(0.299, 0.587, 0.114));
    float lumU = dot(texture2D(tex, uv + vec2(0.0,  texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    float lumD = dot(texture2D(tex, uv + vec2(0.0, -texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    lum = (lum * 0.4 + (lumL + lumR + lumU + lumD) * 0.15);
```

With:
```glsl
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // --- 5x5 Gaussian blur (thermal sensor resolution simulation) ---
    float lum = 0.0;
    float totalWeight = 0.0;
    for (float dy = -2.0; dy <= 2.0; dy += 1.0) {
        for (float dx = -2.0; dx <= 2.0; dx += 1.0) {
            float w = exp(-(dx*dx + dy*dy) / 4.5);
            vec2 sampleUV = uv + vec2(dx, dy) * texel * 2.0;
            lum += dot(texture2D(tex, sampleUV).rgb, vec3(0.299, 0.587, 0.114)) * w;
            totalWeight += w;
        }
    }
    lum = lum / totalWeight;
```

- [ ] **Step 3: Replace Sobel edge glow with hot-source bloom**

Replace lines 51-68 (Sobel detection + edge glow):
```glsl
    // --- Sobel edge detection ---
    float tl = dot(texture2D(tex, uv + vec2(-texel.x,  texel.y)).rgb, vec3(0.299, 0.587, 0.114));
    ...
    float edge = sqrt(gx * gx + gy * gy);

    // --- Palette mapping with shift ---
    float palIdx = fract(lum + u_palette_shift);
    vec3 color = thermal_palette(palIdx);

    // --- Edge glow (warm white/yellow at edges like heat radiation) ---
    color += edge * u_edge_glow * 2.0 * vec3(1.0, 0.85, 0.3);
```

With:
```glsl
    // --- Palette mapping with shift ---
    float palIdx = fract(lum + u_palette_shift);
    vec3 color = thermal_palette(palIdx);

    // --- Hot-source bloom (bright regions glow outward) ---
    float bloom = smoothstep(0.7, 1.0, lum) * u_edge_glow * 0.4;
    color += bloom * vec3(1.0, 0.9, 0.7);
```

- [ ] **Step 4: Commit**

```bash
git add agents/shaders/thermal.frag
git commit -m "fix(effects): thermal low-res UV quantization, 5x5 blur, bloom replaces Sobel"
```

---

### Task 11: Fix halftone shader — CMYK channels, hard edges

**Files:**
- Modify: `agents/shaders/halftone.frag`

- [ ] **Step 1: Replace smoothstep with step in halftone_dot**

In the `halftone_dot` function, replace line 24:
```glsl
    return smoothstep(radius + 0.02, radius - 0.02, dist);
```
With:
```glsl
    return step(dist, radius);
```

- [ ] **Step 2: Fix CMYK subtractive color math**

Replace lines 64-69:
```glsl
        // Subtractive color: start white, subtract ink layers
        vec3 color = vec3(1.0);
        color -= vec3(0.0, c_dot * 0.7, c_dot);        // cyan
        color -= vec3(m_dot, 0.0, m_dot * 0.3);        // magenta
        color -= vec3(y_dot * 0.1, y_dot * 0.1, y_dot); // yellow
        color -= vec3(k_dot);                           // black
```

With:
```glsl
        // Subtractive color: start white, subtract ink layers
        // Cyan absorbs Red, Magenta absorbs Green, Yellow absorbs Blue
        vec3 color = vec3(1.0);
        color.r -= c_dot;                                // cyan subtracts red
        color.g -= m_dot;                                // magenta subtracts green
        color.b -= y_dot;                                // yellow subtracts blue
        color -= vec3(k_dot);                            // black subtracts all
```

- [ ] **Step 3: Commit**

```bash
git add agents/shaders/halftone.frag
git commit -m "fix(effects): halftone correct CMYK channels, hard dot edges via step()"
```

---

### Task 12: Fix glitch_blocks shader — posterization, horizontal bias, data pattern

**Files:**
- Modify: `agents/shaders/glitch_blocks.frag`

- [ ] **Step 1: Make displacement primarily horizontal**

Replace lines 46-48:
```glsl
            float shiftX = (blockHash(blockID, timeSlot + 1.0) - 0.5) * 60.0 / u_width;
            float shiftY = (blockHash(blockID, timeSlot + 2.0) - 0.5) * 30.0 / u_height;
            vec2 displaced = uv + vec2(shiftX, shiftY) * u_intensity;
```

With:
```glsl
            float shiftX = (blockHash(blockID, timeSlot + 1.0) - 0.5) * 60.0 / u_width;
            float shiftY = (blockHash(blockID, timeSlot + 2.0) - 0.5) * 6.0 / u_height;
            vec2 displaced = uv + vec2(shiftX, shiftY) * u_intensity;
```

- [ ] **Step 2: Add posterization to brightness corruption**

Replace lines 57-62 (brightness corruption block):
```glsl
        } else if (effectType < 0.7) {
            // Brightness corruption: wrong exposure
            vec4 color = texture2D(tex, uv);
            float bright = blockHash(blockID, timeSlot + 4.0) * 2.0;
            color.rgb *= bright;
            gl_FragColor = clamp(color, 0.0, 1.0);
```

With:
```glsl
        } else if (effectType < 0.55) {
            // Brightness corruption + posterization
            vec4 color = texture2D(tex, uv);
            float bright = blockHash(blockID, timeSlot + 4.0) * 2.0;
            color.rgb *= bright;
            // Quantize to 4 levels per channel (JPEG compression artifact)
            color.rgb = floor(color.rgb * 4.0) / 4.0;
            gl_FragColor = clamp(color, 0.0, 1.0);
```

- [ ] **Step 3: Add data pattern corruption type**

After the dead pixel block (after line 78), add a new corruption type by adjusting the thresholds:

Replace the dead pixel block (lines 75-78):
```glsl
        } else {
            // Solid block (dead pixel block)
            float v = blockHash(blockID, timeSlot + 6.0);
            gl_FragColor = vec4(vec3(v * 0.3), 1.0);
```

With:
```glsl
        } else if (effectType < 0.9) {
            // Solid block (dead pixel block)
            float v = blockHash(blockID, timeSlot + 6.0);
            gl_FragColor = vec4(vec3(v * 0.3), 1.0);

        } else {
            // Data pattern bleed — repeating gradient showing raw data structure
            vec2 pixel = gl_FragCoord.xy;
            float pattern = mod(pixel.x + pixel.y * 3.0, 8.0) / 8.0;
            float patternR = mod(pixel.x * 2.0 + pixel.y, 6.0) / 6.0;
            gl_FragColor = vec4(pattern, patternR * 0.7, pattern * 0.5, 1.0);
```

- [ ] **Step 4: Commit**

```bash
git add agents/shaders/glitch_blocks.frag
git commit -m "fix(effects): glitch blocks horizontal bias, posterization, data pattern bleed"
```

---

### Task 13: Fix slitscan shader — stronger displacement, banding, convergence

**Files:**
- Modify: `agents/shaders/slitscan.frag`

- [ ] **Step 1: Add scan_pos quantization for visible temporal banding**

After the scan_pos calculation (after line 38), add:
```glsl
    // Quantize to 24 discrete temporal bands for visible interlace artifacts
    scan_pos = floor(scan_pos * 24.0) / 24.0;
```

- [ ] **Step 2: Increase displacement and add center convergence**

Replace lines 43-47:
```glsl
    float phase = u_time * u_scan_speed;
    float displacement = scan_pos * scan_pos * 0.15;

    // Scrolling wave creates the continuously moving slit effect
    float wave = sin(phase + scan_pos * 6.2832) * 0.5 + 0.5;
    displacement *= (0.5 + wave * 0.5);
```

With:
```glsl
    float phase = u_time * u_scan_speed;
    float displacement = scan_pos * scan_pos * 0.4;

    // Scrolling wave creates the continuously moving slit effect
    float wave = sin(phase + scan_pos * 6.2832) * 0.5 + 0.5;
    displacement *= (0.5 + wave * 0.5);

    // Center convergence — edges pull toward center (tunnel effect)
    displaced_uv = uv;
    displaced_uv = mix(displaced_uv, vec2(0.5), scan_pos * 0.15);
```

Wait — `displaced_uv` is declared later. Let me restructure. Replace the entire displacement application section (lines 43-69) with:

```glsl
    float phase = u_time * u_scan_speed;
    float displacement = scan_pos * scan_pos * 0.4;

    // Scrolling wave creates the continuously moving slit effect
    float wave = sin(phase + scan_pos * 6.2832) * 0.5 + 0.5;
    displacement *= (0.5 + wave * 0.5);

    // Start with center convergence (tunnel effect)
    vec2 displaced_uv = mix(uv, vec2(0.5), scan_pos * 0.15);

    // Apply displacement along the scan axis
    if (u_scan_axis < 0.5) {
        displaced_uv.x += displacement * sign(uv.x - 0.5);
    } else {
        displaced_uv.y += displacement * sign(uv.y - 0.5);
    }

    // Multi-harmonic warp for organic distortion
    float warp = u_warp_amount * scan_pos;
    float warp_wave = sin(phase * 1.7 + uv.y * 12.0) * warp * 0.04;
    warp_wave += sin(phase * 0.618 + uv.y * 7.3) * warp * 0.02;
    displaced_uv.x += warp_wave;

    // Secondary + tertiary vertical ripple
    float ripple = sin(phase * 0.8 + uv.x * 8.0) * warp * 0.02;
    ripple += sin(phase * 0.309 + uv.x * 13.0) * warp * 0.01;
    displaced_uv.y += ripple;
```

- [ ] **Step 3: Increase chromatic spread**

Replace line 76 area:
```glsl
    float r = texture2D(tex, displaced_uv + vec2(chroma_spread, 0.0) * texel * 3.0).r;
    float g = texture2D(tex, displaced_uv).g;
    float b = texture2D(tex, displaced_uv - vec2(chroma_spread, 0.0) * texel * 3.0).b;
```

With:
```glsl
    float r = texture2D(tex, displaced_uv + vec2(chroma_spread, 0.0) * texel * 8.0).r;
    float g = texture2D(tex, displaced_uv).g;
    float b = texture2D(tex, displaced_uv - vec2(chroma_spread, 0.0) * texel * 8.0).b;
```

- [ ] **Step 4: Commit**

```bash
git add agents/shaders/slitscan.frag
git commit -m "fix(effects): slitscan stronger displacement, temporal banding, center convergence"
```

---

### Task 14: Rewrite pixsort shader — bubble sort approach

**Files:**
- Modify: `agents/shaders/pixsort.frag`

- [ ] **Step 1: Rewrite entire shader with pseudo-sort algorithm**

Replace the entire `main()` function (keep the header, version, uniforms, luma function):

```glsl
void main() {
    vec2 uv = v_texcoord;

    // Passthrough when sort_length disabled
    if (u_sort_length < 1.0) {
        gl_FragColor = texture2D(tex, uv);
        return;
    }

    vec4 orig = texture2D(tex, uv);
    float lum = luma(orig.rgb);

    // Only sort pixels within threshold window
    if (lum < u_threshold_low || lum > u_threshold_high) {
        gl_FragColor = orig;
        return;
    }

    // Sort direction: 0=right, 1=down
    float angle = u_direction * 3.14159 * 0.5;
    vec2 dir = vec2(cos(angle), sin(angle));
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height);

    // Walk backward to find interval start
    int intervalStart = 0;
    for (int i = 1; i < 64; i++) {
        vec2 sUV = uv - dir * texel * float(i);
        if (sUV.x < 0.0 || sUV.x > 1.0 || sUV.y < 0.0 || sUV.y > 1.0) break;
        float sLum = luma(texture2D(tex, sUV).rgb);
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;
        intervalStart = i;
    }

    // Walk forward to find interval end
    int intervalEnd = 0;
    for (int i = 1; i < 64; i++) {
        vec2 sUV = uv + dir * texel * float(i);
        if (sUV.x < 0.0 || sUV.x > 1.0 || sUV.y < 0.0 || sUV.y > 1.0) break;
        float sLum = luma(texture2D(tex, sUV).rgb);
        if (sLum < u_threshold_low || sLum > u_threshold_high) break;
        intervalEnd = i;
    }

    int intervalLen = intervalStart + intervalEnd + 1;
    if (intervalLen < 3) {
        gl_FragColor = orig;
        return;
    }

    // Sample 12 evenly-spaced pixels within the interval
    vec3 samples[12];
    float sampleLums[12];
    float step_size = float(intervalLen) / 12.0;

    for (int i = 0; i < 12; i++) {
        float pos = -float(intervalStart) + step_size * float(i);
        vec2 sUV = uv + dir * texel * pos;
        sUV = clamp(sUV, vec2(0.0), vec2(1.0));
        samples[i] = texture2D(tex, sUV).rgb;
        sampleLums[i] = luma(samples[i]);
    }

    // Bubble sort the 12 samples by luminance (ascending)
    for (int pass = 0; pass < 11; pass++) {
        for (int j = 0; j < 11; j++) {
            if (j >= 11 - pass) break;
            if (sampleLums[j] > sampleLums[j + 1]) {
                // Swap colors
                vec3 tmpC = samples[j];
                samples[j] = samples[j + 1];
                samples[j + 1] = tmpC;
                // Swap luminances
                float tmpL = sampleLums[j];
                sampleLums[j] = sampleLums[j + 1];
                sampleLums[j + 1] = tmpL;
            }
        }
    }

    // Map current pixel position to sorted array index
    float posInInterval = float(intervalStart) / float(intervalLen);
    float idx = posInInterval * 11.0;
    int idxLow = int(floor(idx));
    int idxHigh = int(ceil(idx));
    if (idxHigh > 11) idxHigh = 11;
    if (idxLow < 0) idxLow = 0;
    float frac = idx - float(idxLow);

    // Interpolate between nearest sorted samples for smooth gradient
    vec3 sorted = mix(samples[idxLow], samples[idxHigh], frac);

    gl_FragColor = vec4(sorted, 1.0);
}
```

- [ ] **Step 2: Commit**

```bash
git add agents/shaders/pixsort.frag
git commit -m "feat(effects): rewrite pixsort with bubble-sort pseudo-sorting algorithm"
```

---

### Task 15: Update backend presets (studio_effects.py)

**Files:**
- Modify: `agents/studio_effects.py:102-358`

- [ ] **Step 1: Update datamosh preset to use glitch_blocks shader**

Find the `"datamosh"` preset and add:
```python
        use_glitch_blocks_shader=True,
        glitch_blocks_params={
            "u_block_size": 32.0,
            "u_intensity": 0.4,
            "u_rgb_split": 0.3,
        },
```

Also remove hue_rotate from color_grade:
```python
        color_grade=ColorGradeConfig(saturation=0.8, brightness=1.1, contrast=1.4),
```

- [ ] **Step 2: Add silhouette preset with Sobel**

Add after the `"clean"` preset:
```python
    "silhouette": EffectPreset(
        name="silhouette",
        color_grade=ColorGradeConfig(saturation=0.0, contrast=2.5, brightness=0.8),
        trail=TrailConfig(count=2, opacity=0.1, blend_mode="source-over"),
        post_process=PostProcessConfig(vignette_strength=0.3),
        use_sobel=True,
    ),
```

- [ ] **Step 3: Update ambient preset brightness**

Find the `"ambient"` preset and update:
```python
    "ambient": EffectPreset(
        name="ambient",
        color_grade=ColorGradeConfig(saturation=0.15, brightness=0.3, contrast=0.85),
        trail=TrailConfig(count=2, opacity=0.08, blend_mode="add"),
        post_process=PostProcessConfig(vignette_strength=0.4),
    ),
```

- [ ] **Step 4: Update feedback trail opacity**

Find the `"feedback"` preset and update trail opacity:
```python
        trail=TrailConfig(
            count=8,
            opacity=0.85,
            blend_mode="add",
            filter_params={
                "brightness": 0.88,
                "hue_rotate": 5.0,
                "decay_r": 0.88,
                "decay_g": 0.85,
                "decay_b": 0.92,
            },
        ),
```

- [ ] **Step 5: Update screwed trail opacity**

Find the `"screwed"` preset and update trail opacity:
```python
        trail=TrailConfig(
            count=5,
            opacity=0.55,
            blend_mode="add",
            drift_x=1,
            drift_y=3,
            filter_params={"saturation": 0.25, "brightness": 0.6, "sepia": 0.5, "hue_rotate": 280},
        ),
```

- [ ] **Step 6: Update ASCII default cell_size**

Find the `"ascii"` preset and update:
```python
        ascii_params={"u_cell_size": 10.0, "u_color_mode": 0.0},
```

- [ ] **Step 7: Update pixsort default direction**

Find the `"pixsort"` preset and update direction to pure horizontal:
```python
        pixsort_params={
            "u_threshold_low": 0.08,
            "u_threshold_high": 0.92,
            "u_sort_length": 56.0,
            "u_direction": 0.0,
        },
```

- [ ] **Step 8: Verify and commit**

```bash
cd /home/hapax/projects/hapax-council && uv run ruff check agents/studio_effects.py && uv run ruff format agents/studio_effects.py
git add agents/studio_effects.py
git commit -m "fix(effects): align backend presets — datamosh glitch blocks, silhouette Sobel, pixsort horizontal"
```

---

### Task 16: Update effectSources.ts — add Silhouette backend mapping

**Files:**
- Modify: `hapax-logos/src/components/studio/effectSources.ts`

- [ ] **Step 1: Map fx-silhouette to silhouette backend preset (not clean)**

Find the `BACKEND_PRESET_MAP` and update:
```typescript
const BACKEND_PRESET_MAP: Record<string, string> = {
  "fx-nightvision": "clean",
  "fx-silhouette": "silhouette",
};
```

- [ ] **Step 2: Commit**

```bash
git add hapax-logos/src/components/studio/effectSources.ts
git commit -m "fix(effects): route silhouette to dedicated backend preset with Sobel"
```

---

## Batch 4: Polish

### Task 17: Final commit — bump ASCII cell_size in shader

**Files:**
- Modify: `agents/shaders/ascii.frag`

- [ ] **Step 1: No shader change needed**

The backend preset already updated `u_cell_size` to 10.0 in Task 15. The shader itself doesn't have a hardcoded default — it reads the uniform. No change needed.

- [ ] **Step 2: Create PR**

```bash
git push origin main
```

Or create feature branch if preferred. The work is on main per the spec (single worktree, sequential commits).

---

## Summary: 16 tasks, ~16 commits

| Batch | Tasks | Commits | Key Files |
|-------|-------|---------|-----------|
| 1: Infrastructure | 1-6 | 6 | CompositeCanvas.tsx, compositePresets.ts |
| 2: Broken Presets | 7-8 | 2 | compositePresets.ts, CompositeCanvas.tsx |
| 3: Shaders | 9-16 | 8 | vhs.frag, thermal.frag, halftone.frag, glitch_blocks.frag, slitscan.frag, pixsort.frag, studio_effects.py, effectSources.ts |
| 4: Polish | 17 | 0 | (no changes needed) |

**Parallelizable tasks**: Tasks 9-14 (shader edits) are fully independent — each edits a different `.frag` file. These can be dispatched to parallel subagents.

**Sequential tasks**: Tasks 1-8 must be sequential (all modify the same two frontend files). Task 15-16 (backend) can run in parallel with shader tasks but must be after Task 7 (which sets the frontend preset values that backend should align with).
