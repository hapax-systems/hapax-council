import { useCallback, useEffect, useRef } from "react";
import { useSnapshotPoll } from "../../../hooks/useSnapshotPoll";
import { useBatchSnapshot } from "../../../hooks/useBatchSnapshotPoll";
import { DetectionOverlay } from "../../studio/DetectionOverlay";
import { CompositeCanvas } from "../../studio/CompositeCanvas";
import { PRESETS } from "../../studio/compositePresets";
import { sourceUrl, selectEffect } from "../../studio/effectSources";
import { useStudio } from "../../../api/hooks";
import type { ClassificationDetection } from "../../../api/types";

interface CameraHeroProps {
  heroRole: string;
  classificationDetections: ClassificationDetection[];
  onHeroChange: (role: string) => void;
  effectSourceId?: string;
  smoothMode?: boolean;
  compositeMode?: boolean;
  presetIdx?: number;
}

export function CameraHero({
  heroRole,
  classificationDetections,
  onHeroChange,
  effectSourceId = "camera",
  smoothMode,
  compositeMode,
  presetIdx = 0,
}: CameraHeroProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const effectUrl = sourceUrl(effectSourceId);
  // Tell compositor to switch effect when source changes
  useEffect(() => { selectEffect(effectSourceId); }, [effectSourceId]);
  // When an effect source is selected, use it as the live source for snapshots
  const batchResult = useBatchSnapshot(heroRole, 50);
  const fxResult = useSnapshotPoll(effectUrl ?? "/api/studio/stream/fx", 50, !!effectUrl);
  const { imgRef, isStale } = effectUrl ? fxResult : batchResult;

  // Pre-warm: eagerly fetch first frame so there's no blank/black initial state
  const prewarmed = useRef(false);
  useEffect(() => {
    if (prewarmed.current) return;
    prewarmed.current = true;
    const url = effectUrl
      ? `${effectUrl}${effectUrl.includes("?") ? "&" : "?"}_t=${Date.now()}`
      : `/api/studio/stream/cameras/batch?roles=${heroRole}&_t=${Date.now()}`;
    // For batch endpoint we just trigger the poll; for direct URL, pre-load into imgRef
    if (effectUrl) {
      const loader = new Image();
      loader.onload = () => {
        if (imgRef.current) imgRef.current.src = loader.src;
      };
      loader.src = url;
    }
  }, [effectUrl, heroRole, imgRef]);

  const { data: studio } = useStudio();
  const cameras = studio?.compositor ? Object.keys(studio.compositor.cameras) : [];
  const secondaryCameras = cameras.filter((r) => r !== heroRole);

  const handleDoubleClick = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen();
  }, []);

  // Composite mode: dual-ring-buffer canvas with temporal parallax
  if (compositeMode) {
    const preset = PRESETS[presetIdx] ?? PRESETS[0];
    // If a GPU effect source is selected, use it as the smooth (overlay) source
    const smoothSource = effectUrl ?? "/api/studio/stream/fx";
    return (
      <div ref={containerRef} className="flex flex-col h-full w-full" onDoubleClick={handleDoubleClick}>
        <div className="relative flex-1 min-h-0">
          {/* When HLS is also active, layer it behind composite at reduced opacity */}
          {smoothMode && (
            <div className="absolute inset-0 z-0 opacity-30">
              <HlsPlayer />
            </div>
          )}
          <CompositeCanvas
            role={heroRole}
            preset={preset}
            className={`h-full w-full bg-black object-cover ${smoothMode ? "relative z-10 mix-blend-screen" : ""}`}
            liveSource={effectUrl}
            smoothSource={smoothSource}
          />
          <DetectionOverlay
            containerRef={containerRef}
            cameraRole={heroRole}
            classificationDetections={classificationDetections}
            tier={2}
            visible={true}
            objectFit="cover"
            activePreset={preset.name}
          />
          {/* Camera role label */}
          <div className="absolute left-2 top-2 z-20 rounded bg-black/60 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
            {heroRole} · {preset.name}{smoothMode ? " · HLS" : ""}{effectUrl ? ` · ${effectSourceId}` : ""}
          </div>
        </div>
        {/* Secondary strip */}
        {secondaryCameras.length > 0 && (
          <SecondaryStrip cameras={secondaryCameras} onSelect={onHeroChange} />
        )}
      </div>
    );
  }

  // HLS mode: render video element instead of snapshot
  if (smoothMode) {
    return (
      <div ref={containerRef} className="flex flex-col h-full w-full" onDoubleClick={handleDoubleClick}>
        <div className="relative flex-1 min-h-0">
          <HlsPlayer />
          {/* Camera role label */}
          <div className="absolute left-2 top-2 z-20 rounded bg-black/60 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
            {heroRole} · HLS
          </div>
        </div>
        {/* Secondary strip */}
        {secondaryCameras.length > 0 && (
          <SecondaryStrip cameras={secondaryCameras} onSelect={onHeroChange} />
        )}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col h-full w-full" onDoubleClick={handleDoubleClick}>
      {/* Hero fills all available space above the thumbnail strip */}
      <div className="relative flex-1 min-h-0">
        <img
          ref={imgRef}
          className="h-full w-full bg-black object-cover"
          alt={heroRole}
        />
        <DetectionOverlay
          containerRef={containerRef}
          cameraRole={effectUrl ? undefined : heroRole}
          classificationDetections={classificationDetections}
          tier={2}
          visible={true}
          objectFit="cover"
        />
        {/* Staleness warning */}
        {isStale && (
          <div className="absolute inset-x-0 top-2 flex justify-center">
            <div className="rounded-full bg-amber-900/80 px-3 py-1 text-[11px] font-medium text-amber-200 backdrop-blur-sm">
              Camera stale
            </div>
          </div>
        )}
        {/* Camera role label */}
        <div className="absolute left-2 top-2 z-20 rounded bg-black/60 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
          {heroRole}{effectUrl ? ` · ${effectSourceId}` : ""}
        </div>
      </div>
      {/* Secondary camera strip — edge-to-edge at the bottom */}
      {secondaryCameras.length > 0 && (
        <SecondaryStrip cameras={secondaryCameras} onSelect={onHeroChange} />
      )}
    </div>
  );
}

