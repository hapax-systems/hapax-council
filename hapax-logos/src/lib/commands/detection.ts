import type { CommandRegistry, CommandResult } from "../commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export type DetectionTier = 1 | 2 | 3;

export interface DetectionState {
  tier: DetectionTier;
  visible: boolean;
}

export interface DetectionActions {
  setTier(tier: DetectionTier): void;
  setVisible(value: boolean): void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const VALID_TIERS = new Set([1, 2, 3]);

function isTier(v: unknown): v is DetectionTier {
  return typeof v === "number" && VALID_TIERS.has(v);
}

function cycleTier(current: DetectionTier): DetectionTier {
  return (current % 3) + 1 as DetectionTier;
}

// ─── Register ────────────────────────────────────────────────────────────────

export function registerDetectionCommands(
  registry: CommandRegistry,
  getState: () => DetectionState,
  actions: DetectionActions,
): void {
  registry.register({
    path: "detection.tier.set",
    description: "Set the detection tier (1, 2, or 3)",
    args: {
      tier: { type: "number", required: true, enum: ["1", "2", "3"] },
    },
    execute(args): CommandResult {
      if (!isTier(args.tier)) {
        return { ok: false, error: `Invalid tier: ${String(args.tier)}` };
      }
      actions.setTier(args.tier);
      return { ok: true };
    },
  });

  registry.register({
    path: "detection.tier.cycle",
    description: "Cycle detection tier 1→2→3→1",
    execute(): CommandResult {
      actions.setTier(cycleTier(getState().tier));
      return { ok: true };
    },
  });

  registry.register({
    path: "detection.visibility.toggle",
    description: "Toggle detection overlay visibility",
    execute(): CommandResult {
      actions.setVisible(!getState().visible);
      return { ok: true };
    },
  });

  // ── Queries ──────────────────────────────────────────────────────────────

  registry.registerQuery("detection.tier", () => getState().tier);
  registry.registerQuery("detection.visible", () => getState().visible);
}
