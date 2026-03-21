import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

interface SplitPaneProps {
  left: ReactNode;
  right: ReactNode;
  fullscreenLeft?: ReactNode;
  fullscreen: boolean;
  onClose: () => void;
  onToggleFullscreen: () => void;
  regionLabel: string;
}

const MIN_LEFT_PCT = 25;
const MAX_LEFT_PCT = 75;
const DEFAULT_LEFT_PCT = 55;

export function SplitPane({
  left,
  right,
  fullscreenLeft,
  fullscreen,
  onClose,
  onToggleFullscreen,
  regionLabel,
}: SplitPaneProps) {
  const [leftPct, setLeftPct] = useState(DEFAULT_LEFT_PCT);
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const pct = ((e.clientX - rect.left) / rect.width) * 100;
    setLeftPct(Math.min(MAX_LEFT_PCT, Math.max(MIN_LEFT_PCT, pct)));
  }, []);

  const handlePointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  // Double-click divider to reset
  const handleDoubleClick = useCallback(() => {
    setLeftPct(DEFAULT_LEFT_PCT);
  }, []);

  // Keyboard: F11 toggles fullscreen
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "F11") {
        e.preventDefault();
        onToggleFullscreen();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onToggleFullscreen]);

  if (fullscreen) {
    return (
      <div
        ref={containerRef}
        className="absolute inset-0 flex"
        style={{ zIndex: 1 }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        {/* Left pane: region content (camera feed for ground) */}
        <div className="h-full overflow-hidden relative" style={{ width: `${leftPct}%` }}>
          {fullscreenLeft ?? left}
        </div>

        {/* Resize handle */}
        <div
          className="h-full flex items-center justify-center shrink-0"
          style={{
            width: "8px",
            cursor: "col-resize",
            background: "rgba(80, 73, 69, 0.4)",
            transition: "background 150ms ease",
          }}
          onPointerDown={handlePointerDown}
          onDoubleClick={handleDoubleClick}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background = "rgba(180, 160, 120, 0.25)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "rgba(80, 73, 69, 0.4)";
          }}
        >
          <div
            className="w-0.5 h-12 rounded-full"
            style={{ background: "rgba(180, 160, 120, 0.35)" }}
          />
        </div>

        {/* Right pane: detail/controls */}
        <div className="h-full overflow-hidden relative flex-1">
          {/* Fullscreen toolbar */}
          <div
            className="absolute top-0 right-0 flex items-center gap-2 px-3 py-1.5"
            style={{ zIndex: 10 }}
          >
            <span
              className="text-[8px] uppercase tracking-[0.3em]"
              style={{ color: "rgba(180, 160, 120, 0.3)" }}
            >
              {regionLabel}
            </span>
            <button
              onClick={onToggleFullscreen}
              className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5 rounded border border-zinc-800/50 hover:border-zinc-700/50"
              title="Exit fullscreen (F11)"
            >
              &#x2295;
            </button>
            <button
              onClick={onClose}
              className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5 rounded border border-zinc-800/50 hover:border-zinc-700/50"
              title="Close split (S)"
            >
              &#x2715;
            </button>
          </div>
          <div className="w-full h-full">{right}</div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 flex"
      style={{ zIndex: 1 }}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
    >
      {/* Left pane */}
      <div className="h-full overflow-hidden relative" style={{ width: `${leftPct}%` }}>
        {left}
      </div>

      {/* Resize handle */}
      <div
        className="h-full flex items-center justify-center shrink-0"
        style={{
          width: "8px",
          cursor: "col-resize",
          background: "rgba(80, 73, 69, 0.4)",
          transition: "background 150ms ease",
        }}
        onPointerDown={handlePointerDown}
        onDoubleClick={handleDoubleClick}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.background = "rgba(180, 160, 120, 0.25)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.background = "rgba(80, 73, 69, 0.4)";
        }}
      >
        <div
          className="w-0.5 h-12 rounded-full"
          style={{ background: "rgba(180, 160, 120, 0.35)" }}
        />
      </div>

      {/* Right pane */}
      <div className="h-full overflow-hidden relative flex-1">
        {/* Right pane toolbar */}
        <div
          className="absolute top-0 right-0 flex items-center gap-2 px-3 py-1.5"
          style={{ zIndex: 10 }}
        >
          <span
            className="text-[8px] uppercase tracking-[0.3em]"
            style={{ color: "rgba(180, 160, 120, 0.3)" }}
          >
            {regionLabel}
          </span>
          <button
            onClick={onToggleFullscreen}
            className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5 rounded border border-zinc-800/50 hover:border-zinc-700/50"
            title="Fullscreen (F11)"
          >
            &#x229E;
          </button>
          <button
            onClick={onClose}
            className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors px-1.5 py-0.5 rounded border border-zinc-800/50 hover:border-zinc-700/50"
            title="Close split (S)"
          >
            &#x2715;
          </button>
        </div>
        <div className="w-full h-full">{right}</div>
      </div>
    </div>
  );
}
