/**
 * Merge multiple preset EffectGraphs into a single chained graph.
 *
 * Strategy:
 * - Nodes from each preset get a prefix to avoid ID collisions (p0_, p1_, ...)
 * - Infrastructure nodes (output, content_layer, postprocess) use only the
 *   LAST preset's version
 * - Compounding nodes (colorgrade, bloom, noise_overlay, vignette) are merged:
 *   only one instance kept, params averaged across presets that include them
 * - Effect nodes (the unique character of each preset) are chained in sequence
 * - @live feeds into the first preset's input
 */
import type { EffectGraphJson } from "./presetLoader";

/** Only one instance, last preset wins (no params to merge) */
const INFRA_TYPES = new Set(["output", "content_layer", "postprocess"]);

/** Only one instance kept, params merged (averaged) across presets.
 *  These compound destructively when chained — 3x colorgrade, 3x bloom, etc. */
const DEDUP_TYPES = new Set(["colorgrade", "bloom", "noise_overlay", "vignette"]);

type ParamValue = string | number | boolean;
type ParamRecord = Record<string, ParamValue>;

function averageParams(paramsList: ParamRecord[]): ParamRecord {
  if (paramsList.length === 0) return {};
  if (paramsList.length === 1) return { ...paramsList[0] };
  const result: ParamRecord = {};
  const allKeys = new Set(paramsList.flatMap((p) => Object.keys(p)));
  for (const key of allKeys) {
    const values = paramsList
      .map((p) => p[key])
      .filter((v) => v !== undefined);
    if (values.length === 0) continue;
    if (typeof values[0] === "number") {
      const sum = (values as number[]).reduce((a, b) => a + b, 0);
      result[key] = sum / values.length;
    } else {
      result[key] = values[values.length - 1];
    }
  }
  return result;
}

