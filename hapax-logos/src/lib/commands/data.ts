import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface DataActions {
  invalidate(key?: string): void;
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerDataCommands(
  registry: CommandRegistry,
  actions: DataActions,
): void {
  registry.register({
    path: "data.refresh",
    description: "Invalidate cached data. Pass key to invalidate specific data, or omit to invalidate all.",
    args: {
      key: { type: "string", description: "Data key to invalidate (omit for all)" },
    },
    execute(args): CommandResult {
      const key = typeof args.key === "string" && args.key.trim() !== ""
        ? args.key
        : undefined;
      actions.invalidate(key);
      return { ok: true };
    },
  });
}
