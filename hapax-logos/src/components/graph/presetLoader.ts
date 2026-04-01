/**
 * Load/save presets: convert between EffectGraph JSON and React Flow nodes/edges.
 */
import Dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";
import { api } from "../../api/client";

/** Backend EffectGraph JSON format. */
export interface EffectGraphJson {
  name: string;
  description?: string;
  transition_ms?: number;
  nodes: Record<string, { type: string; params: Record<string, number | string | boolean> }>;
  edges: [string, string][];
  modulations: { node: string; param: string; source: string; scale?: number; offset?: number; smoothing?: number }[];
  layer_palettes?: Record<string, unknown>;
}

/** Convert EffectGraph JSON → React Flow nodes + edges with dagre layout. */
export function effectGraphToFlow(graph: EffectGraphJson): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Build modulation lookup: nodeId.param → binding
  const modMap: Record<string, Record<string, { source: string; scale: number; offset: number; smoothing: number }>> = {};
  for (const m of graph.modulations ?? []) {
    if (!modMap[m.node]) modMap[m.node] = {};
    modMap[m.node][m.param] = {
      source: m.source,
      scale: m.scale ?? 1,
      offset: m.offset ?? 0,
      smoothing: m.smoothing ?? 0.85,
    };
  }

  // Convert nodes
  for (const [id, def] of Object.entries(graph.nodes)) {
    if (def.type === "output") {
      nodes.push({
        id,
        type: "output",
        position: { x: 0, y: 0 },
        data: { label: "Output" },
        style: { width: 320, height: 200 },
      });
    } else {
      nodes.push({
        id,
        type: "shader",
        position: { x: 0, y: 0 },
        data: {
          shaderType: def.type,
          label: def.type,
          params: def.params ?? {},
          modulations: modMap[id] ?? {},
        },
      });
    }
  }

  // Add @live as a source node if referenced in edges
  const hasLive = graph.edges.some(([src]) => src === "@live");
  if (hasLive) {
    nodes.push({
      id: "@live",
      type: "source",
      position: { x: 0, y: 0 },
      data: {
        sourceType: "camera",
        role: "brio-operator",
        label: "Camera",
      },
    });
  }

  // Convert edges
  for (const [src, tgt] of graph.edges) {
    edges.push({
      id: `e-${src}-${tgt}`,
      source: src,
      target: tgt,
      type: "signal",
    });
  }

  // Apply dagre layout (left-to-right)
  return layoutGraph(nodes, edges);
}

/** Convert React Flow nodes + edges → EffectGraph JSON for saving. */
export function flowToEffectGraph(
  name: string,
  nodes: Node[],
  edges: Edge[],
): EffectGraphJson {
  const graphNodes: EffectGraphJson["nodes"] = {};
  const graphEdges: EffectGraphJson["edges"] = [];
  const modulations: EffectGraphJson["modulations"] = [];

  for (const node of nodes) {
    if (node.type === "source") continue; // @live is implicit
    if (node.type === "output") {
      graphNodes[node.id] = { type: "output", params: {} };
    } else if (node.type === "shader") {
      const data = node.data as Record<string, unknown>;
      graphNodes[node.id] = {
        type: (data.shaderType as string) ?? "unknown",
        params: (data.params as Record<string, number | string | boolean>) ?? {},
      };

      // Extract modulation bindings
      const mods = data.modulations as Record<string, { source: string; scale: number; offset: number; smoothing: number }> | undefined;
      if (mods) {
        for (const [param, binding] of Object.entries(mods)) {
          if (binding.source) {
            modulations.push({
              node: node.id,
              param,
              source: binding.source,
              scale: binding.scale,
              offset: binding.offset,
              smoothing: binding.smoothing,
            });
          }
        }
      }
    }
  }

  for (const edge of edges) {
    const src = nodes.find((n) => n.id === edge.source);
    const srcId = src?.type === "source" ? "@live" : edge.source;
    graphEdges.push([srcId, edge.target]);
  }

  return {
    name,
    nodes: graphNodes,
    edges: graphEdges,
    modulations,
  };
}

/** Dagre layout: left-to-right flow. */
function layoutGraph(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 180, marginx: 60, marginy: 60 });

  for (const node of nodes) {
    const w = node.type === "output" ? 320 : 140;
    const h = node.type === "output" ? 200 : node.type === "source" ? 110 : 60;
    g.setNode(node.id, { width: w, height: h });
  }

  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  Dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    const w = node.type === "output" ? 320 : 140;
    const h = node.type === "output" ? 200 : node.type === "source" ? 110 : 60;
    return {
      ...node,
      position: {
        x: (pos?.x ?? 0) - w / 2,
        y: (pos?.y ?? 0) - h / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}

/** Fetch a preset JSON from the backend and convert to React Flow format. */
export async function fetchAndLoadPreset(presetName: string): Promise<{ nodes: Node[]; edges: Edge[] } | null> {
  try {
    const graph = await api.get<EffectGraphJson>(`/studio/presets/${presetName}`);
    console.log("[preset] fetched:", presetName, graph ? Object.keys(graph) : "null");
    if (!graph?.nodes) return null;
    const result = effectGraphToFlow(graph);
    console.log("[preset] converted:", result.nodes.length, "nodes", result.edges.length, "edges");
    return result;
  } catch (e) {
    console.error("[preset] fetch failed:", presetName, e);
    return null;
  }
}

/** Save current graph as a preset on the backend. */
export async function savePreset(
  name: string,
  nodes: Node[],
  edges: Edge[],
): Promise<boolean> {
  const graph = flowToEffectGraph(name, nodes, edges);
  try {
    await api.post("/studio/presets", graph);
    return true;
  } catch {
    return false;
  }
}
