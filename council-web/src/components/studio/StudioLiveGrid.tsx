import { useCallback, useEffect, useRef, useState } from "react";
import { Maximize, Minimize, GripVertical } from "lucide-react";
import type { CompositePreset } from "./compositePresets";
import { CompositeOverlay } from "./CompositeOverlays";
import "./studio-animations.css";

interface Props {
  cameraOrder: string[];
  onReorder: (order: string[]) => void;
  onFocusCamera: (role: string) => void;
  preset?: CompositePreset;
}

export function StudioLiveGrid({ cameraOrder, onReorder, onFocusCamera, preset }: Props) {
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);

  const handleDragStart = (idx: number) => setDragIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setOverIdx(idx);
  };
  const handleDrop = (idx: number) => {
    if (dragIdx !== null && dragIdx !== idx) {
      const next = [...cameraOrder];
      const [moved] = next.splice(dragIdx, 1);
      next.splice(idx, 0, moved);
      onReorder(next);
    }
    setDragIdx(null);
    setOverIdx(null);
  };
  const handleDragEnd = () => { setDragIdx(null); setOverIdx(null); };

  if (cameraOrder.length === 0) return null;

  const hero = cameraOrder[0];
  const others = cameraOrder.slice(1);

  return (
    <div className="flex h-full gap-1">
      <CameraCell role={hero} isHero idx={0} dragIdx={dragIdx} overIdx={overIdx}
        onDragStart={handleDragStart} onDragOver={handleDragOver}
        onDrop={handleDrop} onDragEnd={handleDragEnd}
        onFocus={onFocusCamera} preset={preset} />
      {others.length > 0 && (
        <div className="flex w-1/3 flex-col gap-1">
          {others.map((role, i) => (
            <CameraCell key={role} role={role} idx={i + 1}
              dragIdx={dragIdx} overIdx={overIdx}
              onDragStart={handleDragStart} onDragOver={handleDragOver}
              onDrop={handleDrop} onDragEnd={handleDragEnd}
              onFocus={onFocusCamera} preset={preset} />
          ))}
        </div>
      )}
    </div>
  );
}

interface CameraCellProps {
  role: string;
  isHero?: boolean;
  idx: number;
  dragIdx: number | null;
  overIdx: number | null;
  onDragStart: (idx: number) => void;
  onDragOver: (e: React.DragEvent, idx: number) => void;
  onDrop: (idx: number) => void;
  onDragEnd: () => void;
  onFocus: (role: string) => void;
  preset?: CompositePreset;
}

