/**
 * Merge multiple preset EffectGraphs into a single chained graph.
 *
 * Strategy:
 * - Nodes from each preset get a prefix to avoid ID collisions (p0_, p1_, ...)
 * - Shared infrastructure nodes (content_layer, postprocess, output) use only
 *   the LAST preset's version (dedup by type)
 * - Edges wire each preset's last effect node into the next preset's first
 * - @live feeds into the first preset's input
 */
import type { EffectGraphJson } from "./presetLoader";

const INFRA_TYPES = new Set(["output", "content_layer", "postprocess"]);

export function mergePresetGraphs(
  presetName: string,
  graphs: EffectGraphJson[],
  source = "@live",
): EffectGraphJson {
  if (graphs.length === 0) {
    return { name: presetName, nodes: { out: { type: "output", params: {} } }, edges: [], modulations: [] };
  }
  if (graphs.length === 1) {
    return { ...graphs[0], name: presetName };
  }

  const merged: EffectGraphJson = {
    name: presetName,
    nodes: {},
    edges: [],
    modulations: [],
  };

  // Collect effect nodes (non-infra) from each preset, prefixed
  const chainSegments: { prefix: string; effectNodes: string[]; firstNode: string; lastNode: string }[] = [];

  for (let i = 0; i < graphs.length; i++) {
    const g = graphs[i];
    const prefix = `p${i}_`;
    const effectNodes: string[] = [];

    // Add prefixed non-infra nodes
    for (const [id, def] of Object.entries(g.nodes)) {
      if (INFRA_TYPES.has(def.type)) continue;
      const prefixedId = prefix + id;
      merged.nodes[prefixedId] = { ...def };
      effectNodes.push(prefixedId);
    }

    // Find first and last effect nodes from edge order
    const edgeMap = new Map<string, string>();
    for (const [src, tgt] of g.edges) {
      const tgtType = g.nodes[tgt]?.type ?? "";
      if (INFRA_TYPES.has(tgtType)) continue;
      const srcKey = src === "@live" ? source : prefix + src;
      edgeMap.set(srcKey, prefix + tgt);
    }

    // Topological walk from source
    const orderedIds: string[] = [];
    let cursor = source;
    while (edgeMap.has(cursor)) {
      const next = edgeMap.get(cursor)!;
      if (effectNodes.includes(next)) orderedIds.push(next);
      cursor = next;
    }

    // Add intra-preset edges (between effect nodes only)
    for (const [src, tgt] of g.edges) {
      const srcType = g.nodes[src]?.type;
      const tgtType = g.nodes[tgt]?.type;
      if (src === "@live") continue; // always skip @live literal in intra-preset edges
      if (INFRA_TYPES.has(srcType ?? "") || INFRA_TYPES.has(tgtType ?? "")) continue;
      merged.edges.push([prefix + src, prefix + tgt]);
    }

    // Add modulations with prefixed node IDs
    for (const m of g.modulations ?? []) {
      if (INFRA_TYPES.has(g.nodes[m.node]?.type ?? "")) continue;
      merged.modulations.push({ ...m, node: prefix + m.node });
    }

    const first = orderedIds.length > 0 ? orderedIds[0] : effectNodes[0];
    const last = orderedIds.length > 0 ? orderedIds[orderedIds.length - 1] : effectNodes[effectNodes.length - 1];
    if (first && last) {
      chainSegments.push({ prefix, effectNodes, firstNode: first, lastNode: last });
    }
  }

  // Wire chain: source -> first preset -> second preset -> ... -> infra -> output
  if (chainSegments.length > 0) {
    merged.edges.push([source, chainSegments[0].firstNode]);

    for (let i = 1; i < chainSegments.length; i++) {
      merged.edges.push([chainSegments[i - 1].lastNode, chainSegments[i].firstNode]);
    }

    const lastSegment = chainSegments[chainSegments.length - 1];
    const lastGraph = graphs[graphs.length - 1];

    // Add infra nodes from last preset (no prefix)
    for (const [id, def] of Object.entries(lastGraph.nodes)) {
      if (INFRA_TYPES.has(def.type)) {
        merged.nodes[id] = { ...def };
      }
    }

    // Wire last effect -> content_layer -> postprocess -> output
    const infraChain = ["content_layer", "postprocess", "out"]
      .filter((id) => merged.nodes[id]);

    if (infraChain.length > 0) {
      merged.edges.push([lastSegment.lastNode, infraChain[0]]);
      for (let i = 1; i < infraChain.length; i++) {
        merged.edges.push([infraChain[i - 1], infraChain[i]]);
      }
    }
  }

  return merged;
}

/** Count total effect slots needed for a merged chain. */
export function countSlots(graphs: EffectGraphJson[]): number {
  let count = 0;
  for (const g of graphs) {
    for (const def of Object.values(g.nodes)) {
      if (!INFRA_TYPES.has(def.type)) count++;
    }
  }
  // Infra nodes from last preset (content_layer, postprocess count as slots too)
  if (graphs.length > 0) {
    const last = graphs[graphs.length - 1];
    for (const def of Object.values(last.nodes)) {
      if (INFRA_TYPES.has(def.type) && def.type !== "output") count++;
    }
  }
  return count;
}

export const MAX_SLOTS = 16;
