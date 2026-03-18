import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
  MarkerType,
  Handle,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { invoke } from "@tauri-apps/api/core";

// ── Types from Rust ─────────────────────────────────────────────────

interface NodeMetrics {
  [key: string]: unknown;
}

interface FlowNode {
  id: string;
  label: string;
  status: string;
  age_s: number;
  metrics: NodeMetrics;
}

interface FlowEdge {
  source: string;
  target: string;
  active: boolean;
  label: string;
}

interface SystemFlowState {
  nodes: FlowNode[];
  edges: FlowEdge[];
  timestamp: number;
}

// ── Layout positions (anatomical arrangement) ───────────────────────

const POSITIONS: Record<string, { x: number; y: number }> = {
  // Top: sensory input
  perception: { x: 400, y: 50 },
  // Middle row: processing
  stimmung: { x: 150, y: 220 },
  temporal: { x: 400, y: 220 },
  consent: { x: 650, y: 220 },
  // Core: integration
  apperception: { x: 250, y: 400 },
  phenomenal: { x: 500, y: 400 },
  // Output row
  voice: { x: 400, y: 580 },
  engine: { x: 100, y: 580 },
  compositor: { x: 700, y: 580 },
};

// ── Status colors ───────────────────────────────────────────────────

const STATUS_COLORS: Record<string, { bg: string; border: string; glow: string }> = {
  active: {
    bg: "rgba(16, 185, 129, 0.12)",
    border: "#10b981",
    glow: "0 0 20px rgba(16, 185, 129, 0.3)",
  },
  stale: {
    bg: "rgba(245, 158, 11, 0.12)",
    border: "#f59e0b",
    glow: "0 0 20px rgba(245, 158, 11, 0.2)",
  },
  offline: {
    bg: "rgba(107, 114, 128, 0.08)",
    border: "#4b5563",
    glow: "none",
  },
};

// ── Custom node component ───────────────────────────────────────────

function SystemNode({ data }: { data: FlowNode }) {
  const colors = STATUS_COLORS[data.status] || STATUS_COLORS.offline;
  const metrics = data.metrics || {};

  return (
    <div
      style={{
        background: colors.bg,
        border: `2px solid ${colors.border}`,
        borderRadius: "12px",
        padding: "12px 16px",
        minWidth: "160px",
        boxShadow: colors.glow,
        transition: "all 0.5s ease",
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: colors.border }} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
        <span style={{ color: "#e5e7eb", fontSize: "13px", fontWeight: 600 }}>
          {data.label}
        </span>
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            background: colors.border,
            boxShadow: data.status === "active" ? `0 0 8px ${colors.border}` : "none",
            animation: data.status === "active" ? "pulse 2s ease-in-out infinite" : "none",
          }}
        />
      </div>

      <div style={{ fontSize: "11px", color: "#9ca3af", lineHeight: "1.5" }}>
        {Object.entries(metrics).map(([key, val]) => {
          if (val === null || val === undefined || val === "") return null;
          const display = typeof val === "number"
            ? val % 1 === 0 ? val.toString() : val.toFixed(2)
            : String(val);
          return (
            <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
              <span style={{ color: "#6b7280" }}>{key.replace(/_/g, " ")}</span>
              <span style={{ color: "#d1d5db" }}>{display}</span>
            </div>
          );
        })}
        {data.status !== "offline" && (
          <div style={{ color: "#6b7280", marginTop: "4px", fontSize: "10px" }}>
            {data.age_s < 1 ? "< 1s" : `${data.age_s.toFixed(0)}s`} ago
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} style={{ background: colors.border }} />
    </div>
  );
}

const nodeTypes = { system: SystemNode };

// ── Detail panel ────────────────────────────────────────────────────

function DetailPanel({ node, onClose }: { node: FlowNode | null; onClose: () => void }) {
  if (!node) return null;
  const colors = STATUS_COLORS[node.status] || STATUS_COLORS.offline;

  return (
    <div
      style={{
        position: "absolute",
        right: "16px",
        top: "16px",
        width: "320px",
        background: "rgba(17, 24, 39, 0.95)",
        border: `1px solid ${colors.border}`,
        borderRadius: "12px",
        padding: "20px",
        zIndex: 100,
        fontFamily: "'JetBrains Mono', monospace",
        boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "16px" }}>
        <h3 style={{ color: "#e5e7eb", margin: 0, fontSize: "16px" }}>{node.label}</h3>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "18px" }}
        >
          ×
        </button>
      </div>
      <div style={{ color: "#9ca3af", fontSize: "12px" }}>
        <div style={{ marginBottom: "8px" }}>
          <span style={{ color: colors.border }}>●</span> {node.status} — {node.age_s.toFixed(1)}s ago
        </div>
        <pre style={{ background: "rgba(0,0,0,0.3)", padding: "12px", borderRadius: "8px", overflow: "auto", maxHeight: "400px", fontSize: "11px", color: "#d1d5db" }}>
          {JSON.stringify(node.metrics, null, 2)}
        </pre>
      </div>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────

export function FlowPage() {
  const [flowState, setFlowState] = useState<SystemFlowState | null>(null);
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Poll system flow state every 3s
  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const state = await invoke<SystemFlowState>("get_system_flow");
        if (mounted) setFlowState(state);
      } catch (e) {
        console.warn("Failed to get system flow:", e);
      }
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Convert flow state to React Flow nodes/edges
  useEffect(() => {
    if (!flowState) return;

    const rfNodes: Node[] = flowState.nodes.map((n) => ({
      id: n.id,
      type: "system",
      position: POSITIONS[n.id] || { x: 0, y: 0 },
      data: n,
      draggable: true,
    }));

    const rfEdges: Edge[] = flowState.edges.map((e, i) => ({
      id: `${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      animated: e.active,
      label: e.label,
      style: {
        stroke: e.active ? "#10b981" : "#374151",
        strokeWidth: e.active ? 2 : 1,
        opacity: e.active ? 1 : 0.3,
      },
      labelStyle: {
        fontSize: "10px",
        fill: e.active ? "#9ca3af" : "#4b5563",
        fontFamily: "'JetBrains Mono', monospace",
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: e.active ? "#10b981" : "#374151",
        width: 16,
        height: 16,
      },
    }));

    setNodes(rfNodes);
    setEdges(rfEdges);
  }, [flowState, setNodes, setEdges]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setSelectedNode(node.data as FlowNode);
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", background: "#0a0f1a", position: "relative" }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        .react-flow__edge-path {
          transition: stroke 0.5s ease, opacity 0.5s ease;
        }
      `}</style>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1f2937" gap={24} size={1} />
        <Controls
          style={{ background: "#1f2937", borderColor: "#374151" }}
        />
      </ReactFlow>

      <DetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />

      {/* Title */}
      <div
        style={{
          position: "absolute",
          top: "16px",
          left: "16px",
          color: "#6b7280",
          fontSize: "12px",
          fontFamily: "'JetBrains Mono', monospace",
          zIndex: 10,
        }}
      >
        SYSTEM ANATOMY — {flowState ? `${flowState.nodes.filter(n => n.status === "active").length}/${flowState.nodes.length} active` : "connecting..."}
      </div>
    </div>
  );
}