/** Capture current img pixels as a low-res data URL for trail frames. */
function captureFrame(img: HTMLImageElement, maxW = 480): string | null {
  if (!img.naturalWidth) return null;
  const scale = Math.min(1, maxW / img.naturalWidth);
  const w = Math.round(img.naturalWidth * scale);
  const h = Math.round(img.naturalHeight * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", 0.4);
}

function CameraCell({
  role, isHero, idx, dragIdx, overIdx,
  onDragStart, onDragOver, onDrop, onDragEnd, onFocus, preset,
}: CameraCellProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const cellRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const trailBuf = useRef<{ src: string; ts: number }[]>([]);
  const [trailFrames, setTrailFrames] = useState<{ src: string; age: number }[]>([]);

  const toggleFullscreen = useCallback(() => {
    const el = cellRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen();
  }, []);

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // Live feed pull
  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    let running = true;
    let pending = false;
    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      loader.onload = () => { if (running && img) img.src = loader.src; pending = false; };
      loader.onerror = () => { pending = false; };
      loader.src = `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };
    pull();
    const timer = setInterval(pull, isHero ? 80 : 120);
    return () => { running = false; clearInterval(timer); };
  }, [role, isHero]);

  // Trail capture — freeze pixels via canvas, auto-expire by age
  useEffect(() => {
    if (!preset) {
      trailBuf.current = [];
      queueMicrotask(() => setTrailFrames([]));
      return;
    }
    const count = preset.trail.count;
    const intervalMs = preset.trail.intervalMs;
    const maxAgeMs = preset.trail.maxAgeMs;
    let running = true;

    const timer = setInterval(() => {
      if (!running) return;
      const now = Date.now();
      const img = imgRef.current;

      // Expire old frames
      trailBuf.current = trailBuf.current.filter((f) => now - f.ts < maxAgeMs);

      // Capture new frame
      if (img) {
        const dataUrl = captureFrame(img, isHero ? 640 : 320);
        if (dataUrl) {
          trailBuf.current = [{ src: dataUrl, ts: now }, ...trailBuf.current].slice(0, count);
        }
      }

      // Update render state with age info
      setTrailFrames(
        trailBuf.current.map((f) => ({ src: f.src, age: (now - f.ts) / maxAgeMs }))
      );
    }, intervalMs);

    return () => {
      running = false;
      clearInterval(timer);
    };
  }, [role, isHero, !!preset, preset?.trail.count, preset?.trail.intervalMs, preset?.trail.maxAgeMs]); // eslint-disable-line react-hooks/exhaustive-deps

  const isDragging = dragIdx === idx;
  const isOver = overIdx === idx && dragIdx !== idx;

  return (
    <div
      ref={cellRef}
      draggable={!isFullscreen}
      onDragStart={() => onDragStart(idx)}
      onDragOver={(e) => onDragOver(e, idx)}
      onDrop={() => onDrop(idx)}
      onDragEnd={onDragEnd}
      onDoubleClick={toggleFullscreen}
      className={`relative flex-1 overflow-hidden rounded-lg transition-all ${
        preset?.cellAnimation ?? ""
      } ${
        isFullscreen ? "flex items-center justify-center bg-black"
          : isDragging ? "scale-[0.97] opacity-50"
          : isOver ? "ring-2 ring-purple-500/60" : ""
      }`}
      style={preset ? { isolation: "isolate" } : undefined}
    >
      {/* Live layer */}
      <img
        ref={imgRef}
        alt={role}
        crossOrigin="anonymous"
        className={`bg-black object-contain ${isFullscreen ? "max-h-screen max-w-full" : "h-full w-full"}`}
        style={preset?.liveFilter && preset.liveFilter !== "none" ? { filter: preset.liveFilter } : undefined}
      />

      {/* Trail layers — frozen past frames, opacity fades with age */}
      {preset && trailFrames.map((frame, i) => (
        <img
          key={i}
          src={frame.src}
          alt=""
          className="pointer-events-none absolute inset-0 h-full w-full object-contain"
          style={{
            mixBlendMode: preset.trail.blendMode as React.CSSProperties["mixBlendMode"],
            opacity: preset.trail.opacity * (1 - frame.age),
            filter: preset.trail.filter !== "none" ? preset.trail.filter : undefined,
          }}
        />
      ))}

      {/* Preset overlays */}
      {preset?.overlays.map((ov) => (
        <CompositeOverlay key={ov} type={ov} />
      ))}

      {/* Labels + controls */}
      <div className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-zinc-300 backdrop-blur-sm">
        {role}
      </div>
      <div className="absolute right-1 top-1 flex items-center gap-0.5">
        {!isFullscreen && (
          <div className="cursor-grab rounded bg-black/40 p-0.5 text-zinc-400 active:cursor-grabbing">
            <GripVertical className="h-3 w-3" />
          </div>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); if (isFullscreen) { toggleFullscreen(); } else { onFocus(role); } }}
          className="rounded bg-black/40 p-0.5 text-zinc-400 hover:bg-black/70 hover:text-zinc-200"
          title={isFullscreen ? "Exit fullscreen" : "Solo this camera"}
        >
          {isFullscreen ? <Minimize className="h-3 w-3" /> : <Maximize className="h-3 w-3" />}
        </button>
      </div>
    </div>
  );
}
