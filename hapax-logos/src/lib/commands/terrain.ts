import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export type TerrainRegion = "horizon" | "field" | "ground" | "watershed" | "bedrock";
export type TerrainDepth = "surface" | "stratum" | "core";

export type TerrainDepths = Record<TerrainRegion, TerrainDepth>;

export interface TerrainState {
  focusedRegion: TerrainRegion | null;
  depths: TerrainDepths;
}

export interface TerrainActions {
  setFocusedRegion(region: TerrainRegion | null): void;
  setDepth(region: TerrainRegion, depth: TerrainDepth): void;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const VALID_REGIONS = new Set<string>(["horizon", "field", "ground", "watershed", "bedrock"]);
const VALID_DEPTHS = new Set<string>(["surface", "stratum", "core"]);
const DEPTH_CYCLE: TerrainDepth[] = ["surface", "stratum", "core"];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function isRegion(v: unknown): v is TerrainRegion {
  return typeof v === "string" && VALID_REGIONS.has(v);
}

function isDepth(v: unknown): v is TerrainDepth {
  return typeof v === "string" && VALID_DEPTHS.has(v);
}

function cycleDepth(current: TerrainDepth): TerrainDepth {
  const idx = DEPTH_CYCLE.indexOf(current);
  return DEPTH_CYCLE[(idx + 1) % DEPTH_CYCLE.length];
}

function isCollapsed(state: TerrainState): boolean {
  if (state.focusedRegion !== null) return false;
  return Object.values(state.depths).every((d) => d === "surface");
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerTerrainCommands(
  registry: CommandRegistry,
  getState: () => TerrainState,
  actions: TerrainActions,
): void {
  // terrain.focus
  registry.register({
    path: "terrain.focus",
    description: "Focus a terrain region, cycle its depth if already focused, or unfocus if null",
    args: {
      region: { type: "string", description: "Region name or null to unfocus" },
      depth: { type: "string", description: "Optional: set depth directly (surface/stratum/core)" },
    },
    execute(args): CommandResult {
      const region = args.region;

      // null → unfocus
      if (region === null || region === undefined) {
        actions.setFocusedRegion(null);
        return { ok: true };
      }

      if (!isRegion(region)) {
        return { ok: false, error: `Invalid region: ${String(region)}` };
      }

      // explicit depth provided → focus region and set depth directly
      if (args.depth !== undefined && args.depth !== null) {
        if (!isDepth(args.depth)) {
          return { ok: false, error: `Invalid depth: ${String(args.depth)}` };
        }
        actions.setFocusedRegion(region);
        actions.setDepth(region, args.depth);
        return { ok: true };
      }

      const state = getState();

      if (state.focusedRegion === region) {
        // already focused → cycle depth
        const nextDepth = cycleDepth(state.depths[region]);
        actions.setDepth(region, nextDepth);
      } else {
        // focus the new region
        actions.setFocusedRegion(region);
      }

      return { ok: true };
    },
  });

  // terrain.depth.set
  registry.register({
    path: "terrain.depth.set",
    description: "Set a specific depth for a terrain region",
    args: {
      region: { type: "string", required: true },
      depth: { type: "string", required: true },
    },
    execute(args): CommandResult {
      if (!isRegion(args.region)) {
        return { ok: false, error: `Invalid region: ${String(args.region)}` };
      }
      if (!isDepth(args.depth)) {
        return { ok: false, error: `Invalid depth: ${String(args.depth)}` };
      }
      actions.setDepth(args.region, args.depth);
      return { ok: true };
    },
  });

  // terrain.depth.cycle
  registry.register({
    path: "terrain.depth.cycle",
    description: "Cycle surface→stratum→core for a terrain region",
    args: {
      region: { type: "string", required: true },
    },
    execute(args): CommandResult {
      if (!isRegion(args.region)) {
        return { ok: false, error: `Invalid region: ${String(args.region)}` };
      }
      const state = getState();
      const nextDepth = cycleDepth(state.depths[args.region]);
      actions.setDepth(args.region, nextDepth);
      return { ok: true };
    },
  });

  // terrain.collapse
  registry.register({
    path: "terrain.collapse",
    description: "Reset all regions to surface depth and unfocus. Returns ok:false when already collapsed.",
    execute(): CommandResult {
      const state = getState();

      if (isCollapsed(state)) {
        return { ok: false, error: "Already collapsed" };
      }

      actions.setFocusedRegion(null);
      const allRegions: TerrainRegion[] = ["horizon", "field", "ground", "watershed", "bedrock"];
      for (const region of allRegions) {
        actions.setDepth(region, "surface");
      }
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("terrain.focusedRegion", () => getState().focusedRegion);
  registry.registerQuery("terrain.depths", () => getState().depths);
  registry.registerQuery("terrain.coreMiddle", () => getState().depths.ground === "core");
}
