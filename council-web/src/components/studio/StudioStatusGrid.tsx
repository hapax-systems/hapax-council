import { useCallback, useEffect, useRef, useState } from "react";
import { useStudio } from "../../api/hooks";
import { Camera, X, Maximize } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500",
  offline: "bg-red-500",
  starting: "bg-yellow-500",
};

interface Props {
  onFocusCamera?: (role: string | null) => void;
  focusedCamera?: string | null;
}

export function StudioStatusGrid({ onFocusCamera, focusedCamera }: Props) {
  const { data: studio } = useStudio();
  const compositor = studio?.compositor;

  if (!compositor || compositor.state === "unknown") {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-xs text-zinc-500">
        Compositor not running
      </div>
    );
  }

  const cameras = Object.entries(compositor.cameras);
  const recordingCams = compositor.recording_cameras ?? {};

  return (
    <div className="flex gap-2">
      {cameras.map(([role, status]) => {
        const isRecording = recordingCams[role] === "active";
        const isFocused = focusedCamera === role;
        return (
          <button
            key={role}
            onClick={() => onFocusCamera?.(isFocused ? null : role)}
            className={`flex flex-1 items-center gap-2 rounded border p-2 text-left transition-colors ${
              isFocused
                ? "border-amber-500/50 bg-amber-950/30"
                : "border-zinc-800 bg-zinc-900 hover:border-zinc-700"
            }`}
          >
            <span
              className={`inline-block h-2 w-2 shrink-0 rounded-full ${STATUS_COLORS[status] ?? "bg-zinc-600"}`}
            />
            <span className="truncate text-[11px] font-medium text-zinc-300">
              {role}
            </span>
            {isRecording && (
              <span className="shrink-0 rounded bg-red-900/50 px-1 py-0.5 text-[9px] font-medium text-red-400">
                REC
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Solo camera viewer — shows a single camera feed full-size */
export function CameraSoloView({
  role,
  onClose,
}: {
  role: string;
  onClose: () => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    let running = true;
    let pending = false;

    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      loader.onload = () => {
        if (running && img) img.src = loader.src;
        pending = false;
      };
      loader.onerror = () => {
        pending = false;
      };
      loader.src = `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };

    pull();
    const timer = setInterval(pull, 120); // ~8fps per camera
    return () => {
      running = false;
      clearInterval(timer);
    };
  }, [role]);

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

  return (
    <div
      ref={containerRef}
      className={`relative ${isFullscreen ? "flex items-center justify-center bg-black" : ""}`}
      onDoubleClick={toggleFullscreen}
    >
      <img
        ref={imgRef}
        alt={role}
        className="aspect-video w-full rounded-lg bg-black object-contain"
      />
      <div className="absolute left-2 top-2 flex items-center gap-1 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-amber-300 backdrop-blur-sm">
        <Camera className="h-3 w-3" />
        {role}
      </div>
      <div className="absolute right-2 top-2 flex items-center gap-1">
        <button
          onClick={toggleFullscreen}
          className="rounded bg-black/60 p-1 text-zinc-300 backdrop-blur-sm hover:bg-black/80"
        >
          <Maximize className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onClose}
          className="rounded bg-black/60 p-1 text-zinc-300 backdrop-blur-sm hover:bg-black/80"
          title="Back to composited view"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
