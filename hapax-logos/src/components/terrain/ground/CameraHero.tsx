import { useCallback, useRef } from "react";
import { useSnapshotPoll } from "../../../hooks/useSnapshotPoll";
import { DetectionOverlay } from "../../studio/DetectionOverlay";
import { useStudio } from "../../../api/hooks";
import type { ClassificationDetection } from "../../../api/types";

interface CameraHeroProps {
  heroRole: string;
  classificationDetections: ClassificationDetection[];
  onHeroChange: (role: string) => void;
  fxMode?: boolean;
  smoothMode?: boolean;
}

export function CameraHero({
  heroRole,
  classificationDetections,
  onHeroChange,
  fxMode,
  smoothMode,
}: CameraHeroProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const snapshotUrl = fxMode
    ? "/api/studio/stream/fx"
    : `/api/studio/stream/camera/${heroRole}`;
  const { imgRef, isStale } = useSnapshotPoll(snapshotUrl, 83); // ~12fps

  const { data: studio } = useStudio();
  const cameras = studio?.compositor ? Object.keys(studio.compositor.cameras) : [];
  const secondaryCameras = cameras.filter((r) => r !== heroRole);

  const handleDoubleClick = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen();
  }, []);

  // HLS mode: render video element instead of snapshot
  if (smoothMode) {
    return (
      <div ref={containerRef} className="relative h-full w-full" onDoubleClick={handleDoubleClick}>
        <HlsPlayer />
        {/* Camera role label */}
        <div className="absolute left-2 top-2 z-20 rounded bg-black/60 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
          {heroRole} {fxMode && "· FX"} {smoothMode && "· HLS"}
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
        cameraRole={fxMode ? undefined : heroRole}
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
        {heroRole} {fxMode && "· FX"}
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
  const { imgRef } = useSnapshotPoll(`/api/studio/stream/camera/${role}`, 1000);

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
  // Dynamic import to avoid bundling hls.js when not needed
  const hlsRef = useRef<import("hls.js").default | null>(null);

  // Initialize HLS on mount
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
      liveMaxLatencyDurationCount: 5,
      maxBufferLength: 10,
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
