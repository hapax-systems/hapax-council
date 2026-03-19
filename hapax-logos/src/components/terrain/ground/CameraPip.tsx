import { useRef } from "react";
import { useBatchSnapshot } from "../../../hooks/useBatchSnapshotPoll";
import { DetectionOverlay } from "../../studio/DetectionOverlay";
import type { ClassificationDetection } from "../../../api/types";

interface CameraPipProps {
  heroRole: string;
  classificationDetections: ClassificationDetection[];
  onClick?: () => void;
}

export function CameraPip({ heroRole, classificationDetections, onClick }: CameraPipProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { imgRef, isStale } = useBatchSnapshot(heroRole, 16); // 60fps ambient pip

  return (
    <div
      ref={containerRef}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      className="relative cursor-pointer overflow-hidden rounded-md transition-opacity duration-500"
      style={{
        width: 120,
        height: 68,
        opacity: isStale ? 0.3 : 0.6,
        filter: "sepia(0.3) contrast(0.8) brightness(0.7)",
      }}
    >
      <img
        ref={imgRef}
        className="h-full w-full object-cover"
        alt={heroRole}
      />
      <DetectionOverlay
        containerRef={containerRef}
        cameraRole={heroRole}
        classificationDetections={classificationDetections}
        tier={1}
        visible={true}
        objectFit="cover"
      />
      {/* Camera role label */}
      <div className="absolute bottom-0.5 left-1 rounded bg-black/60 px-1 py-px text-[8px] text-zinc-400">
        {heroRole.replace("brio-", "").replace("c920-", "")}
      </div>
    </div>
  );
}
