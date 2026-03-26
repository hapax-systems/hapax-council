import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface OverlayState {
  active: string | null;
}

export interface OverlayActions {
  setActive(name: string | null): void;
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerOverlayCommands(
  registry: CommandRegistry,
  getState: () => OverlayState,
  actions: OverlayActions,
): void {
  registry.register({
    path: "overlay.set",
    description: "Set the active overlay by name",
    args: {
      name: { type: "string", required: true },
    },
    execute(args): CommandResult {
      if (typeof args.name !== "string" || args.name.trim() === "") {
        return { ok: false, error: "Missing required arg: name" };
      }
      actions.setActive(args.name);
      return { ok: true };
    },
  });

  registry.register({
    path: "overlay.clear",
    description: "Clear the active overlay. Returns ok:false when nothing is active.",
    execute(): CommandResult {
      if (getState().active === null) {
        return { ok: false, error: "No active overlay to clear" };
      }
      actions.setActive(null);
      return { ok: true };
    },
  });

  registry.register({
    path: "overlay.toggle",
    description: "Toggle an overlay by name — activate if not active, clear if already active",
    args: {
      name: { type: "string", required: true },
    },
    execute(args): CommandResult {
      if (typeof args.name !== "string" || args.name.trim() === "") {
        return { ok: false, error: "Missing required arg: name" };
      }
      const current = getState().active;
      actions.setActive(current === args.name ? null : args.name);
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("overlay.active", () => getState().active);
}