/** Tiny thumbnails along the bottom edge for non-hero cameras. */
function SecondaryStrip({
  cameras,
  onSelect,
}: {
  cameras: string[];
  onSelect: (role: string) => void;
}) {
  return (
    <div className="z-20 flex gap-[3px] bg-black shrink-0" style={{ height: 36 }}>
      {cameras.map((role) => (
        <SecondaryThumb key={role} role={role} onClick={() => onSelect(role)} />
      ))}
    </div>
  );
}

function SecondaryThumb({ role, onClick }: { role: string; onClick: () => void }) {
  const { imgRef } = useBatchSnapshot(role, 250);

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="flex-1 min-w-0 overflow-hidden border border-zinc-700 transition-colors hover:border-zinc-400"
      title={role}
    >
      <img ref={imgRef} className="h-full w-full object-cover bg-black" alt={role} />
    </button>
  );
}

/** Simple HLS player for smooth mode. */
function HlsPlayer() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);

  const containerRef = useCallback(async (node: HTMLVideoElement | null) => {
    if (!node) {
      hlsRef.current?.destroy();
      hlsRef.current = null;
      return;
    }
    const Hls = (await import("hls.js")).default;
    if (!Hls.isSupported()) return;
    const hls = new Hls({
      liveSyncDurationCount: 3,
      liveMaxLatencyDurationCount: 30,
      maxBufferLength: 30,
      backBufferLength: 10,
      enableWorker: true,
      lowLatencyMode: false,
      liveDurationInfinity: true,  // treat as infinite live stream
    });
    hlsRef.current = hls;
    hls.loadSource("/api/studio/hls/stream.m3u8");
    hls.attachMedia(node);
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      node.play().catch(() => {});
    });
    // On buffer gap, skip forward smoothly instead of jumping
    hls.on(Hls.Events.ERROR, (_event: string, data: any) => {
      if (data.details === "bufferStalledError") {
        // Don't seek — just wait for buffer to refill
        return;
      }
      if (data.fatal) {
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls.recoverMediaError();
        } else {
          // Network error — retry after delay
          hls.destroy();
          setTimeout(() => containerRef(node), 3000);
        }
      }
    });
  }, []);

  return (
    <video
      ref={(node) => {
        (videoRef as React.MutableRefObject<HTMLVideoElement | null>).current = node;
        containerRef(node);
      }}
      className="h-full w-full bg-black object-cover"
      muted
      playsInline
      poster="/api/studio/stream/fx"
      onWaiting={(e) => {
        // When buffering, pause to hold last frame instead of showing black
        const v = e.currentTarget;
        if (v.readyState < 3) v.pause();
      }}
      onCanPlay={(e) => {
        // Resume when buffer is ready
        e.currentTarget.play().catch(() => {});
      }}
    />
  );
}
