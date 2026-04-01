/**
 * Side sheet for editing node params and modulation routing.
 * Opens when a shader node is selected on the canvas.
 */
import { useCallback } from "react";
import { useStudioGraph, type StudioGraphState } from "../../stores/studioGraphStore";
import { MODULATION_SIGNALS, type ModulationBinding } from "./nodeRegistry";
import type { ShaderNodeData } from "./nodes/ShaderNode";

type S = StudioGraphState;

export function NodeDetailSheet() {
  const selectedNodeId = useStudioGraph((s: S) => s.selectedNodeId);
  const nodes = useStudioGraph((s: S) => s.nodes);
  const updateNodes = useStudioGraph((s: S) => s.updateNodes);
  const markDirty = useStudioGraph((s: S) => s.markDirty);

  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node || node.type !== "shader") return null;

  const data = node.data as ShaderNodeData;
  const params = data.params ?? {};
  const modulations: Record<string, ModulationBinding> = (data as Record<string, unknown>)
    .modulations as Record<string, ModulationBinding> ?? {};

  return (
    <div
      style={{
        position: "absolute",
        top: 36,
        right: 0,
        bottom: 0,
        width: 280,
        background: "var(--color-bg1)",
        borderLeft: "1px solid var(--color-bg3)",
        zIndex: 20,
        overflowY: "auto",
        padding: "12px",
        fontSize: 12,
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-fg1)" }}>
          {data.label || data.shaderType}
        </div>
        <div style={{ fontSize: 11, color: "var(--color-fg4)", fontFamily: "monospace" }}>
          {data.shaderType}
          {(data as Record<string, unknown>).temporal ? " · temporal" : ""}
        </div>
      </div>

      {/* Params */}
      {Object.entries(params).map(([key, value]) => (
        <ParamRow
          key={key}
          nodeId={node.id}
          paramKey={key}
          value={value}
          modulation={modulations[key]}
          updateNodes={updateNodes}
          markDirty={markDirty}
        />
      ))}

      {Object.keys(params).length === 0 && (
        <div style={{ color: "var(--color-fg4)", fontStyle: "italic" }}>No parameters</div>
      )}
    </div>
  );
}

interface ParamRowProps {
  nodeId: string;
  paramKey: string;
  value: number | string | boolean;
  modulation?: ModulationBinding;
  updateNodes: (updater: (nodes: S["nodes"]) => S["nodes"]) => void;
  markDirty: () => void;
}

