import { useEffect, useRef } from "react";
import type { CompositePreset } from "./compositePresets";

interface CompositeCanvasProps {
  role: string;
  preset: CompositePreset;
  isHero?: boolean;
  className?: string;
}

const RING_SIZE = 16;
const FETCH_INTERVAL = 100;
const RENDER_INTERVAL = 70;

export function CompositeCanvas({
  role,
  preset,
  isHero,
  className,
}: CompositeCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Keep preset in a ref so the render loop always sees the latest without re-mounting
  const presetRef = useRef(preset);
  presetRef.current = preset;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let running = true;
    let pending = false;
    const frameRing: HTMLImageElement[] = [];
    let writeHead = 0;

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

    // --- Offscreen canvases for custom preset passes (created once) ---
    const offscreen = document.createElement("canvas");
    const offCtx = offscreen.getContext("2d");
    const accumCanvas = document.createElement("canvas");
    const accumCtx = accumCanvas.getContext("2d");

    // VHS noise band position
    let noiseBandY = 0;

    // Trap strobe state
    let strobeCountdown = 0;
    let strobeTicks = 0;
    let nextStrobeAt = 18 + Math.floor(Math.random() * 7);

    // Noise tile for Trap grain (256x256, created once)
    const noiseTile = document.createElement("canvas");
    noiseTile.width = 256;
    noiseTile.height = 256;
    const noiseCtx = noiseTile.getContext("2d");
    if (noiseCtx) {
      const noiseData = noiseCtx.createImageData(256, 256);
      const nd = noiseData.data;
      for (let i = 0; i < nd.length; i += 4) {
        const v = Math.floor(Math.random() * 255);
        nd[i] = v;
        nd[i + 1] = v;
        nd[i + 2] = v;
        nd[i + 3] = 255;
      }
      noiseCtx.putImageData(noiseData, 0, 0);
    }

    // Track whether offscreen canvases are sized
    let offscreenSized = false;

    const sizeOffscreens = (w: number, h: number) => {
      if (offscreenSized && offscreen.width === w && offscreen.height === h) return;
      offscreen.width = w;
      offscreen.height = h;
      accumCanvas.width = w;
      accumCanvas.height = h;
      // Clear accumulation canvas on resize
      if (accumCtx) {
        accumCtx.clearRect(0, 0, w, h);
      }
      offscreenSized = true;
    };

    const fetchFrame = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      loader.crossOrigin = "anonymous";
      loader.onload = () => {
        if (!running) {
          pending = false;
          return;
        }
        frameRing[writeHead % RING_SIZE] = loader;
        writeHead++;
        if (canvas.width !== loader.naturalWidth && loader.naturalWidth > 0) {
          canvas.width = loader.naturalWidth;
          canvas.height = loader.naturalHeight;
        }
        pending = false;
      };
      loader.onerror = () => {
        pending = false;
      };
      loader.src = `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };

    const render = () => {
      if (!running) return;
      const p = presetRef.current;
      const w = canvas.width;
      const h = canvas.height;
      if (w === 0) return;
      const available = Math.min(writeHead, RING_SIZE);
      if (available < 3) return;

      // Ensure offscreen canvases match main canvas size
      sizeOffscreens(w, h);

      tick++;
      hueAccum += 4; // degrees per tick for neon hue rotation

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

      // --- Trails preset: accumulation buffer instead of clearRect ---
      const isTrails = p.name === "Trails" && isHero && accumCtx;
      if (!isTrails) {
        ctx.clearRect(0, 0, w, h);
      }

      // --- Ghost trails ---
      const trail = p.trail;
      const trailSpacing = Math.max(3, Math.floor(available / (trail.count + 1)));
      for (let g = trail.count; g >= 1; g--) {
        const gi = (idx - g * trailSpacing + available * 100) % available;
        const ghost = frameRing[gi];
        if (!ghost) continue;
        ctx.save();
        let trailFilter = trail.filter;
        if (trailFilter !== "none" && p.name === "Neon") {
          trailFilter = `${trailFilter} hue-rotate(${hueAccum + g * 30}deg)`;
        }
        // Per-layer hue spread for rainbow trails
        if (trailFilter !== "none" && trail.hueSpread && p.name !== "Neon") {
          trailFilter = `${trailFilter} hue-rotate(${trail.hueSpread * g}deg)`;
        }
        if (trailFilter !== "none") {
          ctx.filter = trailFilter;
        }
        ctx.globalAlpha = trail.opacity * (1 - g / (trail.count + 1));
        ctx.globalCompositeOperation = trail.blendMode as GlobalCompositeOperation;
        ctx.drawImage(ghost, trail.driftX * g, trail.driftY * g, w, h);
        ctx.restore();
      }

      // --- Main frame ---
      const main = frameRing[idx];
      if (!main) return;

      // For Neon, inject cycling hue-rotate into the main colorFilter
      const isNeon = p.name === "Neon";
      let mainFilter = p.colorFilter;
      if (isNeon && mainFilter !== "none") {
        mainFilter = `${mainFilter} hue-rotate(${hueAccum}deg)`;
      }

      const warpCfg = p.warp;
      if (warpCfg && warpCfg.sliceCount > 0) {
        // Warp with horizontal slices
        const t = tick * 0.04;
        const panX = Math.sin(t) * warpCfg.panX;
        const panY =
          Math.sin(t * 0.7) * (warpCfg.panY * 0.64) +
          Math.sin(t * 0.3) * (warpCfg.panY * 0.36);
        const rot = Math.sin(t * 0.5) * warpCfg.rotate;
        const scale = warpCfg.zoom + Math.sin(t * 0.2) * warpCfg.zoomBreath;
        const sliceH = Math.ceil(h / warpCfg.sliceCount);

        ctx.save();
        if (mainFilter !== "none") {
          ctx.filter = mainFilter;
        }

        for (let s = 0; s < warpCfg.sliceCount; s++) {
          const sy = s * sliceH;
          const slicePhase = t + s * 0.15;
          const sliceShift =
            Math.sin(slicePhase) * warpCfg.sliceAmplitude +
            Math.sin(slicePhase * 2.3) * (warpCfg.sliceAmplitude * 0.5);
          const sliceStretch = 1 + Math.sin(slicePhase * 0.8) * 0.008;

          ctx.save();
          ctx.beginPath();
          ctx.rect(0, sy, w, sliceH + 1);
          ctx.clip();
          ctx.translate(w / 2, h / 2);
          ctx.rotate(rot);
          ctx.scale(scale, scale * sliceStretch);
          ctx.translate(-w / 2 + panX + sliceShift, -h / 2 + panY);
          ctx.drawImage(main, 0, 0, w, h);
          ctx.restore();
        }

        ctx.restore();
      } else if (warpCfg) {
        // Global warp transform without slicing
        const t = tick * 0.04;
        const panX = Math.sin(t) * warpCfg.panX;
        const panY = Math.sin(t * 0.7) * warpCfg.panY;
        const rot = Math.sin(t * 0.5) * warpCfg.rotate;
        const scale = warpCfg.zoom + Math.sin(t * 0.2) * warpCfg.zoomBreath;

        ctx.save();
        if (mainFilter !== "none") {
          ctx.filter = mainFilter;
        }
        ctx.translate(w / 2, h / 2);
        ctx.rotate(rot);
        ctx.scale(scale, scale);
        ctx.translate(-w / 2 + panX, -h / 2 + panY);
        ctx.drawImage(main, 0, 0, w, h);
        ctx.restore();
      } else {
        // No warp — simple draw
        ctx.save();
        if (mainFilter !== "none") {
          ctx.filter = mainFilter;
        }
        ctx.drawImage(main, 0, 0, w, h);
        ctx.restore();
      }

      // --- Delayed overlay ---
      if (p.overlay && available > p.overlay.delayFrames) {
        const delayIdx = (idx - p.overlay.delayFrames + available * 100) % available;
        const delayed = frameRing[delayIdx];
        if (delayed) {
          ctx.save();
          let overlayFilter = p.overlay.filter;
          if (isNeon && overlayFilter !== "none") {
            overlayFilter = `${overlayFilter} hue-rotate(${hueAccum + 120}deg)`;
          }
          if (overlayFilter !== "none") {
            ctx.filter = overlayFilter;
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

      // --- VHS chroma shift: draw a red-shifted copy offset to the right ---
      if (p.effects.chromaShift && p.effects.chromaShift > 0 && main) {
        const shift = p.effects.chromaShift;
        ctx.save();
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = 0.15;
        ctx.filter = "saturate(2) hue-rotate(-30deg) brightness(0.8)";
        ctx.drawImage(main, shift, 0, w, h);
        ctx.restore();
        // Cyan ghost shifted left
        ctx.save();
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = 0.1;
        ctx.filter = "saturate(2) hue-rotate(150deg) brightness(0.7)";
        ctx.drawImage(main, -shift * 0.6, 0, w, h);
        ctx.restore();
      }

      // --- VHS head switching noise — persistent bottom distortion ---
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

      // --- Effects ---
      const fx = p.effects;

      // Scanlines
      if (fx.scanlines) {
        ctx.save();
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = "rgba(0,0,0,1)";
        for (let y = 0; y < h; y += 4) {
          ctx.fillRect(0, y + 2, w, 1.5);
        }
        ctx.restore();
      }

      // Band displacement
      if (fx.bandDisplacement && Math.random() < fx.bandChance && main) {
        const bandY = Math.floor(Math.random() * h * 0.6) + h * 0.2;
        const bandH = 4 + Math.floor(Math.random() * 16);
        const shift =
          (Math.random() > 0.5 ? 1 : -1) * (5 + Math.random() * fx.bandMaxShift);
        ctx.save();
        if (mainFilter !== "none") {
          ctx.filter = mainFilter;
        }
        ctx.beginPath();
        ctx.rect(0, bandY, w, bandH);
        ctx.clip();
        ctx.drawImage(main, shift, 0, w, h);
        ctx.restore();
      }

      // Black crush — push dark pixels toward pure black
      if (fx.blackCrush && fx.blackCrush > 0) {
        const imageData = ctx.getImageData(0, 0, w, h);
        const d = imageData.data;
        const threshold = fx.blackCrush;
        for (let i = 0; i < d.length; i += 4) {
          const lum = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
          if (lum < threshold) {
            const factor = lum / threshold;
            const crush = factor * factor; // quadratic falloff
            d[i] = Math.round(d[i] * crush);
            d[i + 1] = Math.round(d[i + 1] * crush);
            d[i + 2] = Math.round(d[i + 2] * crush);
          }
        }
        ctx.putImageData(imageData, 0, 0);
      }

      // Green phosphor persistence for Diff — tint bright motion pixels green
      if (fx.phosphorDecay) {
        const imageData = ctx.getImageData(0, 0, w, h);
        const d = imageData.data;
        for (let i = 0; i < d.length; i += 4) {
          const lum = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
          if (lum > 20) {
            // Tint toward green phosphor: boost green, reduce red/blue
            d[i] = Math.round(d[i] * 0.3); // red down
            d[i + 1] = Math.min(255, Math.round(d[i + 1] * 0.5 + lum * 0.8)); // green up
            d[i + 2] = Math.round(d[i + 2] * 0.15); // blue down
          }
        }
        ctx.putImageData(imageData, 0, 0);
      }

      // Vignette
      if (fx.vignette) {
        const vig = ctx.createRadialGradient(w / 2, h / 2, w * 0.3, w / 2, h / 2, w * 0.7);
        vig.addColorStop(0, "rgba(0,0,0,0)");
        vig.addColorStop(1, `rgba(0,0,0,${fx.vignetteStrength})`);
        ctx.fillStyle = vig;
        ctx.fillRect(0, 0, w, h);
      }

      // Tint overlay
      if (fx.tintColor && fx.tintAlpha && fx.tintAlpha > 0) {
        ctx.save();
        ctx.globalAlpha = fx.tintAlpha;
        ctx.fillStyle = `rgb(${fx.tintColor})`;
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      }

      // Syrup gradient
      if (fx.syrupGradient) {
        ctx.save();
        ctx.filter = "none";
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        const c = fx.syrupColor;
        grad.addColorStop(0, `rgba(${c}, 0.0)`);
        grad.addColorStop(0.5, `rgba(${c}, 0.1)`);
        grad.addColorStop(1, `rgba(${c}, 0.25)`);
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
        ctx.restore();
      }

      // Freeze indicator
      if (phase === "freeze") {
        ctx.fillStyle = "rgba(80, 30, 120, 0.18)";
        ctx.fillRect(0, 0, w, h);
      }

      // =================================================================
      // CUSTOM PER-PRESET RENDERING PASSES (after base pipeline)
      // Only run on hero camera for performance
      // =================================================================

      if (isHero && offCtx) {
        // -----------------------------------------------------------
        // GHOST — Edge-only trail ghosts + temporal color shift
        // -----------------------------------------------------------
        if (p.name === "Ghost") {
          for (let g = trail.count; g >= 1; g--) {
            const gi = (idx - g * trailSpacing + available * 100) % available;
            const ghost = frameRing[gi];
            if (!ghost) continue;

            // Draw ghost frame to offscreen
            offCtx.clearRect(0, 0, w, h);
            offCtx.drawImage(ghost, 0, 0, w, h);

            // Sobel edge detection
            const src = offCtx.getImageData(0, 0, w, h);
            const sd = src.data;
            const edgeData = offCtx.createImageData(w, h);
            const ed = edgeData.data;

            // Process every 2nd pixel for performance, fill neighbors
            for (let y = 1; y < h - 1; y += 2) {
              for (let x = 1; x < w - 1; x += 2) {
                const i00 = ((y - 1) * w + (x - 1)) * 4;
                const i01 = ((y - 1) * w + x) * 4;
                const i02 = ((y - 1) * w + (x + 1)) * 4;
                const i10 = (y * w + (x - 1)) * 4;
                const i12 = (y * w + (x + 1)) * 4;
                const i20 = ((y + 1) * w + (x - 1)) * 4;
                const i21 = ((y + 1) * w + x) * 4;
                const i22 = ((y + 1) * w + (x + 1)) * 4;

                // Luminance at each neighbor
                const l00 = sd[i00] * 0.299 + sd[i00 + 1] * 0.587 + sd[i00 + 2] * 0.114;
                const l01 = sd[i01] * 0.299 + sd[i01 + 1] * 0.587 + sd[i01 + 2] * 0.114;
                const l02 = sd[i02] * 0.299 + sd[i02 + 1] * 0.587 + sd[i02 + 2] * 0.114;
                const l10 = sd[i10] * 0.299 + sd[i10 + 1] * 0.587 + sd[i10 + 2] * 0.114;
                const l12 = sd[i12] * 0.299 + sd[i12 + 1] * 0.587 + sd[i12 + 2] * 0.114;
                const l20 = sd[i20] * 0.299 + sd[i20 + 1] * 0.587 + sd[i20 + 2] * 0.114;
                const l21 = sd[i21] * 0.299 + sd[i21 + 1] * 0.587 + sd[i21 + 2] * 0.114;
                const l22 = sd[i22] * 0.299 + sd[i22 + 1] * 0.587 + sd[i22 + 2] * 0.114;

                // Sobel kernels
                const gx = -l00 - 2 * l10 - l20 + l02 + 2 * l12 + l22;
                const gy = -l00 - 2 * l01 - l02 + l20 + 2 * l21 + l22;
                const mag = Math.min(255, Math.sqrt(gx * gx + gy * gy));

                // Write edge pixel (and fill the skipped neighbor)
                const oi = (y * w + x) * 4;
                const oi2 = (y * w + x + 1) * 4;
                ed[oi] = mag;
                ed[oi + 1] = mag;
                ed[oi + 2] = mag;
                ed[oi + 3] = mag > 20 ? 255 : 0;
                if (x + 1 < w) {
                  ed[oi2] = mag;
                  ed[oi2 + 1] = mag;
                  ed[oi2 + 2] = mag;
                  ed[oi2 + 3] = mag > 20 ? 255 : 0;
                }
              }
            }

            offCtx.putImageData(edgeData, 0, 0);

            // Composite edge canvas onto main with color shift
            // Newer ghosts warm (hue 0), older cool (hue 180)
            const hueShift = (g / trail.count) * 180;
            ctx.save();
            ctx.globalCompositeOperation = "screen";
            ctx.globalAlpha = 0.5 * (1 - g / (trail.count + 1));
            ctx.filter = `hue-rotate(${hueShift}deg)`;
            ctx.drawImage(offscreen, trail.driftX * g * 0.5, trail.driftY * g * 0.5);
            ctx.restore();
          }
        }

        // -----------------------------------------------------------
        // TRAILS — Persistent accumulation (light painting)
        // -----------------------------------------------------------
        if (p.name === "Trails" && accumCtx) {
          // Slow decay: semi-transparent black rect
          accumCtx.save();
          accumCtx.globalCompositeOperation = "source-over";
          accumCtx.fillStyle = "rgba(0, 0, 0, 0.06)";
          accumCtx.fillRect(0, 0, w, h);
          accumCtx.restore();

          // Draw current frame onto accumulation with lighter blend
          accumCtx.save();
          accumCtx.globalCompositeOperation = "lighter";
          accumCtx.globalAlpha = 0.35;
          if (mainFilter !== "none") {
            accumCtx.filter = mainFilter;
          }
          accumCtx.drawImage(main, 0, 0, w, h);
          accumCtx.restore();

          // Composite accumulation onto the main canvas
          ctx.save();
          ctx.globalCompositeOperation = "lighter";
          ctx.globalAlpha = 0.7;
          ctx.drawImage(accumCanvas, 0, 0);
          ctx.restore();
        }

        // -----------------------------------------------------------
        // DATAMOSH — Block displacement from previous frame
        // -----------------------------------------------------------
        if (p.name === "Datamosh") {
          // Get a previous frame for block source
          const prevIdx = (idx - 1 + available) % available;
          const prevFrame = frameRing[prevIdx];
          if (prevFrame) {
            // Draw previous frame to offscreen as block source
            offCtx.clearRect(0, 0, w, h);
            offCtx.drawImage(prevFrame, 0, 0, w, h);

            const blockSize = 16;
            const cols = Math.floor(w / blockSize);
            const rows = Math.floor(h / blockSize);

            for (let by = 0; by < rows; by++) {
              for (let bx = 0; bx < cols; bx++) {
                if (Math.random() > 0.3) continue; // ~30% of blocks

                const srcX = bx * blockSize;
                const srcY = by * blockSize;
                const dx = Math.floor((Math.random() - 0.5) * 64); // ±32
                const dy = Math.floor((Math.random() - 0.5) * 64);
                const destX = Math.max(0, Math.min(w - blockSize, srcX + dx));
                const destY = Math.max(0, Math.min(h - blockSize, srcY + dy));

                ctx.drawImage(
                  offscreen,
                  srcX,
                  srcY,
                  blockSize,
                  blockSize,
                  destX,
                  destY,
                  blockSize,
                  blockSize,
                );
              }
            }
          }
        }

        // -----------------------------------------------------------
        // VHS — RGB channel separation + scrolling noise band
        // -----------------------------------------------------------
        if (p.name === "VHS") {
          const imageData = ctx.getImageData(0, 0, w, h);
          const sd = imageData.data;
          const result = ctx.createImageData(w, h);
          const rd = result.data;

          const chanOffset = 3; // pixels of R/B channel offset

          // Channel separation: R from (x-3), G from (x), B from (x+3)
          // Process every 2nd row for performance
          for (let y = 0; y < h; y += 2) {
            for (let x = 0; x < w; x++) {
              const oi = (y * w + x) * 4;
              // Red from left
              const rx = Math.max(0, x - chanOffset);
              const ri = (y * w + rx) * 4;
              // Blue from right
              const bx = Math.min(w - 1, x + chanOffset);
              const bi = (y * w + bx) * 4;

              rd[oi] = sd[ri]; // R from offset left
              rd[oi + 1] = sd[oi + 1]; // G from center
              rd[oi + 2] = sd[bi + 2]; // B from offset right
              rd[oi + 3] = 255;

              // Copy to the row below (skipped row)
              if (y + 1 < h) {
                const oi2 = ((y + 1) * w + x) * 4;
                rd[oi2] = rd[oi];
                rd[oi2 + 1] = rd[oi + 1];
                rd[oi2 + 2] = rd[oi + 2];
                rd[oi2 + 3] = 255;
              }
            }
          }

          // Scrolling noise band
          noiseBandY = (noiseBandY + 1.5) % h;
          const bandHeight = 6;
          const bandStartY = Math.floor(noiseBandY);
          for (let y = bandStartY; y < Math.min(bandStartY + bandHeight, h); y++) {
            // Horizontal shift for the strip below the noise
            const stripShift = Math.floor(Math.random() * 12) - 6;
            for (let x = 0; x < w; x++) {
              const oi = (y * w + x) * 4;
              if (y < bandStartY + 2) {
                // Noise pixels: random bright static
                const v = 128 + Math.floor(Math.random() * 127);
                rd[oi] = v;
                rd[oi + 1] = v;
                rd[oi + 2] = v;
                rd[oi + 3] = 255;
              } else {
                // Shifted strip
                const sx = Math.max(0, Math.min(w - 1, x + stripShift));
                const si = (y * w + sx) * 4;
                rd[oi] = sd[si];
                rd[oi + 1] = sd[si + 1];
                rd[oi + 2] = sd[si + 2];
                rd[oi + 3] = 255;
              }
            }
          }

          ctx.putImageData(result, 0, 0);
        }

        // -----------------------------------------------------------
        // NEON — Bloom pass (bright-only glow)
        // -----------------------------------------------------------
        if (p.name === "Neon") {
          // Copy current canvas to offscreen
          offCtx.clearRect(0, 0, w, h);
          offCtx.drawImage(canvas, 0, 0);

          // Threshold: keep only bright pixels
          const imgData = offCtx.getImageData(0, 0, w, h);
          const bd = imgData.data;
          // Process every 2nd pixel for performance
          for (let i = 0; i < bd.length; i += 8) {
            const lum = bd[i] * 0.299 + bd[i + 1] * 0.587 + bd[i + 2] * 0.114;
            if (lum < 120) {
              bd[i] = 0;
              bd[i + 1] = 0;
              bd[i + 2] = 0;
              bd[i + 3] = 0;
            }
            // Copy to next pixel
            if (i + 4 < bd.length) {
              const lum2 = bd[i + 4] * 0.299 + bd[i + 5] * 0.587 + bd[i + 6] * 0.114;
              if (lum2 < 120) {
                bd[i + 4] = 0;
                bd[i + 5] = 0;
                bd[i + 6] = 0;
                bd[i + 7] = 0;
              }
            }
          }
          offCtx.putImageData(imgData, 0, 0);

          // Draw thresholded bright image with blur onto main canvas
          ctx.save();
          ctx.filter = "blur(12px)";
          ctx.globalCompositeOperation = "lighter";
          ctx.globalAlpha = 0.6;
          ctx.drawImage(offscreen, 0, 0);
          ctx.restore();
        }

        // -----------------------------------------------------------
        // TRAP — Strobe flash + film grain
        // -----------------------------------------------------------
        if (p.name === "Trap") {
          // Strobe logic
          strobeCountdown++;
          if (strobeCountdown >= nextStrobeAt) {
            strobeTicks = 2;
            strobeCountdown = 0;
            nextStrobeAt = 18 + Math.floor(Math.random() * 7);
          }

          if (strobeTicks > 0) {
            strobeTicks--;
            // Flash: draw raw frame with high contrast/brightness over the dark base
            ctx.save();
            ctx.globalCompositeOperation = "source-over";
            ctx.filter = "contrast(1.8) brightness(1.5)";
            ctx.globalAlpha = 0.7;
            ctx.drawImage(main, 0, 0, w, h);
            ctx.restore();
          }

          // Film grain: tile the noise pattern with overlay blend
          ctx.save();
          ctx.globalCompositeOperation = "overlay";
          ctx.globalAlpha = 0.15;
          const pat = ctx.createPattern(noiseTile, "repeat");
          if (pat) {
            ctx.fillStyle = pat;
            ctx.fillRect(0, 0, w, h);
          }
          ctx.restore();
        }

        // -----------------------------------------------------------
        // DIFF — Motion accumulation + color mapping
        // -----------------------------------------------------------
        if (p.name === "Diff" && accumCtx) {
          // Fade accumulation
          accumCtx.save();
          accumCtx.globalCompositeOperation = "source-over";
          accumCtx.fillStyle = "rgba(0, 0, 0, 0.06)";
          accumCtx.fillRect(0, 0, w, h);
          accumCtx.restore();

          // Draw current difference result onto accumulation
          accumCtx.save();
          accumCtx.globalCompositeOperation = "lighter";
          accumCtx.globalAlpha = 0.3;
          accumCtx.drawImage(canvas, 0, 0);
          accumCtx.restore();

          // Color mapping: luminance to heat ramp
          const accumData = accumCtx.getImageData(0, 0, w, h);
          const ad = accumData.data;
          // Process every 2nd pixel for performance
          for (let i = 0; i < ad.length; i += 8) {
            const lum = ad[i] * 0.299 + ad[i + 1] * 0.587 + ad[i + 2] * 0.114;
            let r = 0,
              g = 0,
              b = 0;
            if (lum < 30) {
              r = 0;
              g = 0;
              b = 0;
            } else if (lum < 80) {
              // Blue
              r = 0;
              g = 0;
              b = Math.floor((lum / 80) * 255);
            } else if (lum < 150) {
              // Green to yellow
              const t = (lum - 80) / 70;
              r = Math.floor(t * 200);
              g = Math.floor(150 + t * 105);
              b = 0;
            } else if (lum < 220) {
              // Orange to red
              const t = (lum - 150) / 70;
              r = 200 + Math.floor(t * 55);
              g = Math.floor(150 * (1 - t));
              b = 0;
            } else {
              // White hot
              r = 255;
              g = 255;
              b = 255;
            }
            ad[i] = r;
            ad[i + 1] = g;
            ad[i + 2] = b;
            ad[i + 3] = lum > 15 ? 200 : 0;
            // Copy to next pixel
            if (i + 4 < ad.length) {
              ad[i + 4] = r;
              ad[i + 5] = g;
              ad[i + 6] = b;
              ad[i + 7] = lum > 15 ? 200 : 0;
            }
          }
          accumCtx.putImageData(accumData, 0, 0);

          // Draw color-mapped motion history onto main canvas
          ctx.save();
          ctx.globalCompositeOperation = "screen";
          ctx.globalAlpha = 0.6;
          ctx.drawImage(accumCanvas, 0, 0);
          ctx.restore();
        }
      }
    };

    fetchFrame();
    const fetchTimer = setInterval(fetchFrame, FETCH_INTERVAL);
    const renderTimer = setInterval(render, RENDER_INTERVAL);

    return () => {
      running = false;
      clearInterval(fetchTimer);
      clearInterval(renderTimer);
    };
  }, [role, isHero]); // Re-mount when camera role or hero status changes

  return (
    <canvas
      ref={canvasRef}
      className={className ?? "h-full w-full bg-black object-contain"}
    />
  );
}
