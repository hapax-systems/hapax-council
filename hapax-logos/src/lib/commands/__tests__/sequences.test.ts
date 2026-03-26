import { describe, it, expect, beforeEach } from "vitest";
import { CommandRegistry } from "../../commandRegistry";
import { registerBuiltinSequences } from "../sequences";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function setupRegistry() {
  const registry = new CommandRegistry();
  const calls: string[] = [];

  // terrain.focus — always ok
  registry.register({
    path: "terrain.focus",
    description: "Focus terrain region",
    execute: (args) => {
      calls.push(`terrain.focus:${args.region}`);
      return { ok: true };
    },
  });

  // terrain.depth.set — always ok
  registry.register({
    path: "terrain.depth.set",
    description: "Set terrain depth",
    execute: (args) => {
      calls.push(`terrain.depth.set:${args.region}:${args.depth}`);
      return { ok: true };
    },
  });

  // terrain.collapse — ok only when expandedRegion is set (simulated via closeable flag)
  let expandedRegion = false;
  registry.register({
    path: "terrain.collapse",
    description: "Collapse terrain",
    execute: () => {
      if (!expandedRegion) {
        calls.push("terrain.collapse:noop");
        return { ok: false, error: "Nothing to collapse" };
      }
      calls.push("terrain.collapse");
      expandedRegion = false;
      return { ok: true };
    },
  });
  const setExpanded = (val: boolean) => { expandedRegion = val; };

  // studio.smooth.enable — always ok
  registry.register({
    path: "studio.smooth.enable",
    description: "Enable smooth",
    execute: () => {
      calls.push("studio.smooth.enable");
      return { ok: true };
    },
  });

  // studio.smooth.disable — always ok
  registry.register({
    path: "studio.smooth.disable",
    description: "Disable smooth",
    execute: () => {
      calls.push("studio.smooth.disable");
      return { ok: true };
    },
  });

  // overlay.clear — ok only when overlay is active (simulated)
  let overlayActive = false;
  registry.register({
    path: "overlay.clear",
    description: "Clear overlay",
    execute: () => {
      if (!overlayActive) {
        calls.push("overlay.clear:noop");
        return { ok: false, error: "No overlay to clear" };
      }
      calls.push("overlay.clear");
      overlayActive = false;
      return { ok: true };
    },
  });
  const setOverlayActive = (val: boolean) => { overlayActive = val; };

  // split.close — ok only when split is open
  let splitOpen = false;
  registry.register({
    path: "split.close",
    description: "Close split",
    execute: () => {
      if (!splitOpen) {
        calls.push("split.close:noop");
        return { ok: false, error: "No split to close" };
      }
      calls.push("split.close");
      splitOpen = false;
      return { ok: true };
    },
  });
  const setSplitOpen = (val: boolean) => { splitOpen = val; };

  registerBuiltinSequences(registry);

  return {
    registry,
    calls,
    setExpanded,
    setOverlayActive,
    setSplitOpen,
  };
}

// ─── studio.enter ─────────────────────────────────────────────────────────────

describe("registerBuiltinSequences — studio.enter", () => {
  let ctx: ReturnType<typeof setupRegistry>;

  beforeEach(() => {
    ctx = setupRegistry();
  });

  it("registers studio.enter as a command", () => {
    const paths = ctx.registry.list().map((c) => c.path);
    expect(paths).toContain("studio.enter");
  });

  it("runs all 3 steps in order", async () => {
    const result = await ctx.registry.execute("studio.enter");
    expect(result.ok).toBe(true);
    expect(ctx.calls).toEqual([
      "terrain.focus:ground",
      "terrain.depth.set:ground:core",
      "studio.smooth.enable",
    ]);
  });

  it("stops and returns failure if terrain.focus fails", async () => {
    ctx.registry.unregister("terrain.focus");
    ctx.registry.register({
      path: "terrain.focus",
      description: "Focus (failing)",
      execute: () => ({ ok: false, error: "focus failed" }),
    });
    const result = await ctx.registry.execute("studio.enter");
    expect(result.ok).toBe(false);
    // Only terrain.focus ran (stops on first failure)
    expect(ctx.calls).not.toContain("studio.smooth.enable");
  });
});

// ─── studio.exit ──────────────────────────────────────────────────────────────

describe("registerBuiltinSequences — studio.exit", () => {
  let ctx: ReturnType<typeof setupRegistry>;

  beforeEach(() => {
    ctx = setupRegistry();
  });

  it("registers studio.exit as a command", () => {
    const paths = ctx.registry.list().map((c) => c.path);
    expect(paths).toContain("studio.exit");
  });

  it("runs both steps when terrain is expanded", async () => {
    ctx.setExpanded(true);
    const result = await ctx.registry.execute("studio.exit");
    expect(result.ok).toBe(true);
    expect(ctx.calls).toEqual(["studio.smooth.disable", "terrain.collapse"]);
  });

  it("smooth.disable always runs even if collapse is noop", async () => {
    // terrain is NOT expanded → collapse returns ok:false
    // default sequence stops on first failure — but smooth.disable is step 1, collapse is step 2
    // smooth.disable succeeds → collapse fails → sequence stops with failure
    const result = await ctx.registry.execute("studio.exit");
    expect(ctx.calls[0]).toBe("studio.smooth.disable");
    expect(ctx.calls[1]).toBe("terrain.collapse:noop");
    expect(result.ok).toBe(false);
  });
});

// ─── escape ───────────────────────────────────────────────────────────────────

describe("registerBuiltinSequences — escape", () => {
  let ctx: ReturnType<typeof setupRegistry>;

  beforeEach(() => {
    ctx = setupRegistry();
  });

  it("registers escape as a command", () => {
    const paths = ctx.registry.list().map((c) => c.path);
    expect(paths).toContain("escape");
  });

  it("stops at overlay.clear when overlay is active (first success)", async () => {
    ctx.setOverlayActive(true);
    const result = await ctx.registry.execute("escape");
    expect(result.ok).toBe(true);
    expect(ctx.calls).toEqual(["overlay.clear"]);
    // split.close and terrain.collapse were NOT called
    expect(ctx.calls).not.toContain("split.close");
    expect(ctx.calls).not.toContain("terrain.collapse");
  });

  it("falls through to split.close when overlay is inactive", async () => {
    ctx.setSplitOpen(true);
    const result = await ctx.registry.execute("escape");
    expect(result.ok).toBe(true);
    expect(ctx.calls).toContain("overlay.clear:noop");
    expect(ctx.calls).toContain("split.close");
    // terrain.collapse was NOT called
    expect(ctx.calls).not.toContain("terrain.collapse");
    expect(ctx.calls).not.toContain("terrain.collapse:noop");
  });

  it("falls through to terrain.collapse when nothing else matches", async () => {
    ctx.setExpanded(true); // make terrain collapseable
    const result = await ctx.registry.execute("escape");
    expect(result.ok).toBe(true);
    expect(ctx.calls).toContain("terrain.collapse");
  });

  it("returns failure when nothing is active (all steps fail)", async () => {
    // overlay inactive, split closed, terrain not expanded
    const result = await ctx.registry.execute("escape");
    expect(result.ok).toBe(false);
    expect(ctx.calls).toEqual([
      "overlay.clear:noop",
      "split.close:noop",
      "terrain.collapse:noop",
    ]);
  });
});
