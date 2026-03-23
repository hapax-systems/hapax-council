import { useRef, useState } from "react";
import { useBatchSnapshot } from "../../../hooks/useBatchSnapshotPoll";
import { DetectionOverlay } from "../../studio/DetectionOverlay";
import { useStudio } from "../../../api/hooks";
import { useDetections } from "../../../contexts/ClassificationOverlayContext";
import type { ClassificationDetection } from "../../../api/types";

interface CameraTileProps {
  role: string;
  classificationDetections: ClassificationDetection[];
  status: string;
  recording: boolean;
  onClick: () => void;
}

function CameraTile({ role, classificationDetections, status, recording, onClick }: CameraTileProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { detectionTier, detectionLayerVisible, enrichmentVisibility } = useDetections();
  const { imgRef, isStale } = useBatchSnapshot(role, 100); // 10fps — smooth enough for grid tiles
  const [loaded, setLoaded] = useState(false);

  const borderColor = recording
    ? "border-red-500/80 animate-pulse"
    : isStale
      ? "border-amber-500/60"
      : status === "active"
        ? "border-green-500/30"
        : "border-zinc-700";

  return (
    <div
      ref={containerRef}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`relative cursor-pointer overflow-hidden rounded-lg border-2 ${borderColor} transition-colors bg-zinc-900`}
    >
      {/* Placeholder behind img — visible until first frame loads */}
      {!loaded && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-[10px] text-zinc-700 animate-pulse">connecting...</span>
        </div>
      )}
      <img
        ref={imgRef}
        className={`h-full w-full object-cover transition-opacity duration-500 ${loaded ? "opacity-100" : "opacity-0"}`}
        onLoad={() => setLoaded(true)}
        alt={role}
      />
      <DetectionOverlay
        containerRef={containerRef}
        cameraRole={role}
        classificationDetections={classificationDetections}
        tier={detectionTier}
        visible={detectionLayerVisible}
        objectFit="cover"
        enrichmentVisibility={enrichmentVisibility}
      />
      {/* Camera role label */}
      <div className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-zinc-300">
        {role}
      </div>
    </div>
  );
}

interface CameraGridProps {
  classificationDetections: ClassificationDetection[];
  onSelectHero: (role: string) => void;
}

export function CameraGrid({ classificationDetections, onSelectHero }: CameraGridProps) {
  const { data: studio } = useStudio();
  const compositor = studio?.compositor;
  const cameras = compositor ? Object.entries(compositor.cameras) : [];
  const recordingCams = compositor?.recording_cameras ?? {};
  const isRecording = compositor?.recording_enabled ?? false;

  if (cameras.length === 0) {
    return (
      <div className="flex h-full flex-col gap-2">
        <div className="grid flex-1 grid-cols-2 gap-2">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="relative overflow-hidden rounded-lg border-2 border-zinc-800 pointer-events-none bg-zinc-900"
            >
              <div className="flex h-full w-full items-center justify-center aspect-video">
                <span className="text-[10px] text-zinc-700 animate-pulse">connecting...</span>
              </div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 px-1 text-[10px] text-zinc-600 animate-pulse">
          waiting for compositor
        </div>
      </div>
    );
  }

  // Status summary line
  const activeCams = cameras.filter(([, s]) => s === "active").length;
  const recCount = Object.values(recordingCams).filter((s) => s === "active").length;
  const consentLabel =
    compositor?.consent_phase === "consent_refused"
      ? "Refused"
      : compositor?.consent_phase === "consent_pending"
        ? "Pending"
        : compositor?.consent_phase === "guest_detected"
          ? "Guest"
          : "OK";

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="grid flex-1 grid-cols-2 gap-2">
        {cameras.map(([role, status]) => (
          <CameraTile
            key={role}
            role={role}
            classificationDetections={classificationDetections}
            status={status}
            recording={isRecording && recordingCams[role] === "active"}
            onClick={() => onSelectHero(role)}
          />
        ))}
      </div>
      {/* Status summary strip */}
      <div className="flex items-center gap-3 px-1 text-[10px] text-zinc-500">
        <span>
          {activeCams}/{cameras.length} cams
        </span>
        {isRecording && (
          <span className="text-red-400">
            REC {recCount > 0 && `${recCount}`}
          </span>
        )}
        <span>Consent {consentLabel}</span>
      </div>
    </div>
  );
}
