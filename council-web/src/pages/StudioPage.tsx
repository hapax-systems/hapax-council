import { useMemo, useState } from "react";
import { StudioStream } from "../components/studio/StudioStream";
import { StudioLiveGrid } from "../components/studio/StudioLiveGrid";
import {
  StudioStatusGrid,
  CameraSoloView,
} from "../components/studio/StudioStatusGrid";
import { useStudio } from "../api/hooks";

export function StudioPage() {
  const { data: studio } = useStudio();
  const compositor = studio?.compositor;
  const [focusedCamera, setFocusedCamera] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"grid" | "composite">("grid");
  // User-defined order override — null means use default from compositor
  const [userOrder, setUserOrder] = useState<string[] | null>(null);

  const defaultOrder = useMemo(
    () => (compositor ? Object.keys(compositor.cameras) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [compositor ? Object.keys(compositor.cameras).join(",") : ""],
  );

  const cameraOrder = userOrder ?? defaultOrder;

  return (
    <div className="flex flex-1 flex-col gap-2 overflow-hidden p-3">
      <div className="flex shrink-0 items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-semibold text-zinc-100">Studio</h1>
          {compositor && compositor.state !== "unknown" && (
            <div className="flex items-center gap-1">
              <button
                onClick={() => setViewMode("grid")}
                className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  viewMode === "grid"
                    ? "bg-zinc-700 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                Grid
              </button>
              <button
                onClick={() => setViewMode("composite")}
                className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  viewMode === "composite"
                    ? "bg-zinc-700 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                Composite
              </button>
            </div>
          )}
        </div>
        {compositor && compositor.state !== "unknown" && (
          <span className="text-[10px] text-zinc-500">
            {compositor.resolution} · {compositor.active_cameras}/
            {compositor.total_cameras} cameras
            {compositor.hls_enabled && " · HLS"}
            {compositor.recording_enabled && " · REC"}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1">
        {focusedCamera ? (
          <CameraSoloView
            role={focusedCamera}
            onClose={() => setFocusedCamera(null)}
          />
        ) : viewMode === "grid" ? (
          <StudioLiveGrid
            cameraOrder={cameraOrder}
            onReorder={setUserOrder}
            onFocusCamera={setFocusedCamera}
          />
        ) : (
          <StudioStream />
        )}
      </div>

      <div className="shrink-0">
        <StudioStatusGrid
          onFocusCamera={setFocusedCamera}
          focusedCamera={focusedCamera}
        />
      </div>
    </div>
  );
}
