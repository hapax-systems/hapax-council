import { memo, useEffect, useRef, useState } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
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
  const staleRef = useRef(false);
  // Double-buffer: keep previous URL alive until new frame loads
  const urlA = useRef<string | null>(null);
  const urlB = useRef<string | null>(null);
  const useA = useRef(true);

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
        const url = URL.createObjectURL(e.data as Blob);
        // Double-buffer: revoke the OLDER url, not the current one
        if (useA.current) {
          if (urlB.current) URL.revokeObjectURL(urlB.current);
          urlA.current = url;
        } else {
          if (urlA.current) URL.revokeObjectURL(urlA.current);
          urlB.current = url;
        }
        useA.current = !useA.current;
        imgRef.current.src = url;
        lastSuccess.current = Date.now();
        // Only trigger React re-render when stale state actually changes
        if (staleRef.current) {
          staleRef.current = false;
          setIsStale(false);
        }
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
      const nowStale = Date.now() - lastSuccess.current > 3000;
      if (nowStale !== staleRef.current) {
        staleRef.current = nowStale;
        setIsStale(nowStale);
      }
    }, 1000);

    return () => {
      running = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      clearInterval(staleTimer);
      ws?.close();
      if (urlA.current) URL.revokeObjectURL(urlA.current);
      if (urlB.current) URL.revokeObjectURL(urlB.current);
    };
  }, [imgRef]);

  return isStale;
}

function OutputNodeInner({ data, selected }: NodeProps) {
  const { label } = data as OutputNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isFullscreen = useStudioGraph((s) => s.outputFullscreen);
  const setIsFullscreen = useStudioGraph((s) => s.setOutputFullscreen);
  // Don't run stream when fullscreen is active — FullscreenOverlay has its own
  const isStale = useFxStream(isFullscreen ? { current: null } : imgRef);

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
          // ``contain`` letterboxes when the node aspect-ratio differs from
          // the compositor's 16:9 — ``cover`` would CROP the right edge,
          // hiding the right-edge wards (chat_keyword_legend at x=1760,
          // stance_indicator at x=1800, thinking_indicator at x=1620,
          // whos_here at x=1460) which sit at the canvas's far right.
          style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
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
 *  Video fills the entire viewport; controls hidden (esc to exit). */
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
      {/* Video — fills available space above controls. width/height: 100%
          makes the img element fill the container; objectFit: contain
          scales the source content to fit the element while preserving
          aspect (letterbox bars when aspect mismatches). The earlier
          attempt to use max-width/max-height + auto sized the img element
          to its INTRINSIC dimensions (1280×720 for the compositor's
          downscaled snapshot), leaving large black bars even on a
          1920×1050 viewport. The right-edge ward "clipping" that
          motivated that change was actually the layout coord rescale
          bug fixed in #1042 — the CSS path was correct all along. */}
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          minHeight: 0,
        }}
      >
        <img
          ref={imgRef}
          alt="fullscreen output"
          draggable={false}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
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