export function mergePresetGraphs(
  presetName: string,
  graphs: EffectGraphJson[],
  source = "@live",
): EffectGraphJson {
  if (graphs.length === 0) {
    return {
      name: presetName,
      nodes: { out: { type: "output", params: {} } },
      edges: [],
      modulations: [],
    };
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

  // --- Phase 1: Collect dedup node params across all presets ---
  const dedupParams: Map<string, ParamRecord[]> = new Map();
  for (const g of graphs) {
    for (const [_id, def] of Object.entries(g.nodes)) {
      if (DEDUP_TYPES.has(def.type)) {
        if (!dedupParams.has(def.type)) dedupParams.set(def.type, []);
        dedupParams.get(def.type)!.push((def.params ?? {}) as ParamRecord);
      }
    }
  }

  // --- Phase 2: Collect unique effect nodes from each preset ---
  const chainSegments: {
    prefix: string;
    effectNodes: string[];
    firstNode: string;
    lastNode: string;
  }[] = [];

  for (let i = 0; i < graphs.length; i++) {
    const g = graphs[i];
    const prefix = `p${i}_`;
    const effectNodes: string[] = [];

    for (const [id, def] of Object.entries(g.nodes)) {
      if (INFRA_TYPES.has(def.type) || DEDUP_TYPES.has(def.type)) continue;
      const prefixedId = prefix + id;
      merged.nodes[prefixedId] = { ...def };
      effectNodes.push(prefixedId);
    }

    // Find first and last effect nodes from edge order
    const edgeMap = new Map<string, string>();
    for (const [src, tgt] of g.edges) {
      const tgtType = g.nodes[tgt]?.type ?? "";
      if (INFRA_TYPES.has(tgtType) || DEDUP_TYPES.has(tgtType)) continue;
      const srcType = g.nodes[src]?.type ?? "";
      // Skip edges FROM dedup/infra types — we'll wire those separately
      if (src !== "@live" && (INFRA_TYPES.has(srcType) || DEDUP_TYPES.has(srcType)))
        continue;
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
      if (src === "@live") continue;
      if (INFRA_TYPES.has(srcType ?? "") || INFRA_TYPES.has(tgtType ?? "")) continue;
      if (DEDUP_TYPES.has(srcType ?? "") || DEDUP_TYPES.has(tgtType ?? "")) continue;
      merged.edges.push([prefix + src, prefix + tgt]);
    }

    // Add modulations with prefixed node IDs (skip dedup node modulations)
    for (const m of g.modulations ?? []) {
      const nodeType = g.nodes[m.node]?.type ?? "";
      if (INFRA_TYPES.has(nodeType) || DEDUP_TYPES.has(nodeType)) continue;
      merged.modulations.push({ ...m, node: prefix + m.node });
    }

    const first =
      orderedIds.length > 0 ? orderedIds[0] : effectNodes[0];
    const last =
      orderedIds.length > 0
        ? orderedIds[orderedIds.length - 1]
        : effectNodes[effectNodes.length - 1];
    if (first && last) {
      chainSegments.push({ prefix, effectNodes, firstNode: first, lastNode: last });
    }
  }

  // --- Phase 3: Add single merged dedup nodes ---
  // Colorgrade goes at the start (before effect chain), bloom/vignette/noise at the end
  const dedupFront = ["colorgrade"];
  const dedupBack = ["bloom", "noise_overlay", "vignette"];

  for (const type of [...dedupFront, ...dedupBack]) {
    const params = dedupParams.get(type);
    if (!params || params.length === 0) continue;
    merged.nodes[type] = { type, params: averageParams(params) };
  }

  // --- Phase 4: Wire the complete chain ---
  if (chainSegments.length > 0) {
    // source -> [colorgrade] -> first effect chain segment
    let entryPoint = source;
    if (merged.nodes["colorgrade"]) {
      merged.edges.push([entryPoint, "colorgrade"]);
      entryPoint = "colorgrade";
    }
    merged.edges.push([entryPoint, chainSegments[0].firstNode]);

    // Inter-segment wiring
    for (let i = 1; i < chainSegments.length; i++) {
      merged.edges.push([
        chainSegments[i - 1].lastNode,
        chainSegments[i].firstNode,
      ]);
    }

    // Last effect -> [bloom] -> [noise_overlay] -> [vignette] -> content_layer -> postprocess -> out
    let exitPoint = chainSegments[chainSegments.length - 1].lastNode;
    for (const type of dedupBack) {
      if (merged.nodes[type]) {
        merged.edges.push([exitPoint, type]);
        exitPoint = type;
      }
    }

    // Add infra nodes from last preset
    const lastGraph = graphs[graphs.length - 1];
    for (const [id, def] of Object.entries(lastGraph.nodes)) {
      if (INFRA_TYPES.has(def.type)) {
        merged.nodes[id] = { ...def };
      }
    }

    const infraChain = ["content_layer", "postprocess", "out"].filter(
      (id) => merged.nodes[id],
    );
    if (infraChain.length > 0) {
      merged.edges.push([exitPoint, infraChain[0]]);
      for (let i = 1; i < infraChain.length; i++) {
        merged.edges.push([infraChain[i - 1], infraChain[i]]);
      }
    }
  }

  return merged;
}

/** Count total effect slots needed for a merged chain. */
export function countSlots(graphs: EffectGraphJson[]): number {
  // Unique effect nodes (not infra, dedup counted once)
  const dedupSeen = new Set<string>();
  let count = 0;
  for (const g of graphs) {
    for (const def of Object.values(g.nodes)) {
      if (INFRA_TYPES.has(def.type)) continue;
      if (DEDUP_TYPES.has(def.type)) {
        if (dedupSeen.has(def.type)) continue;
        dedupSeen.add(def.type);
      }
      count++;
    }
  }
  // Infra from last preset (content_layer, postprocess)
  if (graphs.length > 0) {
    const last = graphs[graphs.length - 1];
    for (const def of Object.values(last.nodes)) {
      if (INFRA_TYPES.has(def.type) && def.type !== "output") count++;
    }
  }
  return count;
}

export const MAX_SLOTS = 24;
