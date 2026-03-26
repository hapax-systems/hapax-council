import { describe, it, expect } from "vitest";
import { CommandRegistry } from "../commandRegistry";
import { evaluateKeyMap, LOGOS_KEY_MAP } from "../keyboardAdapter";
import type { KeyBinding } from "../keyboardAdapter";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeRegistry(queries?: Record<string, () => unknown>): CommandRegistry {
  const registry = new CommandRegistry();
  if (queries) {
    for (const [path, fn] of Object.entries(queries)) {
      registry.registerQuery(path, fn);
    }
  }
  return registry;
}

const NO_MODS = {};
const SHIFT = { shift: true };
const CTRL = { ctrl: true };
const CTRL_SHIFT = { ctrl: true, shift: true };

// ─── Basic key matching ───────────────────────────────────────────────────────

describe("evaluateKeyMap — basic key matching", () => {
  const keyMap: KeyBinding[] = [
    { key: "g", command: "terrain.focus", args: { region: "ground" } },
    { key: "h", command: "terrain.focus", args: { region: "horizon" } },
  ];

  it("returns matching binding for simple key", () => {
    const result = evaluateKeyMap(keyMap, "g", NO_MODS, makeRegistry());
    expect(result).not.toBeNull();
    expect(result!.command).toBe("terrain.focus");
    expect(result!.args).toEqual({ region: "ground" });
  });

  it("returns null for unmapped key", () => {
    const result = evaluateKeyMap(keyMap, "z", NO_MODS, makeRegistry());
    expect(result).toBeNull();
  });

  it("is case-sensitive (G ≠ g)", () => {
    const result = evaluateKeyMap(keyMap, "G", NO_MODS, makeRegistry());
    expect(result).toBeNull();
  });

  it("returns first match in list order", () => {
    const map: KeyBinding[] = [
      { key: "x", command: "first.cmd" },
      { key: "x", command: "second.cmd" },
    ];
    const result = evaluateKeyMap(map, "x", NO_MODS, makeRegistry());
    expect(result!.command).toBe("first.cmd");
  });
});

// ─── Modifier matching ────────────────────────────────────────────────────────

describe("evaluateKeyMap — modifier matching", () => {
  it("matches binding with no modifiers when no modifier is pressed", () => {
    const map: KeyBinding[] = [{ key: "d", command: "detection.tier.cycle" }];
    const result = evaluateKeyMap(map, "d", NO_MODS, makeRegistry());
    expect(result).not.toBeNull();
  });

  it("rejects binding with no modifiers when shift is pressed", () => {
    const map: KeyBinding[] = [{ key: "d", command: "detection.tier.cycle" }];
    const result = evaluateKeyMap(map, "d", SHIFT, makeRegistry());
    expect(result).toBeNull();
  });

  it("rejects binding with no modifiers when ctrl is pressed", () => {
    const map: KeyBinding[] = [{ key: "d", command: "detection.tier.cycle" }];
    const result = evaluateKeyMap(map, "d", CTRL, makeRegistry());
    expect(result).toBeNull();
  });

  it("matches binding requiring shift when shift is pressed", () => {
    const map: KeyBinding[] = [
      { key: "D", modifiers: { shift: true }, command: "detection.visibility.toggle" },
    ];
    const result = evaluateKeyMap(map, "D", SHIFT, makeRegistry());
    expect(result).not.toBeNull();
    expect(result!.command).toBe("detection.visibility.toggle");
  });

  it("rejects shift binding when no modifier pressed", () => {
    const map: KeyBinding[] = [
      { key: "D", modifiers: { shift: true }, command: "detection.visibility.toggle" },
    ];
    const result = evaluateKeyMap(map, "D", NO_MODS, makeRegistry());
    expect(result).toBeNull();
  });

  it("rejects shift binding when ctrl is pressed instead", () => {
    const map: KeyBinding[] = [
      { key: "D", modifiers: { shift: true }, command: "detection.visibility.toggle" },
    ];
    const result = evaluateKeyMap(map, "D", CTRL, makeRegistry());
    expect(result).toBeNull();
  });

  it("matches binding requiring ctrl+shift when both are pressed", () => {
    const map: KeyBinding[] = [
      { key: "k", modifiers: { ctrl: true, shift: true }, command: "some.command" },
    ];
    const result = evaluateKeyMap(map, "k", CTRL_SHIFT, makeRegistry());
    expect(result).not.toBeNull();
  });

  it("rejects ctrl+shift binding when only ctrl is pressed", () => {
    const map: KeyBinding[] = [
      { key: "k", modifiers: { ctrl: true, shift: true }, command: "some.command" },
    ];
    const result = evaluateKeyMap(map, "k", CTRL, makeRegistry());
    expect(result).toBeNull();
  });
});

