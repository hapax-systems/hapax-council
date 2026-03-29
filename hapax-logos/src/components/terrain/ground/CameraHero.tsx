import { useCallback, useEffect, useRef } from "react";
import { useSnapshotPoll } from "../../../hooks/useSnapshotPoll";
import { useBatchSnapshot } from "../../../hooks/useBatchSnapshotPoll";
import { DetectionOverlay } from "../../studio/DetectionOverlay";
import { SceneBadges } from "../../studio/SceneBadges";
import { sourceUrl, selectEffect } from "../../studio/effectSources";
import { useStudio } from "../../../api/hooks";
import { useDetections } from "../../../contexts/ClassificationOverlayContext";
import type { ClassificationDetection } from "../../../api/types";
import type { DetectionTier } from "../../studio/DetectionOverlay";

interface CameraHeroProps {
  heroRole: string;
  classificationDetections: ClassificationDetection[];
  onHeroChange: (role: string) => void;
  effectSourceId?: string;
  smoothMode?: boolean;
}

export function CameraHero({
  heroRole,
  classificationDetections,
  onHeroChange,
  effectSourceId = "camera",
  smoothMode,
}: CameraHeroProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { detectionTier, detectionLayerVisible, enrichmentVisibility } = useDetections();
  const heroTier = Math.max(detectionTier, 2) as DetectionTier; // hero always >= tier 2
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

  const modeLabel = [
    heroRole,
    smoothMode ? "HLS" : null,
    effectUrl ? effectSourceId : null,
  ].filter(Boolean).join(" · ");

  if (smoothMode) {
    return (
      <div ref={containerRef} className="flex flex-col h-full w-full" onDoubleClick={handleDoubleClick}>
        <div className="relative flex-1 min-h-0">
          {/* HLS layer — primary display */}
          <div className="absolute inset-0 z-0">
            <HlsPlayer enabled />
          </div>
          <DetectionOverlay
            containerRef={containerRef}
            cameraRole={heroRole}
            classificationDetections={classificationDetections}
            tier={heroTier}
            visible={detectionLayerVisible}
            objectFit="cover"
            enrichmentVisibility={enrichmentVisibility}
          />
          <div className="absolute left-2 top-2 z-20 rounded bg-black/60 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
            {modeLabel}
          </div>
          <SceneBadges />
        </div>
        {secondaryCameras.length > 0 && (
          <SecondaryStrip cameras={secondaryCameras} onSelect={onHeroChange} />
        )}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex flex-col h-full w-full" onDoubleClick={handleDoubleClick}>
      {/* Live mode: snapshot feed */}
      <div className="relative flex-1 min-h-0 bg-black">
        {/* Placeholder shown until first frame */}
        <div className="absolute inset-0 flex items-center justify-center z-0">
          <span className="text-[11px] text-zinc-700 animate-pulse">connecting...</span>
        </div>
        <img
          ref={imgRef}
          className="h-full w-full object-cover relative z-[1]"
          alt={heroRole}
        />
        <DetectionOverlay
          containerRef={containerRef}
          cameraRole={effectUrl ? undefined : heroRole}
          classificationDetections={classificationDetections}
          tier={heroTier}
          visible={detectionLayerVisible}
          objectFit="cover"
          enrichmentVisibility={enrichmentVisibility}
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
        <SceneBadges />
      </div>
      {/* Secondary camera strip -- edge-to-edge at the bottom */}
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
  const { imgRef } = useBatchSnapshot(role, 100); // 10fps secondary thumbnails

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

/** HLS player that stays alive across mode toggles.
 *  The `enabled` prop controls when the HLS instance is first created.
 *  Once created, it persists until the component fully unmounts.
 */
function HlsPlayer({ enabled = true }: { enabled?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const video = videoRef.current;
    if (!video) return;
    // Already initialized -- don't re-create
    if (hlsRef.current) return;

    let destroyed = false;
    let revealTimer: ReturnType<typeof setTimeout> | undefined;

    // Start hidden until first frame is buffered -- prevents initial black flash
    video.style.opacity = "0";
    video.style.transition = "opacity 0.3s ease-in";

    const url = "http://localhost:8051/api/studio/hls/stream.m3u8";

    (async () => {
      const Hls = (await import("hls.js")).default;
      if (destroyed || !Hls.isSupported()) return;
      const hls = new Hls({
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 6,
        maxBufferLength: 10,
        backBufferLength: 10,
        enableWorker: true,
        lowLatencyMode: false,
        liveDurationInfinity: false,
        maxBufferHole: 0.5,
      });
      hlsRef.current = hls;
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {});
      });
      // Reveal video once first fragment is buffered and decoded
      hls.on(Hls.Events.FRAG_BUFFERED, () => {
        if (video.readyState >= 3 && video.style.opacity === "0") {
          video.style.opacity = "1";
        }
      });
      // Fallback: reveal after 5s in case FRAG_BUFFERED never fires
      revealTimer = setTimeout(() => {
        if (!destroyed && video.style.opacity === "0") video.style.opacity = "1";
      }, 5000);
      hls.on(Hls.Events.ERROR, (_event: string, data: any) => {
        // bufferStalledError is non-fatal -- hls.js handles via internal nudge mechanism.
        // Calling recoverMediaError() here resets MediaSource and causes black-frame blink.
        if (data.details === "bufferStalledError") return;
        if (data.fatal) {
          if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
            hls.recoverMediaError();
          } else {
            hls.stopLoad();
            setTimeout(() => {
              if (!destroyed) {
                hls.loadSource(url);
                hls.startLoad();
              }
            }, 3000);
          }
        }
      });
    })();

    return () => {
      destroyed = true;
      clearTimeout(revealTimer);
      hlsRef.current?.destroy();
      hlsRef.current = null;
    };
  }, [enabled]);

  return (
    <video
      ref={videoRef}
      className="absolute inset-0 h-full w-full bg-black object-cover"
      style={{ willChange: "transform" }}
      autoPlay
      muted
      playsInline
      poster="http://localhost:8051/api/studio/stream/fx"
    />
  );
}
