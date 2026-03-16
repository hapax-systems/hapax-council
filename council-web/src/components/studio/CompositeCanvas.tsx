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
      ctx.clearRect(0, 0, w, h);

      // --- Ghost trails ---
      // Space ghost frames further apart for visible temporal difference
      const trail = p.trail;
      const trailSpacing = Math.max(3, Math.floor(available / (trail.count + 1)));
      for (let g = trail.count; g >= 1; g--) {
        const gi = (idx - g * trailSpacing + available * 100) % available;
        const ghost = frameRing[gi];
        if (!ghost) continue;
        ctx.save();
        // For Neon preset, rotate hue on trail filter
        let trailFilter = trail.filter;
        if (trailFilter !== "none" && p.name === "Neon") {
          trailFilter = `${trailFilter} hue-rotate(${hueAccum}deg)`;
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

      // Vignette
      if (fx.vignette) {
        const vig = ctx.createRadialGradient(w / 2, h / 2, w * 0.3, w / 2, h / 2, w * 0.7);
        vig.addColorStop(0, "rgba(0,0,0,0)");
        vig.addColorStop(1, `rgba(0,0,0,${fx.vignetteStrength})`);
        ctx.fillStyle = vig;
        ctx.fillRect(0, 0, w, h);
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
    };

    fetchFrame();
    const fetchTimer = setInterval(fetchFrame, FETCH_INTERVAL);
    const renderTimer = setInterval(render, RENDER_INTERVAL);

    return () => {
      running = false;
      clearInterval(fetchTimer);
      clearInterval(renderTimer);
    };
  }, [role]); // Only re-mount when camera role changes

  return (
    <canvas
      ref={canvasRef}
      className={className ?? "h-full w-full bg-black object-contain"}
    />
  );
}
