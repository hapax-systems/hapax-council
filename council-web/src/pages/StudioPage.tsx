import { useState } from "react";
import { StudioStream } from "../components/studio/StudioStream";
import {
  StudioStatusGrid,
  CameraSoloView,
} from "../components/studio/StudioStatusGrid";
import { useStudio } from "../api/hooks";

export function StudioPage() {
  const { data: studio } = useStudio();
  const compositor = studio?.compositor;
  const [focusedCamera, setFocusedCamera] = useState<string | null>(null);

  return (
    <div className="flex flex-1 flex-col gap-2 overflow-hidden p-3">
      {/* Header bar */}
      <div className="flex shrink-0 items-center justify-between">
        <h1 className="text-sm font-semibold text-zinc-100">Studio</h1>
        {compositor && compositor.state !== "unknown" && (
          <span className="text-[10px] text-zinc-500">
            {compositor.resolution} · {compositor.active_cameras}/
            {compositor.total_cameras} cameras
            {compositor.hls_enabled && " · HLS"}
            {compositor.recording_enabled && " · REC"}
          </span>
        )}
      </div>

      {/* Stream area — fills available space */}
      <div className="min-h-0 flex-1">
        {focusedCamera ? (
          <CameraSoloView
            role={focusedCamera}
            onClose={() => setFocusedCamera(null)}
          />
        ) : (
          <StudioStream />
        )}
      </div>

      {/* Camera status bar — always visible at bottom */}
      <div className="shrink-0">
        <StudioStatusGrid
          onFocusCamera={setFocusedCamera}
          focusedCamera={focusedCamera}
        />
      </div>
    </div>
  );
}
