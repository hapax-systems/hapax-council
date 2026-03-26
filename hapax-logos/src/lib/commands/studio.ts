import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface StudioState {
  smoothMode: boolean;
  activePreset: string;
  recording: boolean;
}

export interface StudioActions {
  setSmoothMode(value: boolean): void;
  setActivePreset(name: string): void;
  cyclePreset(direction: "next" | "prev"): void;
  setRecording(value: boolean): void;
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerStudioCommands(
  registry: CommandRegistry,
  getState: () => StudioState,
  actions: StudioActions,
): void {
  registry.register({
    path: "studio.smooth.enable",
    description: "Enable smooth mode",
    execute(): CommandResult {
      actions.setSmoothMode(true);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.smooth.disable",
    description: "Disable smooth mode",
    execute(): CommandResult {
      actions.setSmoothMode(false);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.smooth.toggle",
    description: "Toggle smooth mode",
    execute(): CommandResult {
      actions.setSmoothMode(!getState().smoothMode);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.preset.activate",
    description: "Activate a studio preset by name",
    args: {
      name: { type: "string", required: true, description: "Preset name" },
    },
    execute(args): CommandResult {
      if (typeof args.name !== "string" || args.name.trim() === "") {
        return { ok: false, error: "Missing required arg: name" };
      }
      actions.setActivePreset(args.name);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.preset.cycle",
    description: "Cycle to next or previous preset",
    args: {
      direction: { type: "string", required: true, enum: ["next", "prev"] },
    },
    execute(args): CommandResult {
      if (args.direction !== "next" && args.direction !== "prev") {
        return { ok: false, error: `Invalid direction: ${String(args.direction)}` };
      }
      actions.cyclePreset(args.direction);
      return { ok: true };
    },
  });

  registry.register({
    path: "studio.recording.toggle",
    description: "Toggle recording on/off",
    execute(): CommandResult {
      actions.setRecording(!getState().recording);
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("studio.smoothMode", () => getState().smoothMode);
  registry.registerQuery("studio.activePreset", () => getState().activePreset);
  registry.registerQuery("studio.recording", () => getState().recording);
}
