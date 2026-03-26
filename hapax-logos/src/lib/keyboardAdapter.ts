import type { CommandRegistry } from "./commandRegistry";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface KeyBinding {
  key: string;
  modifiers?: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean };
  command: string;
  args?: Record<string, unknown>;
  /** Condition: "query.path=value" (equality check) or "query.path" (truthy check) */
  when?: string;
}

// ─── evaluateKeyMap ───────────────────────────────────────────────────────────

/**
 * Find the first matching key binding for the given key + modifier state.
 *
 * Matching rules:
 * 1. Key string must match exactly (case-sensitive).
 * 2. Modifiers: if the binding declares no modifiers, all pressed modifiers must
 *    be false. If the binding declares modifiers, the pressed state must match
 *    each declared modifier exactly; any undeclared modifier must be absent.
 * 3. When-clause: "path=value" — equality check via registry.query().
 *    "path" alone — truthy check.
 *
 * Returns the first matching { command, args } pair, or null.
 */
export function evaluateKeyMap(
  keyMap: KeyBinding[],
  key: string,
  modifiers: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean },
  registry: CommandRegistry,
): { command: string; args?: Record<string, unknown> } | null {
  const pressedCtrl = modifiers.ctrl ?? false;
  const pressedShift = modifiers.shift ?? false;
  const pressedAlt = modifiers.alt ?? false;
  const pressedMeta = modifiers.meta ?? false;

  for (const binding of keyMap) {
    // 1. Key match
    if (binding.key !== key) continue;

    // 2. Modifier match
    if (!binding.modifiers) {
      // No modifiers declared → reject if any modifier is active
      if (pressedCtrl || pressedShift || pressedAlt || pressedMeta) continue;
    } else {
      const bCtrl = binding.modifiers.ctrl ?? false;
      const bShift = binding.modifiers.shift ?? false;
      const bAlt = binding.modifiers.alt ?? false;
      const bMeta = binding.modifiers.meta ?? false;

      if (bCtrl !== pressedCtrl) continue;
      if (bShift !== pressedShift) continue;
      if (bAlt !== pressedAlt) continue;
      if (bMeta !== pressedMeta) continue;
    }

    // 3. When-clause
    if (binding.when !== undefined) {
      const eqIndex = binding.when.indexOf("=");
      if (eqIndex !== -1) {
        const queryPath = binding.when.slice(0, eqIndex);
        const expectedValue = binding.when.slice(eqIndex + 1);
        const actualValue = registry.query(queryPath);
        if (String(actualValue) !== expectedValue) continue;
      } else {
        // Truthy check
        const value = registry.query(binding.when);
        if (!value) continue;
      }
    }

    return { command: binding.command, args: binding.args };
  }

  return null;
}

// ─── LOGOS_KEY_MAP ────────────────────────────────────────────────────────────

/**
 * Default key bindings for the Logos application.
 *
 * Bindings are evaluated in list order — first match wins. Conditional bindings
 * (when-clause) appear before unconditional bindings for the same key so that
 * context-specific behaviour takes precedence.
 */
export const LOGOS_KEY_MAP: KeyBinding[] = [
  // Terrain region navigation
  { key: "h", command: "terrain.focus", args: { region: "horizon" } },
  { key: "f", command: "terrain.focus", args: { region: "field" } },
  { key: "g", command: "terrain.focus", args: { region: "ground" } },
  { key: "w", command: "terrain.focus", args: { region: "watershed" } },
  { key: "b", command: "terrain.focus", args: { region: "bedrock" } },

  // Overlays
  { key: "/", command: "overlay.toggle", args: { name: "investigation" } },

  // Dismiss / escape
  { key: "Escape", command: "escape" },

  // Split panel
  { key: "s", command: "split.toggle" },

  // Detection
  { key: "d", command: "detection.tier.cycle" },
  { key: "D", modifiers: { shift: true }, command: "detection.visibility.toggle" },

  // Studio controls (ground-context only)
  { key: "e", command: "studio.smooth.toggle", when: "terrain.focusedRegion=ground" },
  { key: "r", command: "studio.recording.toggle", when: "terrain.focusedRegion=ground" },
  { key: "[", command: "studio.preset.cycle", args: { direction: "prev" }, when: "terrain.focusedRegion=ground" },
  { key: "]", command: "studio.preset.cycle", args: { direction: "next" }, when: "terrain.focusedRegion=ground" },

  // Navigation / misc (unconditional — lower priority than ground-gated r above)
  { key: "?", command: "nav.manual.toggle" },
  { key: "c", command: "nav.go", args: { path: "/chat" } },
  { key: "i", command: "nav.go", args: { path: "/insight" } },
  { key: "r", command: "data.refresh" },
];
