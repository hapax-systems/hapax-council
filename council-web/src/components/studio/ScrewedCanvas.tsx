import { useEffect, useRef } from "react";

interface Props {
  role: string;
  className?: string;
}

export function ScrewedCanvas({ role, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let running = true;
    let pending = false;
    const frameRing: HTMLImageElement[] = [];
    const RING_SIZE = 16;
    let writeHead = 0;

    let displayIdx = 0;
    let tick = 0;
    let holdTicks = 0;
    let phase: "play" | "freeze" | "replay" = "play";
    let freezeFor = 0;
    let replayFrom = 0;
    let replayStep = 0;

    const fetchFrame = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      loader.crossOrigin = "anonymous";
      loader.onload = () => {
        if (!running) { pending = false; return; }
        frameRing[writeHead % RING_SIZE] = loader;
        writeHead++;
        if (canvas.width !== loader.naturalWidth) {
          canvas.width = loader.naturalWidth;
          canvas.height = loader.naturalHeight;
        }
        pending = false;
      };
      loader.onerror = () => { pending = false; };
      loader.src = `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };

    const render = () => {
      if (!running) return;
      const w = canvas.width;
      const h = canvas.height;
      if (w === 0) return;
      const available = Math.min(writeHead, RING_SIZE);
      if (available < 3) return;

      tick++;

      if (phase === "play") {
        displayIdx = (writeHead - 1) % RING_SIZE;
        if (tick % 10 === 0 && Math.random() < 0.50) {
          phase = "freeze";
          freezeFor = 3 + Math.floor(Math.random() * 8);
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
          displayIdx = (replayFrom - 3 + replayStep + RING_SIZE * 10) % RING_SIZE;
          if (replayStep >= 3) {
            phase = "play";
          }
        }
      }

      const idx = Math.abs(displayIdx) % available;
      ctx.clearRect(0, 0, w, h);

      // Ghost trails — purple-filtered older frames drifting down
      for (let g = 3; g >= 1; g--) {
        const gi = (idx - g * 2 + available * 100) % available;
        const ghost = frameRing[gi];
        if (!ghost) continue;
        ctx.save();
        ctx.filter = "saturate(0.3) brightness(0.5) sepia(0.6) hue-rotate(250deg)";
        ctx.globalAlpha = 0.18 + (3 - g) * 0.1;
        ctx.drawImage(ghost, g * 0.7, g * 6, w, h);
        ctx.restore();
      }

      // Main frame — SINGLE draw with screwed filter
      const main = frameRing[idx];
      if (main) {
        ctx.save();
        ctx.filter = "saturate(0.55) sepia(0.4) hue-rotate(250deg) contrast(1.05) brightness(0.9)";
        ctx.drawImage(main, 0, 0, w, h);
        ctx.restore();
      }

      // Syrup gradient
      ctx.save();
      ctx.filter = "none";
      const grad = ctx.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, "rgba(50, 15, 70, 0.0)");
      grad.addColorStop(0.5, "rgba(60, 20, 80, 0.1)");
      grad.addColorStop(1, "rgba(40, 10, 60, 0.25)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
      ctx.restore();

      // Vignette
      const vig = ctx.createRadialGradient(w / 2, h / 2, w * 0.3, w / 2, h / 2, w * 0.7);
      vig.addColorStop(0, "rgba(0,0,0,0)");
      vig.addColorStop(1, "rgba(0,0,0,0.3)");
      ctx.fillStyle = vig;
      ctx.fillRect(0, 0, w, h);

      // Band displacement
      if (Math.random() < 0.18 && main) {
        const bandY = Math.floor(Math.random() * h * 0.6) + h * 0.2;
        const bandH = 4 + Math.floor(Math.random() * 16);
        const shift = (Math.random() > 0.5 ? 1 : -1) * (5 + Math.random() * 15);
        ctx.save();
        ctx.filter = "saturate(0.55) sepia(0.4) hue-rotate(250deg) contrast(1.05) brightness(0.9)";
        ctx.beginPath();
        ctx.rect(0, bandY, w, bandH);
        ctx.clip();
        ctx.drawImage(main, shift, 0, w, h);
        ctx.restore();
      }

      // Freeze indicator
      if (phase === "freeze") {
        ctx.fillStyle = "rgba(80, 30, 120, 0.18)";
        ctx.fillRect(0, 0, w, h);
      }
    };

    fetchFrame();
    const fetchTimer = setInterval(fetchFrame, 100);
    const renderTimer = setInterval(render, 70);

    return () => {
      running = false;
      clearInterval(fetchTimer);
      clearInterval(renderTimer);
    };
  }, [role]);

  return (
    <canvas
      ref={canvasRef}
      className={className ?? "h-full w-full bg-black object-contain"}
    />
  );
}