function ParamRow({ nodeId, paramKey, value, modulation, updateNodes, markDirty }: ParamRowProps) {
  const updateParam = useCallback(
    (newValue: number | string | boolean) => {
      updateNodes((nodes) =>
        nodes.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  params: { ...(n.data as ShaderNodeData).params, [paramKey]: newValue },
                },
              }
            : n,
        ),
      );
      markDirty();
    },
    [nodeId, paramKey, updateNodes, markDirty],
  );

  const updateModulation = useCallback(
    (patch: Partial<ModulationBinding>) => {
      updateNodes((nodes) =>
        nodes.map((n) => {
          if (n.id !== nodeId) return n;
          const existing =
            ((n.data as Record<string, unknown>).modulations as Record<string, ModulationBinding>) ?? {};
          return {
            ...n,
            data: {
              ...n.data,
              modulations: {
                ...existing,
                [paramKey]: {
                  ...{ source: "" as const, scale: 1, offset: 0, smoothing: 0.85 },
                  ...existing[paramKey],
                  ...patch,
                },
              },
            },
          };
        }),
      );
      markDirty();
    },
    [nodeId, paramKey, updateNodes, markDirty],
  );

  const hasModulation = modulation && modulation.source !== "";

  return (
    <div style={{ marginBottom: 10 }}>
      {/* Param label + value */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
        <span style={{ color: "var(--color-fg2)" }}>
          {paramKey}
          {hasModulation && (
            <span style={{ color: "var(--color-yellow)", marginLeft: 4, fontSize: 10 }}>●</span>
          )}
        </span>
        <span style={{ color: "var(--color-fg4)", fontFamily: "monospace" }}>
          {typeof value === "number" ? value.toFixed(2) : String(value)}
        </span>
      </div>

      {/* Slider for numbers */}
      {typeof value === "number" && (
        <input
          type="range"
          min={0}
          max={value > 1 ? Math.ceil(value * 2) : 1}
          step={0.01}
          value={value}
          onChange={(e) => updateParam(parseFloat(e.target.value))}
          style={{ width: "100%", accentColor: "var(--color-blue)" }}
        />
      )}

      {/* Enum for strings */}
      {typeof value === "string" && (
        <input
          type="text"
          value={value}
          onChange={(e) => updateParam(e.target.value)}
          style={{
            width: "100%",
            background: "var(--color-bg0)",
            border: "1px solid var(--color-bg3)",
            borderRadius: 4,
            color: "var(--color-fg1)",
            padding: "2px 6px",
            fontSize: 11,
          }}
        />
      )}

      {/* Bool for booleans */}
      {typeof value === "boolean" && (
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={value} onChange={(e) => updateParam(e.target.checked)} />
          <span style={{ color: "var(--color-fg3)" }}>{value ? "on" : "off"}</span>
        </label>
      )}

      {/* Modulation routing */}
      <div style={{ marginTop: 4 }}>
        <select
          value={modulation?.source ?? ""}
          onChange={(e) => updateModulation({ source: e.target.value as ModulationBinding["source"] })}
          style={{
            width: "100%",
            background: "var(--color-bg0)",
            border: "1px solid var(--color-bg3)",
            borderRadius: 4,
            color: hasModulation ? "var(--color-yellow)" : "var(--color-fg4)",
            padding: "2px 4px",
            fontSize: 10,
          }}
        >
          <option value="">no modulation</option>
          {MODULATION_SIGNALS.map((sig) => (
            <option key={sig.id} value={sig.id}>
              {sig.label}
            </option>
          ))}
        </select>

        {/* Scale/offset/smoothing when modulation is active */}
        {hasModulation && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4, marginTop: 4 }}>
            <div>
              <div style={{ fontSize: 9, color: "var(--color-fg4)" }}>scale</div>
              <input
                type="number"
                step={0.1}
                value={modulation.scale}
                onChange={(e) => updateModulation({ scale: parseFloat(e.target.value) || 1 })}
                style={{
                  width: "100%",
                  background: "var(--color-bg0)",
                  border: "1px solid var(--color-bg3)",
                  borderRadius: 3,
                  color: "var(--color-fg2)",
                  padding: "1px 4px",
                  fontSize: 10,
                }}
              />
            </div>
            <div>
              <div style={{ fontSize: 9, color: "var(--color-fg4)" }}>offset</div>
              <input
                type="number"
                step={0.1}
                value={modulation.offset}
                onChange={(e) => updateModulation({ offset: parseFloat(e.target.value) || 0 })}
                style={{
                  width: "100%",
                  background: "var(--color-bg0)",
                  border: "1px solid var(--color-bg3)",
                  borderRadius: 3,
                  color: "var(--color-fg2)",
                  padding: "1px 4px",
                  fontSize: 10,
                }}
              />
            </div>
            <div>
              <div style={{ fontSize: 9, color: "var(--color-fg4)" }}>smooth</div>
              <input
                type="number"
                step={0.05}
                min={0}
                max={1}
                value={modulation.smoothing}
                onChange={(e) => updateModulation({ smoothing: parseFloat(e.target.value) || 0.85 })}
                style={{
                  width: "100%",
                  background: "var(--color-bg0)",
                  border: "1px solid var(--color-bg3)",
                  borderRadius: 3,
                  color: "var(--color-fg2)",
                  padding: "1px 4px",
                  fontSize: 10,
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
