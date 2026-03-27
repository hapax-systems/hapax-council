import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface SplitState {
  region: string | null;
  fullscreen: boolean;
}

export interface SplitActions {
  setRegion(region: string | null): void;
  setFullscreen(value: boolean): void;
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerSplitCommands(
  registry: CommandRegistry,
  getState: () => SplitState,
  actions: SplitActions,
): void {
  registry.register({
    path: "split.open",
    description: "Open the split panel for a region",
    args: {
      region: { type: "string", required: true },
    },
    execute(args): CommandResult {
      if (typeof args.region !== "string" || args.region.trim() === "") {
        return { ok: false, error: "Missing required arg: region" };
      }
      actions.setRegion(args.region);
      return { ok: true };
    },
  });

  registry.register({
    path: "split.close",
    description: "Close the split panel. Returns ok:false when nothing is open.",
    execute(): CommandResult {
      if (getState().region === null) {
        return { ok: false, error: "No split panel is open" };
      }
      actions.setRegion(null);
      return { ok: true };
    },
  });

  registry.register({
    path: "split.toggle",
    description: "Toggle split panel for a region (uses current region if omitted)",
    args: {
      region: { type: "string", description: "Region to toggle. Uses current if omitted." },
    },
    execute(args): CommandResult {
      const state = getState();
      const requestedRegion = typeof args.region === "string" && args.region.trim() !== ""
        ? args.region
        : null;

      if (requestedRegion !== null) {
        // explicit region provided
        if (state.region === requestedRegion) {
          actions.setRegion(null);
        } else {
          actions.setRegion(requestedRegion);
        }
        return { ok: true };
      }

      // no region provided — toggle off if open, else infer from context
      if (state.region !== null) {
        actions.setRegion(null);
        return { ok: true };
      }

      // Infer region: ground when in studio/cam view, else focused region
      const focused = registry.query("terrain.focusedRegion") as string | null;
      const defaultRegion = focused === "ground" ? "ground" : (focused ?? "ground");
      actions.setRegion(defaultRegion);
      return { ok: true };
    },
  });

  registry.register({
    path: "split.fullscreen.toggle",
    description: "Toggle split panel fullscreen mode",
    execute(): CommandResult {
      actions.setFullscreen(!getState().fullscreen);
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("split.region", () => getState().region);
  registry.registerQuery("split.fullscreen", () => getState().fullscreen);
}
