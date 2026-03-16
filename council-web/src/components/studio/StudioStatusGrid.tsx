import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStudio } from "../../api/hooks";
import { AlertTriangle, Camera, X, Maximize, GripVertical } from "lucide-react";

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
  const [userOrder, setUserOrder] = useState<string[] | null>(null);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);

  const defaultOrder = useMemo(
    () => (compositor ? Object.keys(compositor.cameras) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [compositor ? Object.keys(compositor.cameras).join(",") : ""],
  );

  const order = userOrder ?? defaultOrder;

  if (!compositor || compositor.state === "unknown") {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-xs text-zinc-500">
        Compositor not running
      </div>
    );
  }

  const recordingCams = compositor.recording_cameras ?? {};

  const handleDragStart = (idx: number) => setDragIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setOverIdx(idx);
  };
  const handleDrop = (idx: number) => {
    if (dragIdx !== null && dragIdx !== idx) {
      const next = [...order];
      const [moved] = next.splice(dragIdx, 1);
      next.splice(idx, 0, moved);
      setUserOrder(next);
    }
    setDragIdx(null);
    setOverIdx(null);
  };
  const handleDragEnd = () => {
    setDragIdx(null);
    setOverIdx(null);
  };

  return (
    <div className="flex gap-2">
      {order.map((role, idx) => {
        const status = compositor.cameras[role] ?? "unknown";
        const isRecording = recordingCams[role] === "active";
        const isFocused = focusedCamera === role;
        const isDragging = dragIdx === idx;
        const isOver = overIdx === idx && dragIdx !== idx;

        return (
          <div
            key={role}
            draggable
            onDragStart={() => handleDragStart(idx)}
            onDragOver={(e) => handleDragOver(e, idx)}
            onDrop={() => handleDrop(idx)}
            onDragEnd={handleDragEnd}
            onClick={() => onFocusCamera?.(isFocused ? null : role)}
            className={`flex flex-1 cursor-pointer items-center gap-1.5 rounded border p-2 transition-all ${
              isDragging
                ? "scale-95 opacity-50"
                : isOver
                  ? "border-purple-500/50 bg-purple-950/20"
                  : isFocused
                    ? "border-amber-500/50 bg-amber-950/30"
                    : "border-zinc-800 bg-zinc-900 hover:border-zinc-700"
            }`}
          >
            <GripVertical className="h-3 w-3 shrink-0 cursor-grab text-zinc-600 active:cursor-grabbing" />
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
          </div>
        );
      })}
    </div>
  );
}

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
  const lastSuccess = useRef(Date.now());
  const [isStale, setIsStale] = useState(false);

  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    let running = true;
    let pending = false;
    lastSuccess.current = Date.now();

    const pull = () => {
      if (!running || pending) return;
      pending = true;
      const loader = new Image();
      loader.onload = () => {
        if (running && img) img.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
        pending = false;
      };
      loader.onerror = () => {
        pending = false;
      };
      loader.src = `/api/studio/stream/camera/${role}?_t=${Date.now()}`;
    };

    pull();
    const timer = setInterval(pull, 120);
    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 10_000) setIsStale(true);
    }, 2_000);
    return () => {
      running = false;
      clearInterval(timer);
      clearInterval(staleTimer);
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
      <div className="absolute left-2 top-2 flex items-center gap-1.5">
        <span className="flex items-center gap-1 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-amber-300 backdrop-blur-sm">
          <Camera className="h-3 w-3" />
          {role}
        </span>
        {isStale && (
          <span className="flex items-center gap-1 rounded bg-amber-900/80 px-2 py-1 text-[10px] font-medium text-amber-200 backdrop-blur-sm">
            <AlertTriangle className="h-3 w-3" />
            Stale
          </span>
        )}
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
