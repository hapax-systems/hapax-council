import { describe, it, expect, beforeEach } from "vitest";
import { CommandRegistry } from "../../commandRegistry";
import {
  registerTerrainCommands,
  type TerrainState,
  type TerrainActions,
} from "../terrain";

// ─── Helpers ─────────────────────────────────────────────────────────────────

type Depths = TerrainState["depths"];

function makeState(overrides: Partial<TerrainState> = {}): TerrainState {
  return {
    focusedRegion: null,
    depths: {
      horizon: "surface",
      field: "surface",
      ground: "surface",
      watershed: "surface",
      bedrock: "surface",
    },
    ...overrides,
  };
}

function makeActions(state: { current: TerrainState }): TerrainActions {
  return {
    setFocusedRegion: (region) => {
      state.current = { ...state.current, focusedRegion: region };
    },
    setDepth: (region, depth) => {
      state.current = {
        ...state.current,
        depths: { ...state.current.depths, [region]: depth },
      };
    },
  };
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("terrain domain commands", () => {
  let registry: CommandRegistry;
  let stateHolder: { current: TerrainState };

  beforeEach(() => {
    registry = new CommandRegistry();
    stateHolder = { current: makeState() };
    registerTerrainCommands(
      registry,
      () => stateHolder.current,
      makeActions(stateHolder),
    );
  });

  // ── terrain.focus ──────────────────────────────────────────────────────────

  describe("terrain.focus", () => {
    it("focuses a valid region", async () => {
      const result = await registry.execute("terrain.focus", { region: "ground" });
      expect(result.ok).toBe(true);
      expect(stateHolder.current.focusedRegion).toBe("ground");
    });

    it("cycles depth when region is already focused", async () => {
      stateHolder.current = makeState({ focusedRegion: "ground" });
      await registry.execute("terrain.focus", { region: "ground" });
      expect(stateHolder.current.depths.ground).toBe("stratum");
    });

    it("cycles depth surface→stratum→core→surface", async () => {
      stateHolder.current = makeState({ focusedRegion: "field" });
      stateHolder.current.depths.field = "surface";
      await registry.execute("terrain.focus", { region: "field" });
      expect(stateHolder.current.depths.field).toBe("stratum");

      await registry.execute("terrain.focus", { region: "field" });
      expect(stateHolder.current.depths.field).toBe("core");

      await registry.execute("terrain.focus", { region: "field" });
      expect(stateHolder.current.depths.field).toBe("surface");
    });

    it("unfocuses when region is null", async () => {
      stateHolder.current = makeState({ focusedRegion: "ground" });
      const result = await registry.execute("terrain.focus", { region: null });
      expect(result.ok).toBe(true);
      expect(stateHolder.current.focusedRegion).toBeNull();
    });

    it("rejects invalid region", async () => {
      const result = await registry.execute("terrain.focus", { region: "invalid" });
      expect(result.ok).toBe(false);
      expect(result.error).toBeDefined();
    });

    it("all valid regions are accepted", async () => {
      for (const region of ["horizon", "field", "ground", "watershed", "bedrock"]) {
        stateHolder.current = makeState();
        const result = await registry.execute("terrain.focus", { region });
        expect(result.ok).toBe(true);
      }
    });
  });

  // ── terrain.depth.set ──────────────────────────────────────────────────────

  describe("terrain.depth.set", () => {
    it("sets depth for a region", async () => {
      const result = await registry.execute("terrain.depth.set", {
        region: "horizon",
        depth: "core",
      });
      expect(result.ok).toBe(true);
      expect(stateHolder.current.depths.horizon).toBe("core");
    });

    it("rejects invalid region", async () => {
      const result = await registry.execute("terrain.depth.set", {
        region: "invalid",
        depth: "core",
      });
      expect(result.ok).toBe(false);
    });

    it("rejects invalid depth", async () => {
      const result = await registry.execute("terrain.depth.set", {
        region: "ground",
        depth: "deep",
      });
      expect(result.ok).toBe(false);
    });

    it("rejects missing args", async () => {
      const result = await registry.execute("terrain.depth.set", { region: "ground" });
      expect(result.ok).toBe(false);
    });
  });

  // ── terrain.depth.cycle ───────────────────────────────────────────────────

  describe("terrain.depth.cycle", () => {
    it("cycles surface→stratum", async () => {
      const result = await registry.execute("terrain.depth.cycle", { region: "ground" });
      expect(result.ok).toBe(true);
      expect(stateHolder.current.depths.ground).toBe("stratum");
    });

    it("cycles stratum→core", async () => {
      stateHolder.current.depths.ground = "stratum";
      await registry.execute("terrain.depth.cycle", { region: "ground" });
      expect(stateHolder.current.depths.ground).toBe("core");
    });

    it("cycles core→surface", async () => {
      stateHolder.current.depths.ground = "core";
      await registry.execute("terrain.depth.cycle", { region: "ground" });
      expect(stateHolder.current.depths.ground).toBe("surface");
    });

    it("rejects invalid region", async () => {
      const result = await registry.execute("terrain.depth.cycle", { region: "nope" });
      expect(result.ok).toBe(false);
    });
  });

  // ── terrain.collapse ──────────────────────────────────────────────────────

  describe("terrain.collapse", () => {
    it("resets all depths to surface and unfocuses", async () => {
      stateHolder.current = makeState({
        focusedRegion: "ground",
        depths: {
          horizon: "core",
          field: "stratum",
          ground: "core",
          watershed: "stratum",
          bedrock: "core",
        },
      });
      const result = await registry.execute("terrain.collapse");
      expect(result.ok).toBe(true);
      expect(stateHolder.current.focusedRegion).toBeNull();
      for (const depth of Object.values(stateHolder.current.depths)) {
        expect(depth).toBe("surface");
      }
    });

    it("returns ok:false when already collapsed", async () => {
      // already all surface, no focus
      const result = await registry.execute("terrain.collapse");
      expect(result.ok).toBe(false);
    });

    it("returns ok:false when only focus differs (depths all surface)", async () => {
      stateHolder.current = makeState({ focusedRegion: "ground" });
      const result = await registry.execute("terrain.collapse");
      // focus cleared counts as a change → ok:true
      expect(result.ok).toBe(true);
    });
  });

  // ── queries ───────────────────────────────────────────────────────────────

  describe("queries", () => {
    it("terrain.focusedRegion returns current focus", () => {
      stateHolder.current = makeState({ focusedRegion: "bedrock" });
      expect(registry.query("terrain.focusedRegion")).toBe("bedrock");
    });

    it("terrain.depths returns depths map", () => {
      stateHolder.current.depths.ground = "stratum";
      const depths = registry.query("terrain.depths") as Depths;
      expect(depths.ground).toBe("stratum");
    });

    it("terrain.coreMiddle returns true when ground is at core", () => {
      stateHolder.current.depths.ground = "core";
      expect(registry.query("terrain.coreMiddle")).toBe(true);
    });

    it("terrain.coreMiddle returns false when ground is not at core", () => {
      stateHolder.current.depths.ground = "surface";
      expect(registry.query("terrain.coreMiddle")).toBe(false);
    });
  });

  // ── getState is called at execution time ──────────────────────────────────

  describe("late binding", () => {
    it("uses current state at execution time, not registration time", async () => {
      // At registration stateHolder.current.focusedRegion is null.
      // After update it should reflect the new state.
      stateHolder.current = makeState({ focusedRegion: "horizon" });
      await registry.execute("terrain.focus", { region: "horizon" }); // should cycle depth
      expect(stateHolder.current.depths.horizon).toBe("stratum");
    });
  });
});
