import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Hls from "hls.js";
import { StudioLiveGrid } from "../components/studio/StudioLiveGrid";
import { PRESETS } from "../components/studio/compositePresets";
import {
  StudioStatusGrid,
  CameraSoloView,
} from "../components/studio/StudioStatusGrid";
import { useStudio, useStudioStreamInfo } from "../api/hooks";
import { ChevronLeft, ChevronRight } from "lucide-react";

type ViewMode = "grid" | "composite" | "smooth";

export function StudioPage() {
  const { data: studio } = useStudio();
  const { data: streamInfo } = useStudioStreamInfo();
  const compositor = studio?.compositor;
  const [focusedCamera, setFocusedCamera] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [userOrder, setUserOrder] = useState<string[] | null>(null);
  const [presetIdx, setPresetIdx] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [hlsReady, setHlsReady] = useState(false);
  const hlsRef = useRef<Hls | null>(null);

  const defaultOrder = useMemo(
    () => (compositor ? Object.keys(compositor.cameras) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [compositor ? Object.keys(compositor.cameras).join(",") : ""],
  );
  const cameraOrder = userOrder ?? defaultOrder;
  const preset = PRESETS[presetIdx];

  const hlsAvailable = streamInfo?.hls_enabled ?? false;
  const showHls = hlsAvailable; // always load HLS so it's pre-buffered

  // HLS
  useEffect(() => {
    if (!showHls || !streamInfo) return;
    const video = videoRef.current;
    if (!video) return;
    if (!Hls.isSupported()) return;
    const hls = new Hls({
      liveSyncDurationCount: 3,
      liveMaxLatencyDurationCount: 5,
      maxBufferLength: 10,
      backBufferLength: 0,
    });
    hlsRef.current = hls;
    hls.loadSource(streamInfo.hls_url);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      video.play().then(() => setHlsReady(true)).catch(() => {});
    });
    const sync = setInterval(() => {
      if (hls.liveSyncPosition && video.currentTime > 0) {
        const drift = hls.liveSyncPosition - video.currentTime;
        if (drift > 3) video.currentTime = hls.liveSyncPosition;
      }
    }, 2000);
    return () => { clearInterval(sync); hls.destroy(); hlsRef.current = null; setHlsReady(false); };
  }, [showHls, streamInfo]);

  const prevPreset = useCallback(() => setPresetIdx((i) => (i - 1 + PRESETS.length) % PRESETS.length), []);
  const nextPreset = useCallback(() => setPresetIdx((i) => (i + 1) % PRESETS.length), []);

  return (
    <div className="flex flex-1 flex-col gap-2 overflow-hidden p-3">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-semibold text-zinc-100">Studio</h1>
          {compositor && compositor.state !== "unknown" && (
            <div className="flex items-center gap-1">
              {(["grid", "composite", "smooth"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setViewMode(m)}
                  className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                    viewMode === m
                      ? "bg-zinc-700 text-zinc-100"
                      : "text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {m === "grid" ? "Grid" : m === "composite" ? "Composite" : "Smooth"}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {viewMode === "composite" && (
            <div className="flex items-center gap-1">
              <button onClick={prevPreset} className="rounded bg-zinc-800 p-0.5 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200">
                <ChevronLeft className="h-3 w-3" />
              </button>
              <span className="min-w-[4.5rem] text-center text-[10px] font-medium text-purple-300" title={preset.description}>
                {preset.name}
              </span>
              <button onClick={nextPreset} className="rounded bg-zinc-800 p-0.5 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200">
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          )}
          {compositor && compositor.state !== "unknown" && (
            <span className="text-[10px] text-zinc-500">
              {compositor.resolution} · {compositor.active_cameras}/{compositor.total_cameras} cameras
              {compositor.hls_enabled && " · HLS"}
              {compositor.recording_enabled && " · REC"}
            </span>
          )}
        </div>
      </div>

      {/* Main view */}
      <div className="relative min-h-0 flex-1" style={{ isolation: "isolate" }}>
        {focusedCamera ? (
          <CameraSoloView role={focusedCamera} onClose={() => setFocusedCamera(null)} />
        ) : (
          <>
            <div className={viewMode === "smooth" ? "hidden" : "h-full"}>
              <StudioLiveGrid
                cameraOrder={cameraOrder}
                onReorder={setUserOrder}
                onFocusCamera={setFocusedCamera}
                preset={viewMode === "composite" ? preset : undefined}
              />
            </div>
            {/* HLS video — always mounted for pre-buffering, visible only in smooth mode */}
            <video
              ref={videoRef}
              className={viewMode === "smooth" ? "h-full w-full rounded-lg bg-black object-contain" : "hidden"}
              muted
              playsInline
            />
            {viewMode === "smooth" && !hlsReady && (
              <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/80">
                <div className="flex flex-col items-center gap-2 text-zinc-500">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-600 border-t-zinc-300" />
                  <span className="text-[10px]">Buffering stream...</span>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Status bar */}
      <div className="shrink-0">
        <StudioStatusGrid onFocusCamera={setFocusedCamera} focusedCamera={focusedCamera} />
      </div>
    </div>
  );
}
