/**
 * SystemStatus — compact at-a-glance view of the system's phenomenological state.
 * Polls the flow API every 3s and renders a single card showing:
 * - Stimmung stance (color-coded)
 * - Node status grid (9 dots, colored by health)
 * - Active flow count
 * - Key metrics from perception + apperception
 */

import { useEffect, useState } from "react";

interface FlowNode {
  id: string;
  label: string;
  status: string;
  age_s: number;
  metrics: Record<string, unknown>;
}

interface FlowState {
  nodes: FlowNode[];
  edges: { active: boolean }[];
  timestamp: number;
}

const STATUS_DOT: Record<string, string> = {
  active: "#10b981",
  stale: "#f59e0b",
  offline: "#374151",
};

const STANCE_COLOR: Record<string, string> = {
  nominal: "#10b981",
  cautious: "#f59e0b",
  degraded: "#f97316",
  critical: "#ef4444",
};

export function SystemStatus() {
  const [state, setState] = useState<FlowState | null>(null);

  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const resp = await fetch("/api/flow/state");
        if (resp.ok && mounted) setState(await resp.json());
      } catch { /* offline */ }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  if (!state) return null;

  const stimmung = state.nodes.find(n => n.id === "stimmung");
  const perception = state.nodes.find(n => n.id === "perception");
  const apperception = state.nodes.find(n => n.id === "apperception");
  const voice = state.nodes.find(n => n.id === "voice");

  const stance = (stimmung?.metrics?.stance as string) || "unknown";
  const stanceColor = STANCE_COLOR[stance] || "#6b7280";
  const activeFlows = state.edges.filter(e => e.active).length;
  const totalFlows = state.edges.length;
  const activity = (perception?.metrics?.activity as string) || "idle";
  const flowScore = (perception?.metrics?.flow_score as number) ?? 0;
  const presence = (perception?.metrics?.presence_probability as number) ?? 0;
  const coherence = (apperception?.metrics?.coherence as number) ?? 0;
  const voiceActive = (voice?.metrics?.active as boolean) ?? false;
  const voiceTier = (voice?.metrics?.tier as string) || "";

  return (
    <div
      className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: stanceColor, boxShadow: `0 0 6px ${stanceColor}` }}
          />
          <span className="text-xs text-zinc-300 uppercase tracking-wider">
            {stance}
          </span>
        </div>
        <span className="text-[10px] text-zinc-600">
          {activeFlows}/{totalFlows} flows
        </span>
      </div>

      {/* Node status grid */}
      <div className="flex gap-1.5 mb-3">
        {state.nodes.map(n => (
          <div
            key={n.id}
            title={`${n.label}: ${n.status}`}
            className="flex flex-col items-center gap-0.5"
          >
            <span
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{
                background: STATUS_DOT[n.status] || STATUS_DOT.offline,
                opacity: n.status === "offline" ? 0.4 : 1,
              }}
            />
            <span className="text-[7px] text-zinc-600 leading-none">
              {n.id.slice(0, 4)}
            </span>
          </div>
        ))}
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
        <div className="flex justify-between">
          <span className="text-zinc-600">activity</span>
          <span className="text-zinc-400">{activity}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">flow</span>
          <span className="text-zinc-400">{(flowScore * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">presence</span>
          <span className="text-zinc-400">{(presence * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-600">coherence</span>
          <span className="text-zinc-400">{coherence.toFixed(2)}</span>
        </div>
        {voiceActive && (
          <div className="flex justify-between col-span-2">
            <span className="text-zinc-600">voice</span>
            <span className="text-emerald-400">{voiceTier || "active"}</span>
          </div>
        )}
      </div>
    </div>
  );
}
