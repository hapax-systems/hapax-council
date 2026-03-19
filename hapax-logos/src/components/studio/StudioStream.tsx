import { useCallback, useEffect, useRef, useState } from "react";
import Hls from "hls.js";
import { acquireImage, releaseImage } from "../../hooks/useImagePool";
import { useStudioStreamInfo } from "../../api/hooks";
import { VideoOff, Zap, Film, Layers, Maximize, Minimize } from "lucide-react";

type StreamMode = "pull" | "hls" | "composite";

// Filter applied to the HLS (delayed/past) layer to visually distinguish it
const TINT_STYLES = [
  { name: "None", filter: "none" },
  { name: "Cyan", filter: "sepia(1) saturate(5) hue-rotate(160deg) brightness(0.7) contrast(1.3)" },
  { name: "Amber", filter: "sepia(1) saturate(3) hue-rotate(-10deg) brightness(0.7) contrast(1.2)" },
  { name: "Violet", filter: "sepia(1) saturate(4) hue-rotate(230deg) brightness(0.6) contrast(1.3)" },
  { name: "Mono", filter: "grayscale(1) brightness(1.4) contrast(1.5)" },
  { name: "Invert", filter: "invert(1) hue-rotate(180deg) contrast(1.2)" },
  { name: "Thermal", filter: "sepia(1) saturate(6) hue-rotate(-30deg) brightness(0.6) contrast(1.8)" },
] as const;

const BLEND_MODES = [
  { name: "Ghost", css: "screen", liveOpacity: 1, hlsOpacity: 0.4 },
  { name: "Trails", css: "lighten", liveOpacity: 1, hlsOpacity: 0.6 },
  { name: "Diff", css: "difference", liveOpacity: 1, hlsOpacity: 1 },
  { name: "Multiply", css: "multiply", liveOpacity: 1, hlsOpacity: 0.7 },
  { name: "Overlay", css: "overlay", liveOpacity: 1, hlsOpacity: 0.5 },
] as const;