// ─── When-clause evaluation ───────────────────────────────────────────────────

describe("evaluateKeyMap — when-clause evaluation", () => {
  it("matches when query equals expected value", () => {
    const registry = makeRegistry({ "terrain.focusedRegion": () => "ground" });
    const map: KeyBinding[] = [
      { key: "e", command: "studio.smooth.toggle", when: "terrain.focusedRegion=ground" },
    ];
    const result = evaluateKeyMap(map, "e", NO_MODS, registry);
    expect(result).not.toBeNull();
    expect(result!.command).toBe("studio.smooth.toggle");
  });

  it("does not match when query value differs", () => {
    const registry = makeRegistry({ "terrain.focusedRegion": () => "horizon" });
    const map: KeyBinding[] = [
      { key: "e", command: "studio.smooth.toggle", when: "terrain.focusedRegion=ground" },
    ];
    const result = evaluateKeyMap(map, "e", NO_MODS, registry);
    expect(result).toBeNull();
  });

  it("matches when truthy check passes (no = value)", () => {
    const registry = makeRegistry({ "split.isOpen": () => true });
    const map: KeyBinding[] = [
      { key: "q", command: "split.close", when: "split.isOpen" },
    ];
    const result = evaluateKeyMap(map, "q", NO_MODS, registry);
    expect(result).not.toBeNull();
  });

  it("does not match when truthy check fails (value is falsy)", () => {
    const registry = makeRegistry({ "split.isOpen": () => false });
    const map: KeyBinding[] = [
      { key: "q", command: "split.close", when: "split.isOpen" },
    ];
    const result = evaluateKeyMap(map, "q", NO_MODS, registry);
    expect(result).toBeNull();
  });

  it("does not match when query path is not registered (undefined is falsy)", () => {
    const registry = makeRegistry();
    const map: KeyBinding[] = [
      { key: "e", command: "studio.smooth.toggle", when: "terrain.focusedRegion=ground" },
    ];
    const result = evaluateKeyMap(map, "e", NO_MODS, registry);
    expect(result).toBeNull();
  });
});

// ─── 'r' fallthrough: recording vs data.refresh ──────────────────────────────

describe("evaluateKeyMap — 'r' key when-clause fallthrough", () => {
  it("routes r → studio.recording.toggle when ground is focused", () => {
    const registry = makeRegistry({ "terrain.focusedRegion": () => "ground" });
    const result = evaluateKeyMap(LOGOS_KEY_MAP, "r", NO_MODS, registry);
    expect(result).not.toBeNull();
    expect(result!.command).toBe("studio.recording.toggle");
  });

  it("routes r → data.refresh when a non-ground region is focused", () => {
    const registry = makeRegistry({ "terrain.focusedRegion": () => "horizon" });
    const result = evaluateKeyMap(LOGOS_KEY_MAP, "r", NO_MODS, registry);
    expect(result).not.toBeNull();
    expect(result!.command).toBe("data.refresh");
  });

  it("routes r → data.refresh when no region is focused", () => {
    const registry = makeRegistry();
    const result = evaluateKeyMap(LOGOS_KEY_MAP, "r", NO_MODS, registry);
    expect(result).not.toBeNull();
    expect(result!.command).toBe("data.refresh");
  });
});

// ─── Escape special key ───────────────────────────────────────────────────────

describe("evaluateKeyMap — Escape key", () => {
  it("Escape maps to the escape sequence command", () => {
    const registry = makeRegistry();
    const result = evaluateKeyMap(LOGOS_KEY_MAP, "Escape", NO_MODS, registry);
    expect(result).not.toBeNull();
    expect(result!.command).toBe("escape");
  });
});

// ─── LOGOS_KEY_MAP sanity checks ─────────────────────────────────────────────

describe("LOGOS_KEY_MAP — shape checks", () => {
  it("exports a non-empty array", () => {
    expect(Array.isArray(LOGOS_KEY_MAP)).toBe(true);
    expect(LOGOS_KEY_MAP.length).toBeGreaterThan(0);
  });

  it("every binding has key and command fields", () => {
    for (const b of LOGOS_KEY_MAP) {
      expect(typeof b.key).toBe("string");
      expect(typeof b.command).toBe("string");
    }
  });

  it("contains region navigation keys h/f/g/w/b", () => {
    const commands = LOGOS_KEY_MAP
      .filter((b) => ["h", "f", "g", "w", "b"].includes(b.key))
      .map((b) => b.command);
    expect(commands.every((c) => c === "terrain.focus")).toBe(true);
  });
});
