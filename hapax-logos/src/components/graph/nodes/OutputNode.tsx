import { memo, useEffect, useRef, useState } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { ChainBuilder } from "../ChainBuilder";
import { SequenceBar } from "../SequenceBar";
import { useStudioGraph } from "../../../stores/studioGraphStore";

export interface OutputNodeData {
  label: string;
  [key: string]: unknown;
}

/** WebSocket-based frame receiver — push-based, no polling.
 *  Falls back to HTTP polling if WebSocket fails to connect. */
function useFxStream(imgRef: React.RefObject<HTMLImageElement | null>) {
  const lastSuccess = useRef(Date.now());
  const [isStale, setIsStale] = useState(false);
  const prevUrl = useRef<string | null>(null);

  useEffect(() => {
    let running = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (!running) return;
      ws = new WebSocket("ws://127.0.0.1:8053/ws/fx");
      ws.binaryType = "blob";

      ws.onmessage = (e) => {
        if (!running || !imgRef.current) return;
        // Revoke previous blob URL to prevent memory leak
        if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
        const url = URL.createObjectURL(e.data as Blob);
        imgRef.current.src = url;
        prevUrl.current = url;
        lastSuccess.current = Date.now();
        setIsStale(false);
      };

      ws.onclose = () => {
        if (running) reconnectTimer = setTimeout(connect, 1000);
      };

      ws.onerror = () => {
        ws?.close();
      };
    };

    connect();

    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 3000) setIsStale(true);
    }, 1000);

    return () => {
      running = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearInterval(staleTimer);
      ws?.close();
      if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
    };
  }, [imgRef]);

  return isStale;
}

function OutputNodeInner({ data, selected }: NodeProps) {
  const { label } = data as OutputNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const setIsFullscreen = useStudioGraph((s) => s.setOutputFullscreen);
  const isStale = useFxStream(imgRef);

  // Native dblclick listener on capture phase — fires before ReactFlow can swallow it
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      setIsFullscreen(true);
    };
    el.addEventListener("dblclick", handler, true);
    return () => el.removeEventListener("dblclick", handler, true);
  }, [setIsFullscreen]);

  return (
    <>
      <div
        ref={containerRef}
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
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {isStale && <span style={{ fontSize: 9, color: "#fb4934" }}>stale</span>}
            <button
              onClick={(e) => { e.stopPropagation(); setIsFullscreen(true); }}
              style={{
                background: "none",
                border: "1px solid #504945",
                borderRadius: 2,
                padding: "1px 5px",
                fontSize: 9,
                color: "#928374",
                cursor: "pointer",
                lineHeight: 1,
              }}
              title="Fullscreen (Shift+F)"
            >
              ⛶
            </button>
          </div>
        </div>
        <Handle
          type="target"
          position={Position.Left}
          style={{ width: 8, height: 8, background: "#3c3836", border: "2px solid #b8bb26", borderRadius: "50%" }}
        />
      </div>

    </>
  );
}

/** Fullscreen overlay — true borderless fullscreen via Tauri window API.
 *  Controls (chain builder + sequence bar) always visible at the bottom. */
function FullscreenOverlay({ onClose }: { onClose: () => void }) {
  const imgRef = useRef<HTMLImageElement>(null);

  // Own independent poll at 30fps — matches fx-snapshot rate
  useFxStream(imgRef);

  // Enter true borderless fullscreen on mount, restore on unmount
  useEffect(() => {
    import("@tauri-apps/api/core").then(({ invoke }) => {
      invoke("set_window_fullscreen", { fullscreen: true }).catch(() => {});
    });
    return () => {
      import("@tauri-apps/api/core").then(({ invoke }) => {
        invoke("set_window_fullscreen", { fullscreen: false }).catch(() => {});
      });
    };
  }, []);

  // Esc handler
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [onClose]);

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
      {/* Video — fills available space above controls */}
      <div
        style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", minHeight: 0 }}
      >
        <img
          ref={imgRef}
          alt="fullscreen output"
          draggable={false}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </div>

      {/* Controls — always visible at bottom */}
      <div
        style={{
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          background: "rgba(29,32,33,0.9)",
          borderTop: "1px solid #3c3836",
        }}
      >
        <SequenceBar />
        <ChainBuilder />
      </div>

      {/* Top bar — minimal, just exit hint */}
      <div
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          padding: "6px 12px",
          background: "rgba(0,0,0,0.4)",
          borderRadius: "0 0 0 4px",
        }}
      >
        <span
          onClick={onClose}
          style={{ fontSize: 10, color: "#504945", cursor: "pointer" }}
        >
          esc
        </span>
      </div>
    </div>
  );
}

export const OutputNode = memo(OutputNodeInner);
export { FullscreenOverlay };
