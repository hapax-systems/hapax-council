import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface NavState {
  currentPath: string;
  manualOpen: boolean;
  paletteOpen: boolean;
}

export interface NavActions {
  setCurrentPath(path: string): void;
  setManualOpen(value: boolean): void;
  setPaletteOpen(value: boolean): void;
  /** Open the investigation overlay with a specific tab. */
  openInvestigationTab?(tab: string): void;
}

/** Paths that map to investigation overlay tabs rather than router navigation. */
const INVESTIGATION_TAB_PATHS: Record<string, string> = {
  "/chat": "chat",
  "/insight": "insight",
  "/demos": "demos",
};

// ─── Register ────────────────────────────────────────────────────────────────

export function registerNavCommands(
  registry: CommandRegistry,
  getState: () => NavState,
  actions: NavActions,
): void {
  registry.register({
    path: "nav.go",
    description: "Navigate to a path (or open investigation tab for /chat, /insight)",
    args: {
      path: { type: "string", required: true },
    },
    execute(args): CommandResult {
      if (typeof args.path !== "string" || args.path.trim() === "") {
        return { ok: false, error: "Missing required arg: path" };
      }
      const tab = INVESTIGATION_TAB_PATHS[args.path];
      if (tab && actions.openInvestigationTab) {
        actions.openInvestigationTab(tab);
      } else {
        actions.setCurrentPath(args.path);
      }
      return { ok: true };
    },
  });

  registry.register({
    path: "nav.manual.toggle",
    description: "Toggle manual panel open/closed",
    execute(): CommandResult {
      actions.setManualOpen(!getState().manualOpen);
      return { ok: true };
    },
  });

  registry.register({
    path: "nav.palette.toggle",
    description: "Toggle command palette open/closed",
    execute(): CommandResult {
      actions.setPaletteOpen(!getState().paletteOpen);
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("nav.currentPath", () => getState().currentPath);
}
