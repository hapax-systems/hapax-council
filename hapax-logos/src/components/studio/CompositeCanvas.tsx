import { useEffect, useRef } from "react";
import type { CompositePreset } from "./compositePresets";
import { acquireImage, releaseImage } from "../../hooks/useImagePool";

interface CompositeCanvasProps {
  role: string;
  preset: CompositePreset;
  isHero?: boolean;
  className?: string;
  liveSource?: string;   // URL override for live layer (default: camera/{role})
  smoothSource?: string;  // URL for smooth/overlay layer (if different from live)
  liveFilter?: string;   // Override preset's colorFilter for live layer
  smoothFilter?: string; // Override preset's overlay.filter for smooth/overlay layer
}

const RING_SIZE = 16;
const SMOOTH_RING_SIZE = 16;
const FETCH_INTERVAL = 100;
const SMOOTH_INTERVAL = 200;
const SMOOTH_DELAY_FRAMES = 3; // ~500ms at 200ms poll interval

export function CompositeCanvas({
  role,
  preset,
  className,
  liveSource,
  smoothSource,
  liveFilter,
  smoothFilter,
}: CompositeCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Keep preset in a ref so the render loop always sees the latest without re-mounting
  const presetRef = useRef(preset);
  presetRef.current = preset;
  const liveFilterRef = useRef(liveFilter);
  liveFilterRef.current = liveFilter;
  const smoothFilterRef = useRef(smoothFilter);
  smoothFilterRef.current = smoothFilter;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let running = true;
    let pending = false;
    const frameRing: HTMLImageElement[] = [];
    let writeHead = 0;

    // Smooth source: separate ring buffer if smoothSource differs from live
    const smoothRing: HTMLImageElement[] = [];
    let smoothWriteHead = 0;
    let smoothPending = false;

    // Trail state
    let lastTrailHead = 0;

    // Ping-pong back buffer for trail persistence (avoids 8-bit ghost residue)
    let backCanvas: HTMLCanvasElement | null = null;
    let backCtx: CanvasRenderingContext2D | null = null;
    // Scratch canvas for drift shift (avoids undefined same-canvas read/write behavior)
    let scratchCanvas: HTMLCanvasElement | null = null;
    let scratchCtx: CanvasRenderingContext2D | null = null;

    // Drift accumulators (fractional pixel tracking)
    let driftAccumX = 0;
    let driftAccumY = 0;

    // Stutter state
    let tick = 0;
    let displayIdx = 0;
    let phase: "play" | "freeze" | "replay" = "play";
    let freezeFor = 0;
    let holdTicks = 0;
    let replayFrom = 0;
    let replayStep = 0;

    // Neon hue rotation accumulator
    let hueAccum = 0;

    // Filter string cache — avoid per-frame string allocation
    let lastHueQ = -1;
    let cachedMainFilter = "";
    let cachedTrailFilter = "";
    let cachedOverlayFilter = "";

    // --- Filter crossfade ---
    // When live/smooth filter changes, snapshot the current canvas and blend
    // the old snapshot with new renders over 300ms for smooth transition.
    let prevLiveFilter: string | undefined = liveFilter;
    let prevSmoothFilter: string | undefined = smoothFilter;
    let crossfadeStart = 0;
    let crossfadeSnapshot: HTMLCanvasElement | null = null;
    let crossfadeCtx: CanvasRenderingContext2D | null = null;
    const CROSSFADE_MS = 300;

    /** Ensure back buffer and scratch canvas match display canvas dimensions.
     *  Preserves existing trail content on resize by copying old buffer to new one. */
    const ensureBackBuffer = (w: number, h: number) => {
      if (backCanvas && backCanvas.width === w && backCanvas.height === h) return;
      const oldBack = backCanvas;
      backCanvas = document.createElement("canvas");
      backCanvas.width = w;
      backCanvas.height = h;
      backCtx = backCanvas.getContext("2d");
      // Preserve accumulated trail content from previous buffer on resize
      if (oldBack && backCtx) {
        backCtx.drawImage(oldBack, 0, 0, w, h);
      }
      // Scratch canvas for safe drift shift (avoids undefined same-canvas self-draw)
      scratchCanvas = document.createElement("canvas");
      scratchCanvas.width = w;
      scratchCanvas.height = h;
      scratchCtx = scratchCanvas.getContext("2d");
    };

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

    const fetchFrame = () => {
      if (!running || pending) return;
      pending = true;
      const loader = acquireImage();
      loader.crossOrigin = "anonymous";
      loader.onload = () => {
        if (!running) {
          releaseImage(loader);
          pending = false;
          return;
        }
        // Release previous occupant at this ring slot
        const prev = frameRing[writeHead % RING_SIZE];
        if (prev) releaseImage(prev);
        frameRing[writeHead % RING_SIZE] = loader;
        writeHead++;
        // Size canvas to container (fill, no letterbox)
        const rect = canvas.getBoundingClientRect();
        const cw = Math.round(rect.width * devicePixelRatio);
        const ch = Math.round(rect.height * devicePixelRatio);
        if (cw > 0 && ch > 0 && (canvas.width !== cw || canvas.height !== ch)) {
          canvas.width = cw;
          canvas.height = ch;
        }
        pending = false;
      };
      loader.onerror = () => {
        releaseImage(loader);
        pending = false;
      };
      loader.src = liveSource ?? `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };

    // Helper: draw main frame with warp/slices/simple
    // skipWarp: true when trails active — animated warp + persistence = illegible smearing
    const drawMainFrame = (
      target: CanvasRenderingContext2D,
      main: HTMLImageElement,
      w: number, h: number,
      filter: string,
      alpha: number,
      blendMode: string,
      skipWarp = false,
    ) => {
      const p = presetRef.current;
      const warpCfg = skipWarp ? undefined : p.warp;

      if (warpCfg && warpCfg.sliceCount > 0) {
        const t = tick * 0.04;
        const panX = (Math.sin(t) * 0.5 + Math.sin(t * 0.618) * 0.3 + Math.sin(t * 0.237) * 0.2) * warpCfg.panX;
        const panY = (Math.sin(t * 0.7) * 0.5 + Math.sin(t * 0.432) * 0.3 + Math.sin(t * 0.166) * 0.2) * warpCfg.panY;
        const rot = (Math.sin(t * 0.5) * 0.6 + Math.sin(t * 0.309) * 0.4) * warpCfg.rotate;
        const scale = warpCfg.zoom + (Math.sin(t * 0.2) * 0.6 + Math.sin(t * 0.124) * 0.4) * warpCfg.zoomBreath;
        const sliceH = Math.ceil(h / warpCfg.sliceCount);

        target.save();
        target.globalAlpha = alpha;
        target.globalCompositeOperation = blendMode as GlobalCompositeOperation;
        if (filter !== "none") target.filter = filter;

        for (let s = 0; s < warpCfg.sliceCount; s++) {
          const sy = s * sliceH;
          const slicePhase = t + s * 0.15;
          const sliceShift =
            Math.sin(slicePhase) * warpCfg.sliceAmplitude +
            Math.sin(slicePhase * 2.3) * (warpCfg.sliceAmplitude * 0.5);
          const sliceStretch = 1 + Math.sin(slicePhase * 0.8) * 0.008;

          target.save();
          target.beginPath();
          target.rect(0, sy, w, sliceH + 1);
          target.clip();
          target.translate(w / 2, h / 2);
          target.rotate(rot);
          target.scale(scale, scale * sliceStretch);
          target.translate(-w / 2 + panX + sliceShift, -h / 2 + panY);
          target.drawImage(main, 0, 0, w, h);
          target.restore();
        }

        target.restore();
      } else if (warpCfg) {
        const t = tick * 0.04;
        const panX = (Math.sin(t) * 0.5 + Math.sin(t * 0.618) * 0.3 + Math.sin(t * 0.237) * 0.2) * warpCfg.panX;
        const panY = (Math.sin(t * 0.7) * 0.5 + Math.sin(t * 0.432) * 0.3 + Math.sin(t * 0.166) * 0.2) * warpCfg.panY;
        const rot = (Math.sin(t * 0.5) * 0.6 + Math.sin(t * 0.309) * 0.4) * warpCfg.rotate;
        const scale = warpCfg.zoom + (Math.sin(t * 0.2) * 0.6 + Math.sin(t * 0.124) * 0.4) * warpCfg.zoomBreath;

        target.save();
        target.globalAlpha = alpha;
        target.globalCompositeOperation = blendMode as GlobalCompositeOperation;
        if (filter !== "none") target.filter = filter;
        target.translate(w / 2, h / 2);
        target.rotate(rot);
        target.scale(scale, scale);
        target.translate(-w / 2 + panX, -h / 2 + panY);
        target.drawImage(main, 0, 0, w, h);
        target.restore();
      } else {
        target.save();
        target.globalAlpha = alpha;
        target.globalCompositeOperation = blendMode as GlobalCompositeOperation;
        if (filter !== "none") target.filter = filter;
        target.drawImage(main, 0, 0, w, h);
        target.restore();
      }
    };

    // Helper: draw overlay + post-effects onto display canvas
    const drawOverlayAndEffects = (
      main: HTMLImageElement,
      w: number, h: number,
      mainFilter: string,
    ) => {
      const p = presetRef.current;

      // --- Delayed overlay (smooth source if available, else delayed from live ring) ---
      const smoothAvail = Math.min(smoothWriteHead, SMOOTH_RING_SIZE);
      const useSmoothRing = smoothSource && smoothAvail > 0;
      const available = Math.min(writeHead, RING_SIZE);
      const frameIdx = Math.abs(displayIdx) % available;
      if (p.overlay && (useSmoothRing || available > p.overlay.delayFrames)) {
        const delayed = useSmoothRing
          ? smoothRing[((smoothWriteHead - 1 - SMOOTH_DELAY_FRAMES) + SMOOTH_RING_SIZE * 100) % Math.min(smoothAvail, SMOOTH_RING_SIZE)]
          : frameRing[(frameIdx - p.overlay.delayFrames + available * 100) % available];
        if (delayed) {
          ctx.save();
          if (cachedOverlayFilter !== "none") {
            ctx.filter = cachedOverlayFilter;
          }
          ctx.globalAlpha = p.overlay.alpha;
          ctx.globalCompositeOperation = p.overlay.blendMode as GlobalCompositeOperation;
          const dt = tick * 0.03;
          ctx.drawImage(
            delayed,
            Math.sin(dt) * 5,
            p.overlay.driftY + Math.sin(dt * 0.6) * 4,
            w,
            h,
          );
          ctx.restore();
        }
      }

      // --- VHS head switching noise ---
      if (p.name === "VHS" && main) {
        const headSwitchY = h * 0.92;
        const headSwitchH = h * 0.08;
        ctx.save();
        if (mainFilter !== "none") ctx.filter = mainFilter;
        ctx.beginPath();
        ctx.rect(0, headSwitchY, w, headSwitchH);
        ctx.clip();
        const jitter = Math.sin(tick * 0.3) * 8 + Math.sin(tick * 0.7) * 4;
        ctx.drawImage(main, jitter, -2, w, h);
        ctx.restore();
      }

      // --- Post-effects ---
      drawPostEffects(main, w, h, mainFilter);
    };

    /** Draw post-effects (scanlines, bands, vignette, syrup, freeze tint) onto display canvas. */
    const drawPostEffects = (
      main: HTMLImageElement | null,
      w: number, h: number,
      mainFilter: string,
    ) => {
      const fx = presetRef.current.effects;

      if (fx.scanlines) {
        ctx.save();
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = "rgba(0,0,0,1)";
        for (let y = 0; y < h; y += 4) {
          ctx.fillRect(0, y + 2, w, 1.5);
        }
        ctx.restore();
      }

      if (fx.bandDisplacement && main) {
        const bandChance = fx.bandChance || 0.25;
        const bandMaxShift = fx.bandMaxShift || 20;
        if (Math.random() < bandChance) {
          const bandY = Math.floor(Math.random() * h * 0.6) + h * 0.2;
          const bandH = 4 + Math.floor(Math.random() * 16);
          const shift =
            (Math.random() > 0.5 ? 1 : -1) * (5 + Math.random() * bandMaxShift);
          ctx.save();
          if (mainFilter !== "none") ctx.filter = mainFilter;
          ctx.beginPath();
          ctx.rect(0, bandY, w, bandH);
          ctx.clip();
          ctx.drawImage(main, shift, 0, w, h);
          ctx.restore();
        }
      }

      if (fx.vignette) {
        const vignetteStrength = fx.vignetteStrength || 0.35;
        const vig = ctx.createRadialGradient(w / 2, h / 2, w * 0.3, w / 2, h / 2, w * 0.7);
        vig.addColorStop(0, "rgba(0,0,0,0)");
        vig.addColorStop(1, `rgba(0,0,0,${vignetteStrength})`);
        ctx.fillStyle = vig;
        ctx.fillRect(0, 0, w, h);
      }

      if (fx.syrupGradient) {
        ctx.save();
        ctx.filter = "none";
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        const c = fx.syrupColor === "0, 0, 0" ? "30, 15, 45" : fx.syrupColor;
        grad.addColorStop(0, `rgba(${c}, 0.0)`);
        grad.addColorStop(0.5, `rgba(${c}, 0.1)`);
        grad.addColorStop(1, `rgba(${c}, 0.25)`);
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      }

      if (phase === "freeze") {
        ctx.fillStyle = "rgba(80, 30, 120, 0.18)";
        ctx.fillRect(0, 0, w, h);
      }
    };

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

    /** Draw noise grain overlay if preset has noise config. */
    const drawNoise = (w: number, h: number) => {
      const noise = presetRef.current.noise;
      if (!noise?.enabled) return;

      if (!noiseGenerated || (noise.animated && ++noiseTickCounter % 3 === 0)) {
        regenerateNoise();
      }

      ctx.save();
      ctx.imageSmoothingEnabled = false;
      ctx.globalAlpha = noise.intensity;
      ctx.globalCompositeOperation = "overlay";
      ctx.drawImage(noiseCanvas, 0, 0, w, h);
      ctx.restore();
    };

    /** Draw bloom glow: extract bright pixels, blur at 1/4 res, composite with lighter. */
    const drawBloom = (w: number, h: number) => {
      const bloom = presetRef.current.bloom;
      if (!bloom?.enabled || !canvas) return;

      ensureBloomCanvas(w, h);
      if (!bloomCtx || !bloomCanvas) return;

      const brightPass = 0.5 - bloom.threshold * 0.4;
      bloomCtx.filter = `brightness(${brightPass}) contrast(100) blur(${bloom.radius / 4}px)`;
      bloomCtx.drawImage(canvas, 0, 0, bloomCanvas.width, bloomCanvas.height);
      bloomCtx.filter = "none";

      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = bloom.alpha;
      ctx.drawImage(bloomCanvas, 0, 0, w, h);
      ctx.restore();
    };

    let strobeTicks = 0;

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

    /**
     * Compute calibrated fade and draw alphas based on blend mode and preset params.
     * The key insight: fade and draw must reach approximate equilibrium to prevent
     * wash-out (additive) or fade-to-black (multiply). destination-out fade avoids
     * the 8-bit ghost residue problem inherent in source-over black-rect fading.
     */
    const computeTrailAlphas = (trail: CompositePreset["trail"]) => {
      // Base fade rate per rAF tick, tuned per blend mode
      const baseFade = trail.blendMode === "lighter" ? 0.03
        : trail.blendMode === "multiply" ? 0.08
        : trail.blendMode === "difference" ? 0.03
        : 0.04;
      // Scale by opacity (user-facing trail intensity)
      const opacityScale = 0.5 + trail.opacity * 0.5;
      // Scale inversely by count (more echoes = slower fade for longer persistence)
      const countScale = 1.0 / Math.sqrt(Math.max(trail.count, 1));
      const fadeAlpha = baseFade * opacityScale * countScale;

      // Main draw alpha: enough presence per frame without overwhelming fade
      // Main draw alpha: enough presence per frame without overwhelming fade.
      // "difference" needs moderate alpha — too high saturates to a persistent bright ghost.
      const mainAlpha = trail.blendMode === "lighter"
        ? 0.08 + (trail.opacity * 0.12) / Math.sqrt(Math.max(trail.count, 1))
        : trail.blendMode === "difference"
          ? 0.15 + trail.opacity * 0.25
          : trail.blendMode === "multiply"
            ? 0.3 + trail.opacity * 0.3
            : 0.2 + trail.opacity * 0.4;

      return { fadeAlpha, mainAlpha };
    };

    const render = () => {
      if (!running) return;
      const p = presetRef.current;
      const w = canvas.width;
      const h = canvas.height;
      if (w === 0) return;
      const available = Math.min(writeHead, RING_SIZE);
      if (available < 3) return;

      tick++;
      hueAccum += 4;

      // --- Filter crossfade: detect changes and snapshot ---
      const curLiveFilter = liveFilterRef.current;
      const curSmoothFilter = smoothFilterRef.current;
      if (curLiveFilter !== prevLiveFilter || curSmoothFilter !== prevSmoothFilter) {
        if (prevLiveFilter !== undefined || prevSmoothFilter !== undefined) {
          // Snapshot current canvas state before the new filter takes effect
          if (!crossfadeSnapshot || crossfadeSnapshot.width !== w || crossfadeSnapshot.height !== h) {
            crossfadeSnapshot = document.createElement("canvas");
            crossfadeSnapshot.width = w;
            crossfadeSnapshot.height = h;
            crossfadeCtx = crossfadeSnapshot.getContext("2d");
          }
          if (crossfadeCtx) {
            crossfadeCtx.clearRect(0, 0, w, h);
            crossfadeCtx.drawImage(canvas, 0, 0);
          }
          crossfadeStart = performance.now();
        }
        prevLiveFilter = curLiveFilter;
        prevSmoothFilter = curSmoothFilter;
        // Force filter cache refresh
        lastHueQ = -1;
      }

      // Update cached filter strings only when quantized hue changes
      const hueQ = Math.round(hueAccum / 10) * 10;
      if (hueQ !== lastHueQ) {
        lastHueQ = hueQ;
        const isNeonLike = p.name === "Neon" || p.name === "Feedback";
        const effectiveLiveFilter = liveFilterRef.current ?? p.colorFilter;
        const effectiveSmoothFilter = smoothFilterRef.current ?? p.overlay?.filter ?? "none";
        cachedMainFilter = isNeonLike && effectiveLiveFilter !== "none"
          ? `${effectiveLiveFilter} hue-rotate(${hueQ}deg)` : effectiveLiveFilter;
        cachedTrailFilter = isNeonLike && p.trail.filter !== "none"
          ? `${p.trail.filter} hue-rotate(${hueQ + 60}deg)` : p.trail.filter;
        cachedOverlayFilter = isNeonLike && effectiveSmoothFilter !== "none"
          ? `${effectiveSmoothFilter} hue-rotate(${hueQ + 120}deg)` : effectiveSmoothFilter;
      }

      // --- Stutter engine ---
      const stutter = p.stutter;
      if (stutter) {
        if (phase === "play") {
          displayIdx = (writeHead - 1) % RING_SIZE;
          if (tick % stutter.checkInterval === 0 && Math.random() < stutter.freezeChance) {
            phase = "freeze";
            freezeFor =
              stutter.freezeMin + Math.floor(Math.random() * (stutter.freezeMax - stutter.freezeMin));
            holdTicks = 0;
          }
        } else if (phase === "freeze") {
          holdTicks++;
          if (holdTicks >= freezeFor) {
            phase = "replay";
            replayFrom = displayIdx;
            replayStep = 0;
            holdTicks = 0;
          }
        } else if (phase === "replay") {
          holdTicks++;
          if (holdTicks >= 2) {
            holdTicks = 0;
            replayStep++;
            displayIdx =
              (replayFrom - stutter.replayFrames + replayStep + RING_SIZE * 10) % RING_SIZE;
            if (replayStep >= stutter.replayFrames) {
              phase = "play";
            }
          }
        }
      } else {
        displayIdx = (writeHead - 1) % RING_SIZE;
      }

      const idx = Math.abs(displayIdx) % available;
      const main = frameRing[idx];
      if (!main) return;

      const trail = p.trail;
      const trailActive = trail.count > 0 && trail.opacity > 0;
      const isNewFrame = writeHead !== lastTrailHead;

      if (trailActive) {
        // --- PING-PONG PERSISTENCE MODEL ---
        // Back buffer accumulates trail content. Display canvas gets a clean copy
        // each tick with post-effects on top. destination-out fade avoids 8-bit
        // ghost residue that plagues source-over black-rect fading.
        ensureBackBuffer(w, h);
        if (!backCtx) return;

        const { fadeAlpha, mainAlpha } = computeTrailAlphas(trail);

        // 1. FADE: subtract alpha from existing content (destination-out)
        backCtx.save();
        backCtx.globalCompositeOperation = "destination-out";
        backCtx.globalAlpha = fadeAlpha;
        backCtx.fillStyle = "rgba(0,0,0,1)";
        backCtx.fillRect(0, 0, w, h);
        backCtx.restore();

        // 2. DRIFT: shift existing content for spatial trail separation
        if (trail.driftX > 0 || trail.driftY > 0) {
          // Organic sinusoidal drift direction
          const t = tick * 0.015;
          const dxSign = Math.sin(t);
          const dySign = Math.cos(t * 0.7);
          driftAccumX += trail.driftX * dxSign * 0.15;
          driftAccumY += trail.driftY * dySign * 0.15;

          if (Math.abs(driftAccumX) >= 1 || Math.abs(driftAccumY) >= 1) {
            const shiftX = Math.trunc(driftAccumX);
            const shiftY = Math.trunc(driftAccumY);
            driftAccumX -= shiftX;
            driftAccumY -= shiftY;
            // Use scratch canvas to avoid undefined same-canvas read/write behavior
            if (scratchCtx && scratchCanvas) {
              scratchCtx.clearRect(0, 0, w, h);
              scratchCtx.drawImage(backCanvas!, 0, 0);
              backCtx.clearRect(0, 0, w, h);
              backCtx.drawImage(scratchCanvas, shiftX, shiftY);
            }
          }
        }

        // 3. COMPOSITE new frame onto back buffer (only on new JPEG arrival)
        //    When warp is configured, pre-render warped frame to scratch canvas then copy
        //    flat result to back buffer. Drawing warp directly to back buffer causes
        //    directional smearing because each tick's warp position accumulates.
        if (isNewFrame) {
          lastTrailHead = writeHead;
          if (p.warp && scratchCtx && scratchCanvas) {
            // Render warped frame to scratch at full opacity with source-over,
            // then composite the flat result onto back buffer with trail blend/alpha.
            scratchCtx.clearRect(0, 0, w, h);
            drawMainFrame(scratchCtx, main, w, h, cachedTrailFilter, 1, "source-over", false);
            backCtx.save();
            backCtx.globalAlpha = mainAlpha;
            backCtx.globalCompositeOperation = trail.blendMode as GlobalCompositeOperation;
            backCtx.drawImage(scratchCanvas, 0, 0);
            backCtx.restore();
          } else {
            drawMainFrame(backCtx, main, w, h, cachedTrailFilter, mainAlpha, trail.blendMode, true);
          }
        }

        // 4. PRESENT: copy back buffer to display canvas
        ctx.clearRect(0, 0, w, h);
        ctx.drawImage(backCanvas!, 0, 0);

        // 5. OVERLAY + POST-EFFECTS on display canvas (not accumulated into trail buffer)
        // Use main filter here, not trail filter — post-effects (VHS head-switch, band
        // displacement) should match the main frame color, not the trail color treatment.
        if (isNewFrame) {
          drawOverlayAndEffects(main, w, h, cachedMainFilter);
        } else {
          // Post-effects still run every tick for visual consistency
          drawPostEffects(main, w, h, cachedMainFilter);
        }
        drawBloom(w, h);
        drawNoise(w, h);
        drawStrobe(w, h);
        applyCircularMask(w, h);

      } else {
        // --- NO TRAILS: clear and redraw every rAF tick (warp OK here) ---
        ctx.clearRect(0, 0, w, h);
        drawMainFrame(ctx, main, w, h, cachedMainFilter, 1, "source-over");
        drawOverlayAndEffects(main, w, h, cachedMainFilter);
        drawBloom(w, h);
        drawNoise(w, h);
        drawStrobe(w, h);
        applyCircularMask(w, h);
      }

      // --- Filter crossfade: blend old snapshot with new render ---
      if (crossfadeStart > 0 && crossfadeSnapshot && crossfadeCtx) {
        const elapsed = performance.now() - crossfadeStart;
        if (elapsed < CROSSFADE_MS) {
          const oldAlpha = 1 - elapsed / CROSSFADE_MS;
          ctx.save();
          ctx.globalAlpha = oldAlpha;
          ctx.drawImage(crossfadeSnapshot, 0, 0);
          ctx.restore();
        } else {
          crossfadeStart = 0;
        }
      }
    };

    const fetchSmooth = () => {
      if (!running || smoothPending || !smoothSource) return;
      smoothPending = true;
      const loader = acquireImage();
      loader.crossOrigin = "anonymous";
      loader.onload = () => {
        if (!running) { releaseImage(loader); smoothPending = false; return; }
        const prev = smoothRing[smoothWriteHead % SMOOTH_RING_SIZE];
        if (prev) releaseImage(prev);
        smoothRing[smoothWriteHead % SMOOTH_RING_SIZE] = loader;
        smoothWriteHead++;
        smoothPending = false;
      };
      loader.onerror = () => { releaseImage(loader); smoothPending = false; };
      loader.src = `${smoothSource}?_t=${Date.now()}`;
    };

    // Unified rAF loop
    let lastFetch = 0;
    let lastSmooth = 0;
    fetchFrame();
    if (smoothSource) fetchSmooth();

    const loop = (now: number) => {
      if (!running) return;
      if (now - lastFetch >= FETCH_INTERVAL) { fetchFrame(); lastFetch = now; }
      if (smoothSource && now - lastSmooth >= SMOOTH_INTERVAL) { fetchSmooth(); lastSmooth = now; }
      render();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);

    return () => {
      running = false;
      for (const img of frameRing) { if (img) releaseImage(img); }
      for (const img of smoothRing) { if (img) releaseImage(img); }
    };
  }, [role, liveSource, smoothSource]);

  return (
    <canvas
      ref={canvasRef}
      className={className ?? "h-full w-full bg-black"}
    />
  );
}
