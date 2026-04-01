/**
 * Left drawer: categorized node palette for browsing and adding nodes.
 * Nodes are organized by the 10 aesthetic categories.
 * Click a node type to add it to the canvas at viewport center.
 */
import { useState, useCallback } from "react";
import { useReactFlow } from "@xyflow/react";
import { useStudioGraph, type StudioGraphState } from "../../stores/studioGraphStore";
import { AESTHETIC_CATEGORIES } from "./nodeRegistry";

type S = StudioGraphState;

/** All shader node types organized for the palette. */
const SOURCE_TYPES = [
  { type: "camera", label: "Camera", sourceType: "camera" },
  { type: "reverie", label: "Reverie Surface", sourceType: "reverie" },
  { type: "ir", label: "IR Perception", sourceType: "ir" },
  { type: "noise_gen", label: "Noise Generator", sourceType: "generator" },
  { type: "solid", label: "Solid Color", sourceType: "generator" },
] as const;

const UTILITY_TYPES = [
  { type: "output", label: "Output Preview" },
] as const;

let nodeCounter = 100;

export function NodePalette() {
  const leftDrawerOpen = useStudioGraph((s: S) => s.leftDrawerOpen);
  const toggleLeftDrawer = useStudioGraph((s: S) => s.toggleLeftDrawer);
  const updateNodes = useStudioGraph((s: S) => s.updateNodes);
  const markDirty = useStudioGraph((s: S) => s.markDirty);
  const { getViewport } = useReactFlow();

  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);

  const addNode = useCallback(
    (type: "source" | "shader" | "output", nodeType: string, extra?: Record<string, unknown>) => {
      const vp = getViewport();
      const id = `${nodeType}-${++nodeCounter}`;
      const centerX = (-vp.x + 400) / vp.zoom;
      const centerY = (-vp.y + 300) / vp.zoom;

      const baseData: Record<string, unknown> = { label: nodeType, ...extra };

      if (type === "source") {
        baseData.sourceType = extra?.sourceType ?? "camera";
        baseData.role = "brio-operator";
      } else if (type === "shader") {
        baseData.shaderType = nodeType;
        baseData.params = {};
      }

      updateNodes((nodes) => [
        ...nodes,
        {
          id,
          type,
          position: { x: centerX, y: centerY },
          data: baseData,
          ...(type === "output" ? { style: { width: 320, height: 200 } } : {}),
        },
      ]);
      markDirty();
    },
    [getViewport, updateNodes, markDirty],
  );

  if (!leftDrawerOpen) {
    return (
      <button
        onClick={toggleLeftDrawer}
        title="Node Palette (P)"
        style={{
          position: "absolute",
          top: 44,
          left: 8,
          zIndex: 15,
          background: "var(--color-bg1)",
          border: "1px solid var(--color-bg3)",
          borderRadius: 4,
          padding: "4px 8px",
          color: "var(--color-fg4)",
          cursor: "pointer",
          fontSize: 11,
        }}
      >
        + Nodes
      </button>
    );
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 36,
        left: 0,
        bottom: 0,
        width: 220,
        background: "var(--color-bg1)",
        borderRight: "1px solid var(--color-bg3)",
        zIndex: 20,
        overflowY: "auto",
        fontSize: 12,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 12px",
          borderBottom: "1px solid var(--color-bg3)",
        }}
      >
        <span style={{ fontWeight: 600, color: "var(--color-fg1)" }}>Nodes</span>
        <button
          onClick={toggleLeftDrawer}
          style={{ background: "none", border: "none", color: "var(--color-fg4)", cursor: "pointer" }}
        >
          ×
        </button>
      </div>

      {/* Sources */}
      <div style={{ padding: "8px 12px 4px" }}>
        <div style={{ fontSize: 10, color: "var(--color-fg4)", textTransform: "uppercase", marginBottom: 4 }}>
          Sources
        </div>
        {SOURCE_TYPES.map((s) => (
          <PaletteItem
            key={s.type}
            label={s.label}
            onClick={() => addNode("source", s.type, { sourceType: s.sourceType, label: s.label })}
          />
        ))}
      </div>

      {/* Output */}
      <div style={{ padding: "4px 12px" }}>
        <div style={{ fontSize: 10, color: "var(--color-fg4)", textTransform: "uppercase", marginBottom: 4 }}>
          Output
        </div>
        {UTILITY_TYPES.map((u) => (
          <PaletteItem
            key={u.type}
            label={u.label}
            onClick={() => addNode("output", u.type, { label: u.label })}
          />
        ))}
      </div>

      {/* Shader categories */}
      <div style={{ padding: "4px 12px 8px" }}>
        <div style={{ fontSize: 10, color: "var(--color-fg4)", textTransform: "uppercase", marginBottom: 4 }}>
          Effects
        </div>
        {AESTHETIC_CATEGORIES.map((cat) => (
          <div key={cat.id} style={{ marginBottom: 2 }}>
            <button
              onClick={() => setExpandedCategory(expandedCategory === cat.id ? null : cat.id)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                width: "100%",
                background: "none",
                border: "none",
                padding: "4px 0",
                color: expandedCategory === cat.id ? "var(--color-fg1)" : "var(--color-fg3)",
                cursor: "pointer",
                fontSize: 11,
                textAlign: "left",
              }}
            >
              <span>{cat.label}</span>
              <span style={{ fontSize: 9 }}>{expandedCategory === cat.id ? "▾" : "▸"}</span>
            </button>
            {expandedCategory === cat.id && (
              <div style={{ paddingLeft: 8 }}>
                {cat.types.map((t) => (
                  <PaletteItem
                    key={t}
                    label={t}
                    onClick={() => addNode("shader", t, { label: t, params: {} })}
                  />
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function PaletteItem({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        background: "none",
        border: "none",
        padding: "3px 4px",
        color: "var(--color-fg2)",
        cursor: "pointer",
        fontSize: 11,
        borderRadius: 3,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "var(--color-bg2)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "none";
      }}
    >
      {label}
    </button>
  );
}
