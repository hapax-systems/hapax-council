import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { api } from "../api/client";

interface NodeMetrics {
  [key: string]: unknown;
}

export interface FlowNode {
  id: string;
  label: string;
  status: string;
  age_s: number;
  metrics: NodeMetrics;
  [key: string]: unknown;
}

export interface FlowEdge {
  source: string;
  target: string;
  active: boolean;
  label: string;
}

export interface SystemFlowState {
  nodes: FlowNode[];
  edges: FlowEdge[];
  timestamp: number;
}

function staticTopology(): SystemFlowState {
  const off = (id: string, label: string): FlowNode => ({
    id,
    label,
    status: "offline",
    age_s: 999,
    metrics: {},
  });
  return {
    nodes: [
      off("perception", "Perception"),
      off("stimmung", "Stimmung"),
      off("temporal", "Temporal Bands"),
      off("apperception", "Apperception"),
      off("phenomenal", "Phenomenal Context"),
      off("voice", "Voice Pipeline"),
      off("compositor", "Compositor"),
      off("engine", "Reactive Engine"),
      off("consent", "Consent"),
    ],
    edges: [],
    timestamp: Date.now() / 1000,
  };
}

export function useSystemFlow() {
  const [flowState, setFlowState] = useState<SystemFlowState | null>(null);

  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      try {
        const state = await invoke<SystemFlowState>("get_system_flow");
        if (mounted) setFlowState(state);
      } catch {
        try {
          const state = await api.get<SystemFlowState>("/flow/state");
          if (mounted) setFlowState(state);
        } catch {
          if (mounted && !flowState) setFlowState(staticTopology());
        }
      }
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const activeCount = flowState?.nodes.filter((n) => n.status === "active").length ?? 0;
  const totalCount = flowState?.nodes.length ?? 0;
  const stimmungNode = flowState?.nodes.find((n) => n.id === "stimmung");
  const stance = (stimmungNode?.metrics?.stance as string) || "unknown";
  const activeFlows = flowState?.edges.filter((e) => e.active).length ?? 0;
  const totalFlows = flowState?.edges.length ?? 0;

  return { flowState, activeCount, totalCount, stance, activeFlows, totalFlows };
}
