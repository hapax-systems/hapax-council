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
  const batchResult = useBatchSnapshot(heroRole, 67);
  const fxResult = useSnapshotPoll(effectUrl ?? "/api/studio/stream/fx", 67, !!effectUrl);
  const { imgRef, isStale } = effectUrl ? fxResult : batchResult;

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
      <div ref={containerRef} className="relative h-full w-full" onDoubleClick={handleDoubleClick}>
        <CompositeCanvas
          role={heroRole}
          preset={preset}
          className="h-full w-full bg-black object-cover"
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
          {heroRole} · {preset.name}{effectUrl ? ` · ${effectSourceId}` : ""}
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
      <div ref={containerRef} className="relative h-full w-full" onDoubleClick={handleDoubleClick}>
        <HlsPlayer />
        {/* Camera role label */}
        <div className="absolute left-2 top-2 z-20 rounded bg-black/60 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
          {heroRole} · HLS
        </div>
        {/* Secondary strip */}
        {secondaryCameras.length > 0 && (
          <SecondaryStrip cameras={secondaryCameras} onSelect={onHeroChange} />
        )}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative h-full w-full" onDoubleClick={handleDoubleClick}>
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
      {/* Secondary camera strip */}
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
    <div className="absolute bottom-2 left-2 z-20 flex gap-1.5">
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
      className="overflow-hidden rounded border border-zinc-700 transition-colors hover:border-zinc-400"
      style={{ width: 48, height: 27 }}
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
      liveSyncDurationCount: 1,
      liveMaxLatencyDurationCount: 3,
      maxBufferLength: 2,
      backBufferLength: 0,
    });
    hlsRef.current = hls;
    hls.loadSource("/api/studio/hls/stream.m3u8");
    hls.attachMedia(node);
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      node.play().catch(() => {});
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
    />
  );
}
