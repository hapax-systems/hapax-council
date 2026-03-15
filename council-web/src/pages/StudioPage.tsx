import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Maximize, Minimize } from "lucide-react";
import Hls from "hls.js";
import { StudioLiveGrid } from "../components/studio/StudioLiveGrid";
import { PRESETS, type CompositePreset, type OverlayType } from "../components/studio/compositePresets";
import { SOURCE_FILTERS } from "../components/studio/compositeFilters";
import {
  StudioStatusGrid,
  CameraSoloView,
} from "../components/studio/StudioStatusGrid";
import { StudioSidebar } from "../components/studio/StudioSidebar";
import { useStudio } from "../api/hooks";

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
  const [overlayOverrides, setOverlayOverrides] = useState<OverlayType[] | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const [pageFullscreen, setPageFullscreen] = useState(false);
  const [hlsReady, setHlsReady] = useState(false);
  const hlsRef = useRef<Hls | null>(null);

  const defaultOrder = useMemo(
    () => (compositor ? Object.keys(compositor.cameras) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [compositor ? Object.keys(compositor.cameras).join(",") : ""],
  );
  const cameraOrder = userOrder ?? defaultOrder;
  const basePreset = PRESETS[presetIdx];
  const liveFilter = SOURCE_FILTERS[liveFilterIdx];
  const trailFilter = SOURCE_FILTERS[trailFilterIdx];

  // Build effective preset with user filter + overlay overrides
  const effectivePreset: CompositePreset | undefined = useMemo(() => {
    if (viewMode !== "composite") return undefined;
    return {
      ...basePreset,
      liveFilter: liveFilter.css !== "none" ? liveFilter.css : basePreset.liveFilter,
      trail: {
        ...basePreset.trail,
        filter: trailFilter.css !== "none" ? trailFilter.css : basePreset.trail.filter,
      },
      overlays: overlayOverrides ?? basePreset.overlays,
    };
  }, [viewMode, basePreset, liveFilter.css, trailFilter.css, overlayOverrides]);


  // HLS pre-buffering — start immediately, don't wait for stream info
  useEffect(() => {
    const hlsUrl = "/api/studio/hls/stream.m3u8";
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
    hls.loadSource(hlsUrl);
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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Callbacks for sidebar ---

  const handlePresetChange = useCallback((i: number) => {
    setPresetIdx(i);
    setLiveFilterIdx(0);
    setTrailFilterIdx(0);
    setOverlayOverrides(null);
  }, []);

  const handleOverlayToggle = useCallback(
    (ov: OverlayType) => {
      setOverlayOverrides((prev) => {
        const current = prev ?? PRESETS[presetIdx].overlays;
        return current.includes(ov) ? current.filter((o) => o !== ov) : [...current, ov];
      });
    },
    [presetIdx],
  );

  const handleOverlayReset = useCallback(() => {
    setOverlayOverrides(null);
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

  return (
    <div ref={pageRef} className={`flex flex-1 overflow-hidden ${pageFullscreen ? "bg-zinc-950" : ""}`}>
      {/* Main content */}
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        {/* Header — title + camera count only */}
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
            {pageFullscreen ? <Minimize className="h-3.5 w-3.5" /> : <Maximize className="h-3.5 w-3.5" />}
          </button>
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
                  preset={effectivePreset}
                />
              </div>
              <video
                ref={videoRef}
                className={`h-full w-full rounded-lg bg-black object-contain ${viewMode !== "smooth" ? "invisible absolute inset-0" : ""}`}
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
        overlayOverrides={overlayOverrides}
        onOverlayToggle={handleOverlayToggle}
        onOverlayReset={handleOverlayReset}
        heroRole={heroRole}
        onHeroChange={handleHeroChange}
        onOrderReset={handleOrderReset}
        cameraRoles={cameraOrder}
      />
    </div>
  );
}
