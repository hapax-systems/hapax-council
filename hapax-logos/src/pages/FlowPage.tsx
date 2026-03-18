import { useCallback, useEffect, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type EdgeProps,
  Position,
  MarkerType,
  Handle,
  useNodesState,
  useEdgesState,
  getBezierPath,
  BaseEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { invoke } from "@tauri-apps/api/core";

// ── Types ───────────────────────────────────────────────────────────

interface NodeMetrics {
  [key: string]: unknown;
}

interface FlowNode {
  id: string;
  label: string;
  status: string;
  age_s: number;
  metrics: NodeMetrics;
  [key: string]: unknown;
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

// ── Layout (anatomical arrangement) ─────────────────────────────────

const POSITIONS: Record<string, { x: number; y: number }> = {
  perception: { x: 400, y: 50 },
  stimmung: { x: 120, y: 230 },
  temporal: { x: 400, y: 230 },
  consent: { x: 680, y: 230 },
  apperception: { x: 220, y: 420 },
  phenomenal: { x: 520, y: 420 },
  voice: { x: 400, y: 610 },
  engine: { x: 80, y: 610 },
  compositor: { x: 720, y: 610 },
};

// ── Colors ──────────────────────────────────────────────────────────

const COLORS = {
  active: { bg: "rgba(16, 185, 129, 0.10)", border: "#10b981", glow: "rgba(16, 185, 129, 0.25)" },
  stale: { bg: "rgba(245, 158, 11, 0.10)", border: "#f59e0b", glow: "rgba(245, 158, 11, 0.15)" },
  offline: { bg: "rgba(107, 114, 128, 0.06)", border: "#4b5563", glow: "transparent" },
};

// Staleness → edge color interpolation (green → amber)
function edgeColor(age_s: number, active: boolean): string {
  if (!active) return "#2a2f3a";
  if (age_s < 3) return "#10b981";    // fresh green
  if (age_s < 8) return "#34d399";    // light green
  if (age_s < 15) return "#a3e635";   // yellow-green
  if (age_s < 25) return "#facc15";   // yellow
  return "#f59e0b";                    // amber (stale)
}

// Breathing speed: active nodes pulse faster based on recency
function breathDuration(age_s: number, status: string): string {
  if (status !== "active") return "0s";
  if (age_s < 3) return "1.5s";   // fast breathing
  if (age_s < 10) return "2.5s";  // normal
  if (age_s < 20) return "4s";    // slow
  return "6s";                     // very slow
}

// Node opacity: unchanged nodes fade (attention decay)
function nodeOpacity(age_s: number, status: string): number {
  if (status === "offline") return 0.5;
  if (age_s < 5) return 1.0;
  if (age_s < 15) return 0.95;
  if (age_s < 30) return 0.85;
  return 0.7; // faded — hasn't updated in 30s+
}

// ── Flowing Edge (particles + staleness color) ──────────────────────

function FlowingEdge({
  id, sourceX, sourceY, targetX, targetY,
  sourcePosition, targetPosition, data,
}: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const active = (data as Record<string, unknown>)?.active as boolean ?? false;
  const age = (data as Record<string, unknown>)?.age_s as number ?? 999;
  const isGated = (data as Record<string, unknown>)?.gated as boolean ?? false;
  const edgeLabel = (data as Record<string, unknown>)?.label as string ?? "";
  const color = edgeColor(age, active);

  // Particle count based on activity (more particles = more throughput)
  const particleCount = active ? (age < 5 ? 3 : age < 15 ? 2 : 1) : 0;

  return (
    <g>
      {/* Base edge path */}
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: color,
          strokeWidth: active ? 1.5 : 0.8,
          opacity: active ? 0.7 : 0.15,
          transition: "stroke 1s ease, opacity 1s ease",
        }}
      />

      {/* Consent gate barrier */}
      {isGated && (
        <circle r="4" fill="#f59e0b" opacity="0.8">
          <animateMotion dur="0.01s" path={path} fill="freeze" keyPoints="0.5" keyTimes="0" />
        </circle>
      )}

      {/* Flowing particles */}
      {Array.from({ length: particleCount }).map((_, i) => {
        const delay = (i * (1.0 / particleCount));
        const speed = age < 5 ? "2s" : age < 15 ? "3.5s" : "5s";
        return (
          <circle key={i} r="2" fill={color} opacity="0.8">
            <animateMotion
              dur={speed}
              path={path}
              repeatCount="indefinite"
              begin={`${delay}s`}
            />
          </circle>
        );
      })}

      {/* Edge label */}
      {edgeLabel && (
        <text>
          <textPath
            href={`#${id}`}
            startOffset="50%"
            textAnchor="middle"
            style={{
              fontSize: "9px",
              fill: active ? "#6b7280" : "#2a2f3a",
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {edgeLabel}
          </textPath>
        </text>
      )}
    </g>
  );
}

const edgeTypes = { flowing: FlowingEdge };

// ── Sparkline (tiny SVG, no axes, no labels) ────────────────────────

// Which metric to sparkline per node
const SPARKLINE_METRIC: Record<string, string> = {
  perception: "flow_score",
  stimmung: "resource_pressure",
  temporal: "max_surprise",
  apperception: "coherence",
  voice: "activation",
  compositor: "",
  phenomenal: "",
  engine: "",
  consent: "",
};

// Global history buffer: nodeId → metric values (last 30)
const sparklineHistory: Record<string, number[]> = {};
const SPARKLINE_MAX = 30;

function pushSparkline(nodeId: string, value: number | undefined | null) {
  if (value === null || value === undefined || typeof value !== "number") return;
  if (!sparklineHistory[nodeId]) sparklineHistory[nodeId] = [];
  const buf = sparklineHistory[nodeId];
  buf.push(value);
  if (buf.length > SPARKLINE_MAX) buf.shift();
}

function Sparkline({ nodeId, color }: { nodeId: string; color: string }) {
  const values = sparklineHistory[nodeId];
  if (!values || values.length < 3) return null;

  const w = 120;
  const h = 20;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={w} height={h} style={{ opacity: 0.5, marginTop: "4px" }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── Custom Node (breathing + decay + sparkline) ─────────────────────

function SystemNode({ data }: { data: FlowNode }) {
  const colors = COLORS[data.status as keyof typeof COLORS] || COLORS.offline;
  const metrics = data.metrics || {};
  const breathe = breathDuration(data.age_s, data.status);
  const opacity = nodeOpacity(data.age_s, data.status);

  // Push to sparkline history
  const sparkMetric = SPARKLINE_METRIC[data.id];
  if (sparkMetric && metrics[sparkMetric] !== undefined) {
    pushSparkline(data.id, metrics[sparkMetric] as number);
  }

  // State machine for consent node
  const consentStates = ["none", "guest_detected", "consent_pending", "consent_granted", "consent_refused"];
  const currentConsent = data.id === "consent" ? (metrics.phase as string || "none") : null;

  return (
    <div
      style={{
        background: colors.bg,
        border: `1.5px solid ${colors.border}`,
        borderRadius: "12px",
        padding: "10px 14px",
        minWidth: "150px",
        maxWidth: "200px",
        opacity,
        transition: "opacity 2s ease, box-shadow 1s ease",
        fontFamily: "'JetBrains Mono', monospace",
        animation: breathe !== "0s" ? `breathe ${breathe} ease-in-out infinite` : "none",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: colors.border, width: 6, height: 6 }} />

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "5px" }}>
        <span style={{ color: "#e5e7eb", fontSize: "12px", fontWeight: 600, letterSpacing: "0.02em" }}>
          {data.label}
        </span>
        <span
          style={{
            width: "6px",
            height: "6px",
            borderRadius: "50%",
            background: colors.border,
            boxShadow: data.status === "active" ? `0 0 6px ${colors.border}` : "none",
          }}
        />
      </div>

      {/* Metrics */}
      <div style={{ fontSize: "10px", color: "#9ca3af", lineHeight: "1.6" }}>
        {Object.entries(metrics).map(([key, val]) => {
          if (val === null || val === undefined || val === "") return null;
          if (key === "phase" && data.id === "consent") return null; // rendered as state dots
          const display = typeof val === "number"
            ? val % 1 === 0 ? val.toString() : val.toFixed(2)
            : String(val);
          return (
            <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: "6px" }}>
              <span style={{ color: "#4b5563" }}>{key.replace(/_/g, " ")}</span>
              <span style={{ color: "#d1d5db" }}>{display}</span>
            </div>
          );
        })}

        {/* State machine dots for consent */}
        {currentConsent && (
          <div style={{ display: "flex", gap: "4px", marginTop: "6px", justifyContent: "center" }}>
            {consentStates.map((s) => (
              <span
                key={s}
                title={s.replace(/_/g, " ")}
                style={{
                  width: "6px",
                  height: "6px",
                  borderRadius: "50%",
                  background: s === currentConsent ? colors.border : "transparent",
                  border: `1px solid ${s === currentConsent ? colors.border : "#4b5563"}`,
                  transition: "all 0.5s ease",
                }}
              />
            ))}
          </div>
        )}

        {/* Sparkline */}
        {SPARKLINE_METRIC[data.id] && (
          <Sparkline nodeId={data.id} color={colors.border} />
        )}

        {/* Age indicator */}
        {data.status !== "offline" && (
          <div style={{ color: "#374151", marginTop: "3px", fontSize: "9px", textAlign: "right" }}>
            {data.age_s < 1 ? "now" : `${data.age_s.toFixed(0)}s`}
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} style={{ background: colors.border, width: 6, height: 6 }} />
    </div>
  );
}

const nodeTypes = { system: SystemNode };

// ── Detail Panel ────────────────────────────────────────────────────

function DetailPanel({ node, onClose }: { node: FlowNode | null; onClose: () => void }) {
  if (!node) return null;
  const colors = COLORS[node.status as keyof typeof COLORS] || COLORS.offline;

  return (
    <div
      style={{
        position: "absolute",
        right: "16px",
        top: "16px",
        width: "300px",
        background: "rgba(10, 15, 26, 0.95)",
        border: `1px solid ${colors.border}`,
        borderRadius: "12px",
        padding: "16px",
        zIndex: 100,
        fontFamily: "'JetBrains Mono', monospace",
        boxShadow: `0 8px 32px rgba(0,0,0,0.5), 0 0 20px ${colors.glow}`,
        backdropFilter: "blur(8px)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "12px" }}>
        <h3 style={{ color: "#e5e7eb", margin: 0, fontSize: "14px" }}>{node.label}</h3>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#6b7280", cursor: "pointer", fontSize: "16px" }}
        >
          ×
        </button>
      </div>
      <div style={{ color: "#9ca3af", fontSize: "11px" }}>
        <div style={{ marginBottom: "8px" }}>
          <span style={{ color: colors.border }}>●</span> {node.status} — {node.age_s.toFixed(1)}s ago
        </div>
        <pre style={{
          background: "rgba(0,0,0,0.3)",
          padding: "10px",
          borderRadius: "8px",
          overflow: "auto",
          maxHeight: "350px",
          fontSize: "10px",
          color: "#d1d5db",
          lineHeight: "1.5",
        }}>
          {JSON.stringify(node.metrics, null, 2)}
        </pre>
      </div>
    </div>
  );
}

// ── Static fallback ─────────────────────────────────────────────────

function staticTopology(): SystemFlowState {
  const off = (id: string, label: string): FlowNode => ({
    id, label, status: "offline", age_s: 999, metrics: {},
  });
  return {
    nodes: [
      off("perception", "Perception"), off("stimmung", "Stimmung"),
      off("temporal", "Temporal Bands"), off("apperception", "Apperception"),
      off("phenomenal", "Phenomenal Context"), off("voice", "Voice Pipeline"),
      off("compositor", "Compositor"), off("engine", "Reactive Engine"),
      off("consent", "Consent"),
    ],
    edges: [
      { source: "perception", target: "stimmung", active: false, label: "perception confidence" },
      { source: "perception", target: "temporal", active: false, label: "perception ring" },
      { source: "perception", target: "consent", active: false, label: "faces + speaker" },
      { source: "stimmung", target: "apperception", active: false, label: "stance" },
      { source: "temporal", target: "apperception", active: false, label: "surprise" },
      { source: "temporal", target: "phenomenal", active: false, label: "bands" },
      { source: "apperception", target: "phenomenal", active: false, label: "self-band" },
      { source: "stimmung", target: "phenomenal", active: false, label: "attunement" },
      { source: "phenomenal", target: "voice", active: false, label: "orientation" },
      { source: "perception", target: "voice", active: false, label: "salience" },
      { source: "voice", target: "compositor", active: false, label: "voice state" },
      { source: "stimmung", target: "compositor", active: false, label: "visual mood" },
      { source: "perception", target: "compositor", active: false, label: "signals" },
      { source: "engine", target: "compositor", active: false, label: "engine state" },
      { source: "stimmung", target: "engine", active: false, label: "phase gating" },
      { source: "consent", target: "voice", active: false, label: "consent gate" },
    ],
    timestamp: Date.now() / 1000,
  };
}

// ── Main Page ───────────────────────────────────────────────────────

export function FlowPage() {
  const [flowState, setFlowState] = useState<SystemFlowState | null>(null);
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const prevPositions = useRef<Record<string, { x: number; y: number }>>({});

  // Poll every 3s — Tauri IPC → HTTP fallback → static topology
  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const state = await invoke<SystemFlowState>("get_system_flow");
        if (mounted) setFlowState(state);
      } catch {
        try {
          const resp = await fetch("/api/flow/state");
          if (resp.ok) {
            const state = await resp.json();
            if (mounted) setFlowState(state);
          }
        } catch {
          if (mounted && !flowState) setFlowState(staticTopology());
        }
      }
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  // Build React Flow nodes/edges from state
  useEffect(() => {
    if (!flowState) return;

    // Find source node age for each edge (for staleness coloring)
    const nodeAgeMap: Record<string, number> = {};
    for (const n of flowState.nodes) {
      nodeAgeMap[n.id] = n.age_s;
    }

    // Consent gating active?
    const consentPhase = flowState.nodes.find(n => n.id === "consent")?.metrics?.phase as string || "none";
    const consentActive = consentPhase !== "none" && consentPhase !== "consent_granted";

    const rfNodes: Node[] = flowState.nodes.map((n) => ({
      id: n.id,
      type: "system",
      position: prevPositions.current[n.id] || POSITIONS[n.id] || { x: 0, y: 0 },
      data: n,
      draggable: true,
    }));

    const rfEdges: Edge[] = flowState.edges.map((e, i) => ({
      id: `${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      type: "flowing",
      data: {
        active: e.active,
        age_s: nodeAgeMap[e.source] || 999,
        label: e.label,
        gated: consentActive && e.label === "consent gate",
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: edgeColor(nodeAgeMap[e.source] || 999, e.active),
        width: 12,
        height: 12,
      },
    }));

    setNodes(rfNodes);
    setEdges(rfEdges);
  }, [flowState, setNodes, setEdges]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setSelectedNode(node.data as FlowNode);
  }, []);

  // Track manual node drags
  const onNodeDragStop = useCallback((_: unknown, node: Node) => {
    prevPositions.current[node.id] = node.position;
  }, []);

  const activeCount = flowState?.nodes.filter(n => n.status === "active").length ?? 0;
  const totalCount = flowState?.nodes.length ?? 0;

  return (
    <div style={{ width: "100%", height: "100%", background: "#0a0f1a", position: "relative" }}>
      <style>{`
        @keyframes breathe {
          0%, 100% { box-shadow: 0 0 12px var(--glow-color, rgba(16,185,129,0.25)); }
          50% { box-shadow: 0 0 24px var(--glow-color, rgba(16,185,129,0.4)); }
        }
        .react-flow__edge-path { transition: stroke 1s ease, opacity 1s ease; }
        .react-flow__handle { border: none !important; }
        .react-flow__controls { border-radius: 8px; overflow: hidden; }
        .react-flow__controls button { background: #1a1f2e !important; border-color: #2a2f3a !important; color: #6b7280 !important; }
        .react-flow__controls button:hover { background: #2a2f3a !important; color: #9ca3af !important; }
      `}</style>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeDragStop={onNodeDragStop}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={2.5}
      >
        <Background color="#161b2e" gap={32} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>

      <DetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />

      {/* Title bar */}
      <div
        style={{
          position: "absolute",
          top: "12px",
          left: "12px",
          color: "#4b5563",
          fontSize: "11px",
          fontFamily: "'JetBrains Mono', monospace",
          zIndex: 10,
          letterSpacing: "0.08em",
        }}
      >
        SYSTEM ANATOMY — {flowState
          ? <><span style={{ color: activeCount > 0 ? "#10b981" : "#4b5563" }}>{activeCount}</span>/{totalCount} active</>
          : "connecting..."}
      </div>

      {/* System summary bar */}
      {flowState && (() => {
        const stimmungNode = flowState.nodes.find(n => n.id === "stimmung");
        const stance = (stimmungNode?.metrics?.stance as string) || "unknown";
        const staleCount = flowState.nodes.filter(n => n.status === "stale").length;
        const offlineCount = flowState.nodes.filter(n => n.status === "offline").length;
        const activeEdges = flowState.edges.filter(e => e.active).length;
        const totalEdges = flowState.edges.length;
        const stanceColor = stance === "nominal" ? "#10b981" : stance === "cautious" ? "#f59e0b" : stance === "degraded" ? "#f97316" : stance === "critical" ? "#ef4444" : "#6b7280";

        return (
          <div
            style={{
              position: "absolute",
              bottom: "12px",
              left: "50%",
              transform: "translateX(-50%)",
              display: "flex",
              gap: "24px",
              color: "#4b5563",
              fontSize: "10px",
              fontFamily: "'JetBrains Mono', monospace",
              zIndex: 10,
              letterSpacing: "0.05em",
              opacity: 0.7,
            }}
          >
            <span>stance: <span style={{ color: stanceColor }}>{stance}</span></span>
            <span>flows: <span style={{ color: "#6b7280" }}>{activeEdges}/{totalEdges}</span></span>
            {staleCount > 0 && <span>stale: <span style={{ color: "#f59e0b" }}>{staleCount}</span></span>}
            {offlineCount > 0 && <span>offline: <span style={{ color: "#6b7280" }}>{offlineCount}</span></span>}
          </div>
        );
      })()}
    </div>
  );
}