export function StudioStream() {
  const { data: streamInfo } = useStudioStreamInfo();
  const [error, setError] = useState(false);
  const [mode, setMode] = useState<StreamMode>("pull");
  const [blendIdx, setBlendIdx] = useState(0);
  const [tintIdx, setTintIdx] = useState(1); // default to Cyan
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);

  const hlsAvailable = streamInfo?.hls_enabled ?? false;
  const snapshotAvailable = streamInfo?.mjpeg_enabled ?? false;
  const anyAvailable = hlsAvailable || snapshotAvailable;

  const showPull = mode === "pull" || mode === "composite";
  const showHls = mode === "hls" || mode === "composite";
  const blend = BLEND_MODES[blendIdx];
  const tint = TINT_STYLES[tintIdx];

  // --- Pull: fetch snapshot JPEGs on a timer ---
  useEffect(() => {
    if (!showPull || !snapshotAvailable) return;
    const img = imgRef.current;
    if (!img) return;

    let running = true;
    let pending = false;

    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = acquireImage();
      loader.onload = () => {
        if (running && img) img.src = loader.src;
        releaseImage(loader);
        pending = false;
      };
      loader.onerror = () => {
        releaseImage(loader);
        pending = false;
      };
      loader.src = `/api/studio/stream/snapshot?_t=${Date.now()}`;
    };

    pull();
    const pollRate = mode === "composite" ? 150 : 80;
    const timer = setInterval(pull, pollRate);
    return () => {
      running = false;
      clearInterval(timer);
    };
  }, [mode, snapshotAvailable]);

  // --- HLS ---
  useEffect(() => {
    if (!showHls || !hlsAvailable || !streamInfo) return;
    const video = videoRef.current;
    if (!video) return;
    if (!Hls.isSupported()) return;

    const hls = new Hls({
      liveSyncDurationCount: 1,
      liveMaxLatencyDurationCount: 3,
      maxBufferLength: 2,
      lowLatencyMode: true,
      backBufferLength: 0,
    });
    hlsRef.current = hls;
    hls.loadSource(streamInfo.hls_url);
    hls.attachMedia(video);
    hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
    hls.on(Hls.Events.ERROR, (_e, d) => {
      if (d.fatal) setError(true);
    });
    const sync = setInterval(() => {
      if (hls.liveSyncPosition && video.currentTime > 0) {
        const drift = hls.liveSyncPosition - video.currentTime;
        if (drift > 3) video.currentTime = hls.liveSyncPosition;
      }
    }, 2000);

    return () => {
      clearInterval(sync);
      hls.destroy();
      hlsRef.current = null;
    };
  }, [mode, hlsAvailable, streamInfo]);

  const cycleMode = useCallback(() => {
    setMode((m) => {
      if (m === "pull") return "hls";
      if (m === "hls") return "composite";
      return "pull";
    });
  }, []);

  const cycleBlend = useCallback(() => {
    setBlendIdx((i) => (i + 1) % BLEND_MODES.length);
  }, []);

  const cycleTint = useCallback(() => {
    setTintIdx((i) => (i + 1) % TINT_STYLES.length);
  }, []);

  const toggleFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      el.requestFullscreen();
    }
  }, []);

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  if (!anyAvailable || error) {
    return (
      <div className="flex aspect-video items-center justify-center rounded-lg border border-zinc-800 bg-zinc-900">
        <div className="flex flex-col items-center gap-2 text-zinc-600">
          <VideoOff className="h-8 w-8" />
          <span className="text-sm">Stream offline</span>
          {error && (
            <button
              onClick={() => setError(false)}
              className="mt-1 rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-700"
            >
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  const modeIcon =
    mode === "pull" ? (
      <Zap className="h-3 w-3 text-amber-400" />
    ) : mode === "hls" ? (
      <Film className="h-3 w-3 text-blue-400" />
    ) : (
      <Layers className="h-3 w-3 text-purple-400" />
    );
  const modeLabel =
    mode === "pull" ? "Live" : mode === "hls" ? "Smooth" : "Composite";

  return (
    <div
      ref={containerRef}
      className={`relative ${isFullscreen ? "flex items-center justify-center bg-black" : ""}`}
      onDoubleClick={toggleFullscreen}
    >
      {mode === "composite" ? (
        /* Composited overlay: live base + HLS blended on top */
        <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black" style={{ isolation: "isolate" }}>
          <img
            ref={imgRef}
            alt="Studio live"
            className="absolute inset-0 h-full w-full object-contain"
            style={{ opacity: blend.liveOpacity }}
          />
          <video
            ref={videoRef}
            className="absolute inset-0 h-full w-full object-contain"
            style={{
              mixBlendMode: blend.css,
              opacity: blend.hlsOpacity,
              filter: tint.filter,
            }}
            muted
            playsInline
          />
        </div>
      ) : (
        <>
          <img
            ref={imgRef}
            alt="Studio live"
            className={`aspect-video w-full rounded-lg bg-black object-contain ${mode !== "pull" ? "hidden" : ""}`}
          />
          <video
            ref={videoRef}
            className={`aspect-video w-full rounded-lg bg-black ${mode !== "hls" ? "hidden" : ""}`}
            muted
            playsInline
          />
        </>
      )}

      {/* Controls */}
      <div className="absolute right-2 top-2 flex items-center gap-1">
        {snapshotAvailable && hlsAvailable && (
          <button
            onClick={cycleMode}
            className="flex items-center gap-1 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-zinc-300 backdrop-blur-sm hover:bg-black/80"
            title="Cycle: Live → Smooth → Composite"
          >
            {modeIcon}
            {modeLabel}
          </button>
        )}
        <button
          onClick={toggleFullscreen}
          className="flex items-center rounded bg-black/60 p-1 text-zinc-300 backdrop-blur-sm hover:bg-black/80"
          title={isFullscreen ? "Exit fullscreen (or double-click)" : "Fullscreen (or double-click)"}
        >
          {isFullscreen ? <Minimize className="h-3.5 w-3.5" /> : <Maximize className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* Composite controls */}
      {mode === "composite" && (
        <div className="absolute right-2 top-9 flex flex-col gap-1">
          <button
            onClick={cycleBlend}
            className="flex items-center gap-1 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-purple-300 backdrop-blur-sm hover:bg-black/80"
            title={`Blend: ${blend.name} — click to cycle`}
          >
            {blend.name}
          </button>
          <button
            onClick={cycleTint}
            className="flex items-center gap-1 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-cyan-300 backdrop-blur-sm hover:bg-black/80"
            title={`Past tint: ${tint.name} — click to cycle`}
          >
            {tint.name}
          </button>
        </div>
      )}
    </div>
  );
}
