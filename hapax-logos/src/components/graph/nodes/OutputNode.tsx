import { memo, useEffect, useRef, useState } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import { LOGOS_API_URL } from "../../../config";

export interface OutputNodeData {
  label: string;
  [key: string]: unknown;
}

function OutputNodeInner({ id, data, selected }: NodeProps) {
  const { label } = data as OutputNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const [isStale, setIsStale] = useState(false);
  const lastSuccess = useRef(Date.now());

  useEffect(() => {
    let running = true;
    const poll = () => {
      if (!running || !imgRef.current) return;
      const url = `${LOGOS_API_URL}/studio/stream/fx?_t=${Date.now()}`;
      const loader = new Image();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
        lastSuccess.current = Date.now();
        setIsStale(false);
      };
      loader.onerror = () => {};
      loader.src = url;
    };
    poll();
    const pollTimer = setInterval(poll, 83);
    const staleTimer = setInterval(() => {
      if (Date.now() - lastSuccess.current > 5000) setIsStale(true);
    }, 2000);
    return () => {
      running = false;
      clearInterval(pollTimer);
      clearInterval(staleTimer);
    };
  }, []);

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        minWidth: 200,
        minHeight: 130,
        width: "100%",
        height: "100%",
        background: "var(--color-bg0)",
        border: "2px solid var(--color-green)",
        position: "relative",
      }}
    >
      <NodeResizer
        isVisible={!!selected}
        minWidth={200}
        minHeight={130}
        lineStyle={{ borderColor: "var(--color-green)" }}
        handleStyle={{ background: "var(--color-green)", width: 8, height: 8 }}
      />
      <img
        ref={imgRef}
        alt={label}
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
      />
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          padding: "4px 8px",
          fontSize: 11,
          color: "var(--color-fg3)",
          background: "linear-gradient(rgba(0,0,0,0.6), transparent)",
        }}
      >
        {label}
        {isStale && (
          <span style={{ marginLeft: 8, color: "var(--color-red)", fontSize: 10 }}>stale</span>
        )}
      </div>
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "var(--color-green)", width: 10, height: 10 }}
      />
    </div>
  );
}

export const OutputNode = memo(OutputNodeInner);
