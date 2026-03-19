import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Maximize, Minimize, GripVertical } from "lucide-react";
import { acquireImage, releaseImage } from "../../hooks/useImagePool";
import { DetectionOverlay, type DetectionTier } from "./DetectionOverlay";
import type { ClassificationDetection } from "../../api/types";

interface Props {
  cameraOrder: string[];
  onReorder: (order: string[]) => void;
  onFocusCamera: (role: string) => void;
  classificationDetections?: ClassificationDetection[];
  detectionTier?: DetectionTier;
  detectionsVisible?: boolean;
}

export function StudioLiveGrid({
  cameraOrder,
  onReorder,
  onFocusCamera,
  classificationDetections = [],
  detectionTier = 1,
  detectionsVisible = true,
}: Props) {
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
  const handleDragEnd = () => {
    setDragIdx(null);
    setOverIdx(null);
  };

  if (cameraOrder.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-zinc-600">
        No cameras connected — start the compositor to enable studio.
      </div>
    );
  }

  const hero = cameraOrder[0];
  const others = cameraOrder.slice(1);

  return (
    <div className="flex h-full gap-1">
      <CameraCell
        role={hero}
        isHero
        idx={0}
        dragIdx={dragIdx}
        overIdx={overIdx}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onDragEnd={handleDragEnd}
        onFocus={onFocusCamera}
        classificationDetections={classificationDetections}
        detectionTier={detectionTier}
        detectionsVisible={detectionsVisible}
      />
      {others.length > 0 && (
        <div className="flex w-1/3 flex-col gap-1">
          {others.map((role, i) => (
            <CameraCell
              key={role}
              role={role}
              idx={i + 1}
              dragIdx={dragIdx}
              overIdx={overIdx}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onDragEnd={handleDragEnd}
              onFocus={onFocusCamera}
              classificationDetections={classificationDetections}
              detectionTier={detectionTier}
              detectionsVisible={detectionsVisible}
            />
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
  classificationDetections?: ClassificationDetection[];
  detectionTier?: DetectionTier;
  detectionsVisible?: boolean;
}

function CameraCell({
  role,
  isHero,
  idx,
  dragIdx,
  overIdx,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onFocus,
  classificationDetections = [],
  detectionTier = 1,
  detectionsVisible = true,
}: CameraCellProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const cellRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const lastSuccess = useRef(0);
  const [isStale, setIsStale] = useState(false);

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

  // Live feed snapshot pull
  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    let running = true;
    let pending = false;
    let currentLoader: HTMLImageElement | null = null;

    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = acquireImage();
      currentLoader = loader;
      loader.onload = () => {
        if (running && img) img.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
        pending = false;
        releaseImage(loader);
        currentLoader = null;
      };
      loader.onerror = () => {
        pending = false;
        releaseImage(loader);
        currentLoader = null;
      };
      loader.src = `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };
    pull();
    lastSuccess.current = Date.now();
    const rate = isHero ? 80 : 120;
    const timer = setInterval(pull, rate);
    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 10_000) setIsStale(true);
    }, 2_000);
    return () => {
      running = false;
      clearInterval(timer);
      clearInterval(staleTimer);
      if (currentLoader) {
        releaseImage(currentLoader);
        currentLoader = null;
      }
    };
  }, [role, isHero]);

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
        isFullscreen
          ? "flex items-center justify-center bg-black"
          : isDragging
            ? "scale-[0.97] opacity-50"
            : isOver
              ? "ring-2 ring-purple-500/60"
              : ""
      }`}
    >
      <img
        ref={imgRef}
        alt={role}
        crossOrigin="anonymous"
        className={`bg-black ${isFullscreen ? "max-h-screen max-w-full object-contain" : "h-full w-full object-cover"}`}
      />

      {/* Classification detection overlay */}
      <DetectionOverlay
        containerRef={cellRef}
        cameraRole={role}
        classificationDetections={classificationDetections}
        tier={detectionTier}
        visible={detectionsVisible}
        objectFit={isFullscreen ? "contain" : "cover"}
      />

      {/* Labels + controls */}
      <div className="absolute left-1 top-1 z-20 flex items-center gap-1">
        <span className="rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-zinc-300 backdrop-blur-sm">
          {role}
        </span>
        {isStale && (
          <span className="flex items-center gap-0.5 rounded bg-amber-900/80 px-1.5 py-0.5 text-[9px] font-medium text-amber-200 backdrop-blur-sm">
            <AlertTriangle className="h-2.5 w-2.5" />
            Stale
          </span>
        )}
      </div>
      <div className="absolute right-1 top-1 z-20 flex items-center gap-0.5">
        {!isFullscreen && (
          <div className="cursor-grab rounded bg-black/40 p-0.5 text-zinc-400 active:cursor-grabbing">
            <GripVertical className="h-3 w-3" />
          </div>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (isFullscreen) {
              toggleFullscreen();
            } else {
              onFocus(role);
            }
          }}
          className="rounded bg-black/40 p-0.5 text-zinc-400 hover:bg-black/70 hover:text-zinc-200"
          title={isFullscreen ? "Exit fullscreen" : "Solo this camera"}
        >
          {isFullscreen ? (
            <Minimize className="h-3 w-3" />
          ) : (
            <Maximize className="h-3 w-3" />
          )}
        </button>
      </div>
    </div>
  );
}
