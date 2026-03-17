import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Maximize, Minimize } from "lucide-react";
import Hls from "hls.js";
import { StudioLiveGrid } from "../components/studio/StudioLiveGrid";
import { PRESETS, type CompositePreset } from "../components/studio/compositePresets";
import {
  StudioStatusGrid,
  CameraSoloView,
} from "../components/studio/StudioStatusGrid";
import { StudioSidebar } from "../components/studio/StudioSidebar";
import { useStudio, useStudioStreamInfo } from "../api/hooks";
import { useSnapshotPoll } from "../hooks/useSnapshotPoll";
import { useStudioShortcuts } from "../hooks/useStudioShortcuts";
import { api } from "../api/client";

/* ---------- GPU FX snapshot viewer ---------- */
function FxView() {
  const { imgRef, isStale } = useSnapshotPoll("/api/studio/stream/fx", 80);

  return (
    <div className="relative h-full w-full">
      <img
        ref={imgRef}
        className="h-full w-full rounded-lg bg-black object-contain"
        alt="GPU FX"
      />
      {isStale && (
        <div className="absolute inset-x-0 top-2 flex justify-center">
          <div className="flex items-center gap-1.5 rounded-full bg-amber-900/80 px-3 py-1 text-[11px] font-medium text-amber-200 backdrop-blur-sm">
            <AlertTriangle className="h-3.5 w-3.5" />
            FX pipeline stale
          </div>
        </div>
      )}
    </div>
  );
}

type ViewMode = "grid" | "composite" | "smooth";

