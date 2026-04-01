import { memo, useEffect, useRef } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { LOGOS_API_URL } from "../../../config";
import { useStudioGraph } from "../../../stores/studioGraphStore";

export interface SourceNodeData {
  sourceType: "camera" | "reverie" | "ir" | "generator";
  role: string;
  label: string;
  [key: string]: unknown;
}

function SourceNodeInner({ data }: NodeProps) {
  const { sourceType, role, label } = data as SourceNodeData;
  const imgRef = useRef<HTMLImageElement>(null);
  const cameraStatuses = useStudioGraph((s) => s.cameraStatuses);
  const status = cameraStatuses[role] ?? "offline";

  useEffect(() => {
    if (sourceType !== "camera") return;
    let running = true;
    const poll = () => {
      if (!running || !imgRef.current) return;
      const url = `${LOGOS_API_URL}/studio/stream/cameras/batch?roles=${role}&_t=${Date.now()}`;
      const loader = new Image();
      loader.onload = () => {
        if (running && imgRef.current) imgRef.current.src = loader.src;
      };
      loader.src = url;
    };
    poll();
    const timer = setInterval(poll, 250);
    return () => {
      running = false;
      clearInterval(timer);
    };
  }, [sourceType, role]);

  const statusColor =
    status === "active"
      ? "var(--color-green)"
      : status === "starting"
        ? "var(--color-yellow)"
        : "var(--color-red)";

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{
        width: 140,
        background: "var(--color-bg1)",
        border: "2px solid var(--color-yellow)",
      }}
    >
      <div
        style={{
          width: 140,
          height: 80,
          background: "var(--color-bg0)",
          position: "relative",
        }}
      >
        {sourceType === "camera" && (
          <img
            ref={imgRef}
            alt={label}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        )}
        {sourceType !== "camera" && (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--color-fg4)",
              fontSize: 11,
            }}
          >
            {sourceType === "reverie" ? "Reverie" : sourceType === "ir" ? "IR" : "Gen"}
          </div>
        )}
        {sourceType === "camera" && (
          <div
            style={{
              position: "absolute",
              top: 4,
              right: 4,
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: statusColor,
            }}
          />
        )}
      </div>
      <div
        style={{
          padding: "4px 8px",
          fontSize: 11,
          color: "var(--color-fg2)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {label}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: "var(--color-yellow)", width: 10, height: 10 }}
      />
    </div>
  );
}

export const SourceNode = memo(SourceNodeInner);
