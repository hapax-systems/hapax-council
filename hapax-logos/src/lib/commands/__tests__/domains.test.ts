import { describe, it, expect, beforeEach } from "vitest";
import { CommandRegistry } from "../../commandRegistry";

import { registerStudioCommands, type StudioState, type StudioActions } from "../studio";
import { registerOverlayCommands, type OverlayState, type OverlayActions } from "../overlay";
import { registerDetectionCommands, type DetectionState, type DetectionActions } from "../detection";
import { registerNavCommands, type NavState, type NavActions } from "../nav";
import { registerSplitCommands, type SplitState, type SplitActions } from "../split";
import { registerDataCommands, type DataActions } from "../data";

// ─── Studio ──────────────────────────────────────────────────────────────────

describe("studio domain commands", () => {
  let registry: CommandRegistry;
  let state: StudioState;
  let actions: StudioActions;

  beforeEach(() => {
    registry = new CommandRegistry();
    state = { smoothMode: false, activePreset: "clean", recording: false };
    actions = {
      setSmoothMode: (v) => { state.smoothMode = v; },
      setActivePreset: (name) => { state.activePreset = name; },
      cyclePreset: (dir) => {
        // simple stub: track last call
        state.activePreset = dir === "next" ? "next-preset" : "prev-preset";
      },
      setRecording: (v) => { state.recording = v; },
    };
    registerStudioCommands(registry, () => state, actions);
  });

  it("studio.smooth.enable sets smoothMode true", async () => {
    const result = await registry.execute("studio.smooth.enable");
    expect(result.ok).toBe(true);
    expect(state.smoothMode).toBe(true);
  });

  it("studio.smooth.disable sets smoothMode false", async () => {
    state.smoothMode = true;
    const result = await registry.execute("studio.smooth.disable");
    expect(result.ok).toBe(true);
    expect(state.smoothMode).toBe(false);
  });

  it("studio.smooth.toggle flips smoothMode", async () => {
    state.smoothMode = false;
    await registry.execute("studio.smooth.toggle");
    expect(state.smoothMode).toBe(true);
    await registry.execute("studio.smooth.toggle");
    expect(state.smoothMode).toBe(false);
  });

  it("studio.preset.activate sets preset by name", async () => {
    const result = await registry.execute("studio.preset.activate", { name: "datamosh" });
    expect(result.ok).toBe(true);
    expect(state.activePreset).toBe("datamosh");
  });

  it("studio.preset.activate rejects missing name", async () => {
    const result = await registry.execute("studio.preset.activate", {});
    expect(result.ok).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("studio.preset.cycle next works", async () => {
    const result = await registry.execute("studio.preset.cycle", { direction: "next" });
    expect(result.ok).toBe(true);
    expect(state.activePreset).toBe("next-preset");
  });

  it("studio.preset.cycle prev works", async () => {
    const result = await registry.execute("studio.preset.cycle", { direction: "prev" });
    expect(result.ok).toBe(true);
    expect(state.activePreset).toBe("prev-preset");
  });

  it("studio.preset.cycle rejects invalid direction", async () => {
    const result = await registry.execute("studio.preset.cycle", { direction: "sideways" });
    expect(result.ok).toBe(false);
  });

  it("studio.recording.toggle flips recording", async () => {
    state.recording = false;
    await registry.execute("studio.recording.toggle");
    expect(state.recording).toBe(true);
    await registry.execute("studio.recording.toggle");
    expect(state.recording).toBe(false);
  });

  it("studio.smoothMode query returns current value", () => {
    state.smoothMode = true;
    expect(registry.query("studio.smoothMode")).toBe(true);
  });

  it("studio.activePreset query returns current preset", () => {
    state.activePreset = "vhs";
    expect(registry.query("studio.activePreset")).toBe("vhs");
  });

  it("studio.recording query returns current recording state", () => {
    state.recording = true;
    expect(registry.query("studio.recording")).toBe(true);
  });
});

// ─── Overlay ─────────────────────────────────────────────────────────────────

describe("overlay domain commands", () => {
  let registry: CommandRegistry;
  let state: OverlayState;
  let actions: OverlayActions;

  beforeEach(() => {
    registry = new CommandRegistry();
    state = { active: null };
    actions = {
      setActive: (name) => { state.active = name; },
    };
    registerOverlayCommands(registry, () => state, actions);
  });

  it("overlay.set sets active overlay", async () => {
    const result = await registry.execute("overlay.set", { name: "grid" });
    expect(result.ok).toBe(true);
    expect(state.active).toBe("grid");
  });

  it("overlay.clear clears active overlay", async () => {
    state.active = "grid";
    const result = await registry.execute("overlay.clear");
    expect(result.ok).toBe(true);
    expect(state.active).toBeNull();
  });

  it("overlay.clear returns ok:false when nothing active", async () => {
    state.active = null;
    const result = await registry.execute("overlay.clear");
    expect(result.ok).toBe(false);
  });

  it("overlay.toggle sets overlay when none active", async () => {
    const result = await registry.execute("overlay.toggle", { name: "crosshair" });
    expect(result.ok).toBe(true);
    expect(state.active).toBe("crosshair");
  });

  it("overlay.toggle clears when same overlay is active", async () => {
    state.active = "crosshair";
    const result = await registry.execute("overlay.toggle", { name: "crosshair" });
    expect(result.ok).toBe(true);
    expect(state.active).toBeNull();
  });

  it("overlay.toggle switches to new overlay when different one active", async () => {
    state.active = "grid";
    const result = await registry.execute("overlay.toggle", { name: "crosshair" });
    expect(result.ok).toBe(true);
    expect(state.active).toBe("crosshair");
  });

  it("overlay.active query returns current overlay", () => {
    state.active = "grid";
    expect(registry.query("overlay.active")).toBe("grid");
  });

  it("overlay.active query returns null when none active", () => {
    expect(registry.query("overlay.active")).toBeNull();
  });
});

// ─── Detection ───────────────────────────────────────────────────────────────

describe("detection domain commands", () => {
  let registry: CommandRegistry;
  let state: DetectionState;
  let actions: DetectionActions;

  beforeEach(() => {
    registry = new CommandRegistry();
    state = { tier: 1, visible: true };
    actions = {
      setTier: (tier) => { state.tier = tier; },
      setVisible: (v) => { state.visible = v; },
    };
    registerDetectionCommands(registry, () => state, actions);
  });

  it("detection.tier.set sets tier 1", async () => {
    state.tier = 3;
    const result = await registry.execute("detection.tier.set", { tier: 1 });
    expect(result.ok).toBe(true);
    expect(state.tier).toBe(1);
  });

  it("detection.tier.set sets tier 2", async () => {
    const result = await registry.execute("detection.tier.set", { tier: 2 });
    expect(result.ok).toBe(true);
    expect(state.tier).toBe(2);
  });

  it("detection.tier.set sets tier 3", async () => {
    const result = await registry.execute("detection.tier.set", { tier: 3 });
    expect(result.ok).toBe(true);
    expect(state.tier).toBe(3);
  });

  it("detection.tier.set rejects invalid tier", async () => {
    const result = await registry.execute("detection.tier.set", { tier: 4 });
    expect(result.ok).toBe(false);
  });

  it("detection.tier.set rejects missing tier", async () => {
    const result = await registry.execute("detection.tier.set", {});
    expect(result.ok).toBe(false);
  });

  it("detection.tier.cycle cycles 1→2→3→1", async () => {
    state.tier = 1;
    await registry.execute("detection.tier.cycle");
    expect(state.tier).toBe(2);

    await registry.execute("detection.tier.cycle");
    expect(state.tier).toBe(3);

    await registry.execute("detection.tier.cycle");
    expect(state.tier).toBe(1);
  });

  it("detection.visibility.toggle flips visible", async () => {
    state.visible = true;
    await registry.execute("detection.visibility.toggle");
    expect(state.visible).toBe(false);
    await registry.execute("detection.visibility.toggle");
    expect(state.visible).toBe(true);
  });

  it("detection.tier query returns current tier", () => {
    state.tier = 2;
    expect(registry.query("detection.tier")).toBe(2);
  });

  it("detection.visible query returns current visibility", () => {
    state.visible = false;
    expect(registry.query("detection.visible")).toBe(false);
  });
});

// ─── Nav ─────────────────────────────────────────────────────────────────────

describe("nav domain commands", () => {
  let registry: CommandRegistry;
  let state: NavState;
  let actions: NavActions;

  beforeEach(() => {
    registry = new CommandRegistry();
    state = { currentPath: "/", manualOpen: false, paletteOpen: false };
    actions = {
      setCurrentPath: (path) => { state.currentPath = path; },
      setManualOpen: (v) => { state.manualOpen = v; },
      setPaletteOpen: (v) => { state.paletteOpen = v; },
    };
    registerNavCommands(registry, () => state, actions);
  });

  it("nav.go sets current path", async () => {
    const result = await registry.execute("nav.go", { path: "/terrain" });
    expect(result.ok).toBe(true);
    expect(state.currentPath).toBe("/terrain");
  });

  it("nav.go rejects missing path", async () => {
    const result = await registry.execute("nav.go", {});
    expect(result.ok).toBe(false);
  });

  it("nav.manual.toggle flips manualOpen", async () => {
    state.manualOpen = false;
    await registry.execute("nav.manual.toggle");
    expect(state.manualOpen).toBe(true);
    await registry.execute("nav.manual.toggle");
    expect(state.manualOpen).toBe(false);
  });

  it("nav.palette.toggle flips paletteOpen", async () => {
    state.paletteOpen = false;
    await registry.execute("nav.palette.toggle");
    expect(state.paletteOpen).toBe(true);
    await registry.execute("nav.palette.toggle");
    expect(state.paletteOpen).toBe(false);
  });

  it("nav.currentPath query returns current path", () => {
    state.currentPath = "/studio";
    expect(registry.query("nav.currentPath")).toBe("/studio");
  });
});

// ─── Split ───────────────────────────────────────────────────────────────────

describe("split domain commands", () => {
  let registry: CommandRegistry;
  let state: SplitState;
  let actions: SplitActions;

  beforeEach(() => {
    registry = new CommandRegistry();
    state = { region: null, fullscreen: false };
    actions = {
      setRegion: (region) => { state.region = region; },
      setFullscreen: (v) => { state.fullscreen = v; },
    };
    registerSplitCommands(registry, () => state, actions);
  });

  it("split.open opens a region", async () => {
    const result = await registry.execute("split.open", { region: "ground" });
    expect(result.ok).toBe(true);
    expect(state.region).toBe("ground");
  });

  it("split.open rejects missing region", async () => {
    const result = await registry.execute("split.open", {});
    expect(result.ok).toBe(false);
  });

  it("split.close closes the open region", async () => {
    state.region = "ground";
    const result = await registry.execute("split.close");
    expect(result.ok).toBe(true);
    expect(state.region).toBeNull();
  });

  it("split.close returns ok:false when nothing open", async () => {
    state.region = null;
    const result = await registry.execute("split.close");
    expect(result.ok).toBe(false);
  });

  it("split.toggle opens region when none active", async () => {
    const result = await registry.execute("split.toggle", { region: "field" });
    expect(result.ok).toBe(true);
    expect(state.region).toBe("field");
  });

  it("split.toggle closes when same region active", async () => {
    state.region = "field";
    const result = await registry.execute("split.toggle", { region: "field" });
    expect(result.ok).toBe(true);
    expect(state.region).toBeNull();
  });

  it("split.toggle uses focused region when none provided", async () => {
    // No focused region info in split state — uses provided region or null
    // When region omitted and no current region, returns ok:false
    const result = await registry.execute("split.toggle", {});
    expect(result.ok).toBe(false);
  });

  it("split.toggle closes current split when region omitted and split is open", async () => {
    state.region = "ground";
    const result = await registry.execute("split.toggle", {});
    expect(result.ok).toBe(true);
    expect(state.region).toBeNull();
  });

  it("split.fullscreen.toggle flips fullscreen", async () => {
    state.fullscreen = false;
    await registry.execute("split.fullscreen.toggle");
    expect(state.fullscreen).toBe(true);
    await registry.execute("split.fullscreen.toggle");
    expect(state.fullscreen).toBe(false);
  });

  it("split.region query returns current region", () => {
    state.region = "horizon";
    expect(registry.query("split.region")).toBe("horizon");
  });

  it("split.fullscreen query returns current fullscreen state", () => {
    state.fullscreen = true;
    expect(registry.query("split.fullscreen")).toBe(true);
  });
});

// ─── Data ────────────────────────────────────────────────────────────────────

describe("data domain commands", () => {
  let registry: CommandRegistry;
  let actions: DataActions;
  let invalidated: (string | null)[];

  beforeEach(() => {
    registry = new CommandRegistry();
    invalidated = [];
    actions = {
      invalidate: (key) => { invalidated.push(key ?? null); },
    };
    registerDataCommands(registry, actions);
  });

  it("data.refresh with key invalidates that key", async () => {
    const result = await registry.execute("data.refresh", { key: "terrain" });
    expect(result.ok).toBe(true);
    expect(invalidated).toContain("terrain");
  });

  it("data.refresh without key invalidates all (null)", async () => {
    const result = await registry.execute("data.refresh", {});
    expect(result.ok).toBe(true);
    expect(invalidated).toContain(null);
  });

  it("data.refresh is callable multiple times", async () => {
    await registry.execute("data.refresh", { key: "a" });
    await registry.execute("data.refresh", { key: "b" });
    expect(invalidated).toEqual(["a", "b"]);
  });
});
