import type { DemoBridge } from "../useDemoBridge";
import type { RegionName, Depth, Overlay, InvestigationTab } from "../../contexts/TerrainContext";

export interface DemoAction {
  at: number;
  action: (ctx: DemoBridge) => void;
  label?: string;
}

export interface DemoScene {
  title: string;
  audioFile: string;
  actions: DemoAction[];
}

export interface DemoManifest {
  name: string;
  audioDir: string;
  scenes: DemoScene[];
}

// ── JSON-serialized action format (from app-script.json) ─────────────

interface JsonAction {
  at: number;
  calls: (string | null)[][];
  label?: string;
}

interface JsonScene {
  title: string;
  audioFile: string;
  actions: JsonAction[];
}

/**
 * Deserialize a JSON action call into a bridge function invocation.
 * Format: ["methodName", ...args] where methodName is a bridge method.
 */
function deserializeCall(call: (string | null)[], ctx: DemoBridge): void {
  const [method, ...args] = call;
  switch (method) {
    case "focusRegion":
      ctx.terrain.focusRegion(args[0] as RegionName | null);
      break;
    case "setRegionDepth":
      ctx.terrain.setRegionDepth(args[0] as RegionName, args[1] as Depth);
      break;
    case "cycleDepth":
      ctx.terrain.cycleDepth(args[0] as RegionName);
      break;
    case "setOverlay":
      ctx.terrain.setOverlay(args[0] as Overlay);
      break;
    case "setInvestigationTab":
      ctx.terrain.setInvestigationTab(args[0] as InvestigationTab);
      break;
    case "setSplitRegion":
      ctx.terrain.setSplitRegion(args[0] as RegionName | null);
      break;
    case "highlightRegion":
      ctx.terrain.highlightRegion(
        args[0] as RegionName | null,
        args[1] != null ? Number(args[1]) : undefined,
      );
      break;
    case "selectPreset":
      ctx.studio.selectPreset(args[0] as string);
      break;
    default:
      console.warn(`Unknown bridge method: ${method}`);
  }
}

/**
 * Convert JSON scenes (from app-script.json) into DemoScene[] with live functions.
 */
function hydrateJsonScenes(jsonScenes: JsonScene[]): DemoScene[] {
  return jsonScenes.map((js) => ({
    title: js.title,
    audioFile: js.audioFile,
    actions: js.actions.map((ja) => ({
      at: ja.at,
      label: ja.label,
      action: (ctx: DemoBridge) => {
        for (const call of ja.calls) {
          deserializeCall(call, ctx);
        }
      },
    })),
  }));
}

// ── Demo loader ──────────────────────────────────────────────────────

export async function loadDemo(name: string): Promise<DemoManifest> {
  // Try hardcoded scripts first (hand-crafted, TypeScript-native)
  switch (name) {
    case "brother": {
      const { DEMO_SCRIPT } = await import("./brother");
      return { name, audioDir: "/api/demos/brother-demo/files/audio", scenes: DEMO_SCRIPT };
    }
    case "alexis": {
      const { DEMO_SCRIPT } = await import("./alexis");
      return { name, audioDir: "/api/demos/alexis-demo/files/audio", scenes: DEMO_SCRIPT };
    }
    case "alexis-v4": {
      const { DEMO_SCRIPT } = await import("./alexis-v4");
      return { name, audioDir: "/api/demos/alexis-v4-demo/files/audio", scenes: DEMO_SCRIPT };
    }
    case "kids": {
      const { DEMO_SCRIPT } = await import("./kids");
      return { name, audioDir: "/api/demos/kids-demo/files/audio", scenes: DEMO_SCRIPT };
    }
  }

  // Fall back to dynamic JSON loading (LLM-generated demos)
  // Try with -demo suffix first (hand-crafted), then without (pipeline-generated)
  let audioDir = `/api/demos/${name}-demo/files/audio`;
  let scriptUrl = `/api/demos/${name}-demo/files/app-script.json`;

  // Check if the -demo variant exists; if not, try bare name
  const probeResp = await fetch(scriptUrl, { method: "HEAD" });
  if (!probeResp.ok) {
    audioDir = `/api/demos/${name}/files/audio`;
    scriptUrl = `/api/demos/${name}/files/app-script.json`;
  }

  const resp = await fetch(scriptUrl);
  if (!resp.ok) {
    throw new Error(`Demo "${name}" not found (HTTP ${resp.status} from ${scriptUrl})`);
  }

  const jsonScenes: JsonScene[] = await resp.json();
  const scenes = hydrateJsonScenes(jsonScenes);

  return { name, audioDir, scenes };
}