export function StudioPage() {
  const { data: studio } = useStudio();

  const compositor = studio?.compositor;
  const [focusedCamera, setFocusedCamera] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [userOrder, setUserOrder] = useState<string[] | null>(null);
  const [presetIdx, setPresetIdx] = useState(0);
  const [liveFilterIdx, setLiveFilterIdx] = useState(0);
  const [trailFilterIdx, setTrailFilterIdx] = useState(0);
  const [effectOverrides, setEffectOverrides] = useState<Partial<CompositePreset["effects"]> | null>(
    null,
  );
  const videoRef = useRef<HTMLVideoElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const [pageFullscreen, setPageFullscreen] = useState(false);
  const [hlsReady, setHlsReady] = useState(false);
  const [hlsError, setHlsError] = useState(false);
  const hlsRef = useRef<Hls | null>(null);
  const { data: streamInfo } = useStudioStreamInfo();

  const defaultOrder = useMemo(
    () => (compositor ? Object.keys(compositor.cameras) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [compositor ? Object.keys(compositor.cameras).join(",") : ""],
  );
  const cameraOrder = userOrder ?? defaultOrder;
  const basePreset = PRESETS[presetIdx];

  // HLS — only initialize when in smooth mode (saves decode resources)
  useEffect(() => {
    if (viewMode !== "smooth") return;
    setHlsError(false);
    setHlsReady(false);

    // Skip HLS init entirely if stream is known to be offline
    if (streamInfo && !streamInfo.hls_enabled) {
      setHlsError(true);
      return;
    }

    const video = videoRef.current;
    if (!video) return;
    if (!Hls.isSupported()) return;

    const hlsUrl = "/api/studio/hls/stream.m3u8";
    const hls = new Hls({
      liveSyncDurationCount: 3,
      liveMaxLatencyDurationCount: 5,
      maxBufferLength: 10,
      backBufferLength: 0,
    });
    hlsRef.current = hls;
    hls.loadSource(hlsUrl);
    hls.attachMedia(video);

    let manifestParsed = false;
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      manifestParsed = true;
      video
        .play()
        .then(() => setHlsReady(true))
        .catch(() => {});
    });
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data.fatal) setHlsError(true);
    });

    // 8s timeout — if no manifest parsed, show error
    const timeout = setTimeout(() => {
      if (!manifestParsed) setHlsError(true);
    }, 8_000);

    const sync = setInterval(() => {
      if (hls.liveSyncPosition && video.currentTime > 0) {
        const drift = hls.liveSyncPosition - video.currentTime;
        if (drift > 3) video.currentTime = hls.liveSyncPosition;
      }
    }, 2000);
    return () => {
      clearTimeout(timeout);
      clearInterval(sync);
      hls.destroy();
      hlsRef.current = null;
      setHlsReady(false);
    };
  }, [viewMode, streamInfo?.hls_enabled]);

  // --- Callbacks for sidebar ---

  const handlePresetChange = useCallback((i: number) => {
    setPresetIdx(i);
    setLiveFilterIdx(0);
    setTrailFilterIdx(0);
    setEffectOverrides(null);
    // Switch the GPU pipeline when a preset is selected
    const presetName = PRESETS[i].name.toLowerCase();
    api.selectEffect(presetName).catch(() => {
      /* GPU pipeline may not be running — ignore */
    });
  }, []);

  const handleEffectToggle = useCallback(
    (key: keyof CompositePreset["effects"]) => {
      setEffectOverrides((prev) => {
        const current = prev ? { ...PRESETS[presetIdx].effects, ...prev } : PRESETS[presetIdx].effects;
        const val = current[key];
        if (typeof val === "boolean") {
          return { ...(prev ?? {}), [key]: !val };
        }
        return prev;
      });
    },
    [presetIdx],
  );

  const handleEffectReset = useCallback(() => {
    setEffectOverrides(null);
  }, []);

  const heroRole = cameraOrder.length > 0 ? cameraOrder[0] : null;

  const handleHeroChange = useCallback(
    (role: string) => {
      if (!role) return;
      const idx = cameraOrder.indexOf(role);
      if (idx <= 0) return;
      const next = [...cameraOrder];
      const [moved] = next.splice(idx, 1);
      next.unshift(moved);
      setUserOrder(next);
    },
    [cameraOrder],
  );

  const handleOrderReset = useCallback(() => {
    setUserOrder(null);
  }, []);

  const togglePageFullscreen = useCallback(() => {
    const el = pageRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen();
  }, []);

  useEffect(() => {
    const onChange = () => setPageFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // Keyboard shortcuts
  useStudioShortcuts({
    onViewMode: setViewMode,
    onPreset: handlePresetChange,
    onFullscreen: togglePageFullscreen,
  });

  return (
    <div ref={pageRef} className={`flex flex-1 overflow-hidden ${pageFullscreen ? "bg-zinc-950" : ""}`}>
      {/* Main content */}
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between">
          <h1 className="text-sm font-semibold text-zinc-100">Studio</h1>
          {compositor && compositor.state !== "unknown" && (
            <span className="text-[10px] text-zinc-500">
              {compositor.active_cameras}/{compositor.total_cameras} cameras
            </span>
          )}
          <button
            onClick={togglePageFullscreen}
            className="rounded p-0.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
            title={pageFullscreen ? "Exit fullscreen" : "Fullscreen studio"}
          >
            {pageFullscreen ? (
              <Minimize className="h-3.5 w-3.5" />
            ) : (
              <Maximize className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {/* Main view */}
        <div className="relative min-h-0 flex-1" style={{ isolation: "isolate" }}>
          {focusedCamera ? (
            <CameraSoloView role={focusedCamera} onClose={() => setFocusedCamera(null)} />
          ) : (
            <>
              {viewMode === "grid" ? (
                <StudioLiveGrid
                  cameraOrder={cameraOrder}
                  onReorder={setUserOrder}
                  onFocusCamera={setFocusedCamera}
                />
              ) : viewMode === "composite" ? (
                <div className="relative h-full w-full">
                  <FxView />
                  <div className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-purple-300 backdrop-blur-sm">
                    {PRESETS[presetIdx].name}
                  </div>
                </div>
              ) : (
                <>
                  <video
                    ref={videoRef}
                    className="h-full w-full rounded-lg bg-black object-contain"
                    muted
                    playsInline
                  />
                  {!hlsReady && (
                    <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/80">
                      {hlsError ? (
                        <div className="flex flex-col items-center gap-3 text-zinc-400">
                          <AlertTriangle className="h-6 w-6 text-amber-500" />
                          <span className="text-xs">HLS stream unavailable</span>
                          <button
                            onClick={() => setViewMode("grid")}
                            className="rounded bg-zinc-700 px-3 py-1 text-[11px] font-medium text-zinc-200 hover:bg-zinc-600"
                          >
                            Switch to Grid
                          </button>
                        </div>
                      ) : (
                        <div className="flex flex-col items-center gap-2 text-zinc-500">
                          <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-600 border-t-zinc-300" />
                          <span className="text-[10px]">Buffering stream...</span>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
              {/* Hidden video element keeps HLS pre-buffered regardless of view mode */}
              {viewMode !== "smooth" && (
                <video
                  ref={videoRef}
                  className="invisible absolute inset-0 h-0 w-0"
                  muted
                  playsInline
                />
              )}
            </>
          )}
        </div>

        {/* Status bar */}
        <div className="shrink-0">
          <StudioStatusGrid onFocusCamera={setFocusedCamera} focusedCamera={focusedCamera} />
        </div>
      </div>

      {/* Sidebar */}
      <StudioSidebar
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        presetIdx={presetIdx}
        onPresetChange={handlePresetChange}
        liveFilterIdx={liveFilterIdx}
        onLiveFilterChange={setLiveFilterIdx}
        trailFilterIdx={trailFilterIdx}
        onTrailFilterChange={setTrailFilterIdx}
        effectOverrides={effectOverrides}
        baseEffects={basePreset.effects}
        onEffectToggle={handleEffectToggle}
        onEffectReset={handleEffectReset}
        heroRole={heroRole}
        onHeroChange={handleHeroChange}
        onOrderReset={handleOrderReset}
        cameraRoles={cameraOrder}
      />
    </div>
  );
}
