import { useEffect, useRef } from "react";
import { acquireImage, releaseImage } from "../../hooks/useImagePool";
import { ZoneOverlay } from "./ZoneOverlay";
import {
  SIGNAL_CATEGORIES,
  type SignalCategory,
  useSignals,
  useOverlayControl,
} from "../../contexts/ClassificationOverlayContext";
import type { SignalEntry } from "../../api/types";

interface PerceptionCanvasProps {
  activeZone: SignalCategory | null;
  onZoneClick: (cat: SignalCategory) => void;
}

export function PerceptionCanvas({ activeZone, onZoneClick }: PerceptionCanvasProps) {
  const { visualLayer, filteredSignals } = useSignals();
  const { zoneOpacityOverrides } = useOverlayControl();
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Poll compositor snapshot
  useEffect(() => {
    let running = true;
    let pending = false;
    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = acquireImage();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
        releaseImage(loader);
        pending = false;
      };
      loader.onerror = () => {
        releaseImage(loader);
        pending = false;
      };
      loader.src = `/api/studio/stream/snapshot?_t=${Date.now()}`;
    };
    pull();
    const timer = setInterval(pull, 100); // 10fps compositor snapshot
    return () => {
      running = false;
      clearInterval(timer);
    };
  }, []);

  const zoneOpacities = visualLayer?.zone_opacities ?? {};

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden rounded-lg bg-black">
      {/* Background: compositor snapshot */}
      <img
        ref={imgRef}
        className="h-full w-full object-contain"
        alt="Studio composite"
      />

      {/* Detection overlay disabled on composite — per-camera boxes can't map
         to the tiled composite layout. Individual camera feeds in the grid
         have their own DetectionOverlay instances with correct cameraRole. */}

      {/* Zone overlays */}
      {SIGNAL_CATEGORIES.map((cat) => {
        const signals: SignalEntry[] = filteredSignals[cat] ?? [];
        const baseOpacity = zoneOpacities[cat] ?? 0;
        const override = zoneOpacityOverrides[cat];
        const opacity = override !== undefined ? override : baseOpacity;

        return (
          <ZoneOverlay
            key={cat}
            category={cat}
            signals={signals}
            opacity={opacity}
            active={activeZone === cat}
            onClick={() => onZoneClick(cat)}
          />
        );
      })}
    </div>
  );
}
