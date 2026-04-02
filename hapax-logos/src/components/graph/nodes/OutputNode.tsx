import { memo, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { LOGOS_API_URL } from "../../../config";
import { api } from "../../../api/client";
import { PRESET_CATEGORIES } from "../presetData";

export interface OutputNodeData {
  label: string;
  [key: string]: unknown;
}

/** Shared polling hook — same proven pattern as SourceNode (Image() preloader). */
function useFxPoll(imgRef: React.RefObject<HTMLImageElement | null>, intervalMs: number) {
  const lastSuccess = useRef(Date.now());
  const [isStale, setIsStale] = useState(false);

  useEffect(() => {
    let running = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = () => {
      if (!running || !imgRef.current) {
        timer = setTimeout(poll, intervalMs);
        return;
      }
      const loader = new Image();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
        // Schedule next poll AFTER this frame loads — adaptive chain, no overlap
        if (running) timer = setTimeout(poll, intervalMs);
      };
      loader.onerror = () => {
        if (running) timer = setTimeout(poll, intervalMs * 2); // back off on error
      };
      loader.src = `${LOGOS_API_URL}/studio/stream/fx?_t=${Date.now()}`;
    };
    poll();
    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 5000) setIsStale(true);
    }, 2000);
    return () => {
      running = false;
      if (timer) clearTimeout(timer);
      clearInterval(staleTimer);
    };
  }, [imgRef, intervalMs]);

  return isStale;
}

function OutputNodeInner({ data, selected }: NodeProps) {
  const { label } = data as OutputNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const isStale = useFxPoll(imgRef, 100);

  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setIsFullscreen(false);
      }
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [isFullscreen]);

  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setIsFullscreen(true);
  }, []);

  return (
    <>
      <div
        onDoubleClickCapture={handleDoubleClick}
        style={{
          minWidth: 220,
          minHeight: 140,
          width: "100%",
          height: "100%",
          background: "#1d2021",
          border: selected ? "1px solid #b8bb26" : "1px solid #3c3836",
          borderRadius: 4,
          position: "relative",
          overflow: "hidden",
          fontFamily: "JetBrains Mono, monospace",
          cursor: "pointer",
        }}
      >
        <NodeResizer
          isVisible={!!selected}
          minWidth={220}
          minHeight={140}
          lineStyle={{ borderColor: "#b8bb26", borderWidth: 1 }}
          handleStyle={{ background: "#b8bb26", width: 6, height: 6, borderRadius: 2, border: "none" }}
        />
        <img
          ref={imgRef}
          alt={label}
          draggable={false}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            padding: "4px 8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "linear-gradient(transparent, rgba(29,32,33,0.85))",
          }}
        >
          <span style={{ fontSize: 10, color: "#bdae93" }}>{label}</span>
          {isStale && <span style={{ fontSize: 9, color: "#fb4934" }}>stale</span>}
        </div>
        <Handle
          type="target"
          position={Position.Left}
          style={{ width: 8, height: 8, background: "#3c3836", border: "2px solid #b8bb26", borderRadius: "50%" }}
        />
      </div>

      {isFullscreen &&
        createPortal(
          <FullscreenOverlay onClose={() => setIsFullscreen(false)} />,
          document.body,
        )}
    </>
  );
}

/** Fullscreen overlay — has its OWN poll, independent of parent OutputNode. */
function FullscreenOverlay({ onClose }: { onClose: () => void }) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [showPresets, setShowPresets] = useState(false);
  const [activePreset, setActivePreset] = useState("");

  // Own independent poll — not shared with parent
  useFxPoll(imgRef, 83);

  const allPresets = PRESET_CATEGORIES.flatMap((cat) =>
    cat.presets.map((p) => ({ name: p, category: cat.label })),
  );

  const selectPreset = useCallback((name: string) => {
    api.post("/studio/effect/select", { preset: name }).catch(() => {});
    setActivePreset(name);
  }, []);

  useEffect(() => {
    api.get<{ preset: string }>("/studio/effect/current")
      .then((r) => { if (r?.preset) setActivePreset(r.preset); })
      .catch(() => {});
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: "100vw",
        height: "100vh",
        zIndex: 2147483647,
        background: "#000000",
        display: "flex",
        flexDirection: "column",
        fontFamily: "JetBrains Mono, monospace",
        isolation: "isolate",
      }}
    >
      {/* Video */}
      <div
        onClick={onClose}
        style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", overflow: "hidden" }}
      >
        <img
          ref={imgRef}
          alt="fullscreen output"
          draggable={false}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </div>

      {/* Top bar */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 16px",
          background: "linear-gradient(rgba(0,0,0,0.6), transparent)",
        }}
      >
        <span style={{ fontSize: 11, color: "#928374" }}>{activePreset || "output"}</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={(e) => { e.stopPropagation(); setShowPresets(!showPresets); }}
            style={{
              background: "none",
              border: "1px solid #504945",
              borderRadius: 2,
              padding: "2px 8px",
              fontSize: 10,
              color: showPresets ? "#fabd2f" : "#928374",
              cursor: "pointer",
            }}
          >
            presets
          </button>
          <span style={{ fontSize: 10, color: "#504945" }}>esc to exit</span>
        </div>
      </div>

      {/* Preset strip */}
      {showPresets && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            background: "rgba(29,32,33,0.92)",
            borderTop: "1px solid #3c3836",
            padding: "8px 16px",
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
            maxHeight: 180,
            overflowY: "auto",
          }}
        >
          {allPresets.map(({ name }) => (
            <button
              key={name}
              onClick={() => selectPreset(name)}
              style={{
                background: name === activePreset ? "#3c3836" : "none",
                border: name === activePreset ? "1px solid #fabd2f" : "1px solid #504945",
                borderRadius: 2,
                padding: "3px 8px",
                fontSize: 10,
                color: name === activePreset ? "#ebdbb2" : "#928374",
                cursor: "pointer",
              }}
            >
              {name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export const OutputNode = memo(OutputNodeInner);
