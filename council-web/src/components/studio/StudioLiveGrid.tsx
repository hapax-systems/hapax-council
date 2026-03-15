import { useEffect, useRef, useState } from "react";
import { Maximize, GripVertical } from "lucide-react";

interface Props {
  cameraOrder: string[];
  onReorder: (order: string[]) => void;
  onFocusCamera: (role: string) => void;
}

/** Grid of individual live camera feeds — drag to swap positions. */
export function StudioLiveGrid({
  cameraOrder,
  onReorder,
  onFocusCamera,
}: Props) {
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);

  const handleDragStart = (idx: number) => setDragIdx(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setOverIdx(idx);
  };
  const handleDrop = (idx: number) => {
    if (dragIdx !== null && dragIdx !== idx) {
      const next = [...cameraOrder];
      const [moved] = next.splice(dragIdx, 1);
      next.splice(idx, 0, moved);
      onReorder(next);
    }
    setDragIdx(null);
    setOverIdx(null);
  };
  const handleDragEnd = () => {
    setDragIdx(null);
    setOverIdx(null);
  };

  if (cameraOrder.length === 0) return null;

  const hero = cameraOrder[0];
  const others = cameraOrder.slice(1);

  return (
    <div className="flex h-full gap-1">
      <CameraCell
        role={hero}
        isHero
        idx={0}
        dragIdx={dragIdx}
        overIdx={overIdx}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onDragEnd={handleDragEnd}
        onFocus={onFocusCamera}
      />
      {others.length > 0 && (
        <div className="flex w-1/3 flex-col gap-1">
          {others.map((role, i) => (
            <CameraCell
              key={role}
              role={role}
              idx={i + 1}
              dragIdx={dragIdx}
              overIdx={overIdx}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onDragEnd={handleDragEnd}
              onFocus={onFocusCamera}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface CameraCellProps {
  role: string;
  isHero?: boolean;
  idx: number;
  dragIdx: number | null;
  overIdx: number | null;
  onDragStart: (idx: number) => void;
  onDragOver: (e: React.DragEvent, idx: number) => void;
  onDrop: (idx: number) => void;
  onDragEnd: () => void;
  onFocus: (role: string) => void;
}

function CameraCell({
  role,
  isHero,
  idx,
  dragIdx,
  overIdx,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onFocus,
}: CameraCellProps) {
  const imgRef = useRef<HTMLImageElement>(null);

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
    const interval = isHero ? 80 : 120;
    const timer = setInterval(pull, interval);
    return () => {
      running = false;
      clearInterval(timer);
    };
  }, [role, isHero]);

  const isDragging = dragIdx === idx;
  const isOver = overIdx === idx && dragIdx !== idx;

  return (
    <div
      draggable
      onDragStart={() => onDragStart(idx)}
      onDragOver={(e) => onDragOver(e, idx)}
      onDrop={() => onDrop(idx)}
      onDragEnd={onDragEnd}
      className={`relative flex-1 overflow-hidden rounded-lg transition-all ${
        isDragging
          ? "scale-[0.97] opacity-50"
          : isOver
            ? "ring-2 ring-purple-500/60"
            : ""
      }`}
    >
      <img
        ref={imgRef}
        alt={role}
        className="h-full w-full bg-black object-contain"
      />
      <div className="absolute left-1 top-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-zinc-300 backdrop-blur-sm">
        {role}
      </div>
      <div className="absolute right-1 top-1 flex items-center gap-0.5">
        <div className="cursor-grab rounded bg-black/40 p-0.5 text-zinc-400 active:cursor-grabbing">
          <GripVertical className="h-3 w-3" />
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onFocus(role); }}
          className="rounded bg-black/40 p-0.5 text-zinc-400 hover:bg-black/70 hover:text-zinc-200"
          title="Solo this camera"
        >
          <Maximize className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}
