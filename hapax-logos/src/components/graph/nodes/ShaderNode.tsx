import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useStudioGraph } from "../../../stores/studioGraphStore";

export interface ShaderNodeData {
  shaderType: string;
  label: string;
  params: Record<string, number | string | boolean>;
  [key: string]: unknown;
}

function paramSummary(params: Record<string, number | string | boolean>): string {
  const first = Object.entries(params)[0];
  if (!first) return "";
  const [key, val] = first;
  if (typeof val === "number") return `${key}: ${val.toFixed(2)}`;
  return `${key}: ${val}`;
}

function ShaderNodeInner({ id, data }: NodeProps) {
  const { shaderType, label, params } = data as ShaderNodeData;
  const selectedNodeId = useStudioGraph((s) => s.selectedNodeId);
  const selectNode = useStudioGraph((s) => s.selectNode);
  const isSelected = selectedNodeId === id;

  return (
    <div
      onClick={() => selectNode(id)}
      className="rounded-lg cursor-pointer"
      style={{
        width: 140,
        background: "var(--color-bg1)",
        border: `2px solid ${isSelected ? "var(--color-blue)" : "var(--color-bg3)"}`,
        transition: "border-color 0.15s",
      }}
    >
      <div
        style={{
          padding: "6px 8px 2px",
          fontSize: 12,
          fontWeight: 600,
          color: "var(--color-fg1)",
        }}
      >
        {label || shaderType}
      </div>
      <div
        style={{
          padding: "0 8px 6px",
          fontSize: 10,
          color: "var(--color-fg4)",
          fontFamily: "monospace",
        }}
      >
        {paramSummary(params)}
      </div>
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: "var(--color-fg4)", width: 8, height: 8 }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: "var(--color-fg4)", width: 8, height: 8 }}
      />
    </div>
  );
}

export const ShaderNode = memo(ShaderNodeInner);
