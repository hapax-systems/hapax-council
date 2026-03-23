/**
 * Kids demo — hand-choreographed for Agatha (11) and Simon (8).
 * Same structure as alexis-v4.ts. Every action manually timed.
 */
import type { DemoBridge } from "../useDemoBridge";
import type { RegionName } from "../../contexts/TerrainContext";

const ALL: RegionName[] = ["horizon", "field", "ground", "watershed", "bedrock"];

function reset(ctx: DemoBridge) {
  for (const r of ALL) ctx.terrain.setRegionDepth(r, "surface");
  ctx.terrain.focusRegion(null);
  ctx.terrain.setOverlay(null);
  ctx.terrain.highlightRegion(null);
}

export const DEMO_SCRIPT = [
  // 0: Riser (6s)
  { title: "", audioFile: "00-riser.wav", actions: [] },
  // 0.5: Bing (0.8s)
  { title: "", audioFile: "00-bing.wav", actions: [] },
  // 1: Intro (3.5s) — ambient
  { title: "Introduction", audioFile: "00-intro.wav", actions: [] },

  // 2: What It Is (48.9s) — ambient, briefly show field for agents
  {
    title: "What It Is",
    audioFile: "01-what-it-is.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "Forty-five separate programs" ~20s
      { at: 20, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 30, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 3000) },
      { at: 40, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 3: Consent (53.1s) — bedrock
  {
    title: "Consent",
    audioFile: "02-consent.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "cameras" ~8s
      { at: 8, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 10, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "stratum") },
      { at: 13, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
      // "consent contract" ~15s
      { at: 15, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 4000) },
      // "Two consent contracts" ~35s
      { at: 35, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
      { at: 46, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 4: Interface (38.2s) — show regions
  {
    title: "The Interface",
    audioFile: "03-the-interface.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "five horizontal regions" ~10s
      { at: 10, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 2000) },
      { at: 13, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 2000) },
      { at: 16, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 2000) },
      { at: 19, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("watershed", 2000) },
      { at: 22, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 2000) },
      // "three depths" ~25s — demo on field
      { at: 26, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 30, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "core") },
      { at: 34, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 5: Horizon (32.9s) — horizon core
  {
    title: "Horizon",
    audioFile: "04-horizon.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("horizon") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "core") },
      { at: 8, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 3000) },
    ],
  },

  // 6: Perception (39.0s) — field core
  {
    title: "Perception",
    audioFile: "05-perception.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("field") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "core") },
      { at: 15, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 3000) },
    ],
  },

  // 7: Agents (39.3s) — field stratum
  {
    title: "Agents",
    audioFile: "06-agents.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("field") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 3000) },
    ],
  },

  // 8: Ground (57.4s) — surface → stratum → core
  {
    title: "Ground",
    audioFile: "07-ground.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
      // "camera feeds appear" ~18s
      { at: 18, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "stratum") },
      // "core depth" ~22s
      { at: 22, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "core") },
      // "Cyan for a screen" ~30s
      { at: 30, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 4000) },
      // "appears grey" ~48s
      { at: 48, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 3000) },
    ],
  },

  // 9: Effects (41.2s) — ground core, narrate effects
  {
    title: "Effects",
    audioFile: "08-effects.wav",
    actions: [
      // Stay on ground core from previous scene
    ],
  },

  // 10: Stimmung (55.0s) — all regions surface, borders visible
  {
    title: "Stimmung",
    audioFile: "09-stimmung.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "glow on borders" ~38s
      { at: 38, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 2000) },
      { at: 41, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 2000) },
      { at: 44, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 2000) },
    ],
  },

  // 11: Governance (48.0s) — bedrock core
  {
    title: "Governance",
    audioFile: "10-governance.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 4, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
      { at: 6, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
    ],
  },

  // 12: Ethics (49.8s) — bedrock, briefly ground
  {
    title: "Ethics",
    audioFile: "11-ethics.wav",
    actions: [
      // Stay on bedrock from governance
      // "cameras" ~20s — briefly show ground
      { at: 20, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("bedrock", "surface"); ctx.terrain.focusRegion("ground"); ctx.terrain.setRegionDepth("ground", "stratum"); } },
      // "code itself" ~30s — back to bedrock
      { at: 30, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("ground", "surface"); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "core"); } },
      { at: 44, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 13: Research Intro (15.7s) — ambient
  {
    title: "Research",
    audioFile: "12-research-intro.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
    ],
  },

  // 14: Clark (45.8s) — ambient
  { title: "Clark & Brennan", audioFile: "13-clark.wav", actions: [] },

  // 15: Why Not (36.7s) — ambient
  { title: "The Gap", audioFile: "14-why-not.wav", actions: [] },

  // 16: Voice System (39.7s) — ambient, briefly field
  {
    title: "Voice System",
    audioFile: "15-voice-system.wav",
    actions: [
      { at: 25, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 33, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("ground"); } },
    ],
  },

  // 17: Methodology (46.6s) — ambient
  { title: "Methodology", audioFile: "16-methodology.wav", actions: [] },

  // 18: Philosophy (53.9s) — cycle regions
  {
    title: "Philosophy",
    audioFile: "17-philosophy.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "stimmung" ~5s
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 3000) },
      // "sensor system" ~15s — field
      { at: 15, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "core"); } },
      { at: 22, action: (ctx: DemoBridge) => reset(ctx) },
      // "temporal bands" ~35s — watershed
      { at: 35, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("watershed"); ctx.terrain.setRegionDepth("watershed", "core"); } },
      { at: 44, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 19: What Is Proven (33.3s) — field stratum → bedrock
  {
    title: "What Is Proven",
    audioFile: "18-what-is-proven.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 2, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      // "What remains" ~15s
      { at: 15, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "stratum"); } },
      { at: 26, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 20: Closing (32.0s) — ambient
  {
    title: "Closing",
    audioFile: "19-closing.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
    ],
  },

  // 21: Outro (1.3s)
  { title: "That Is Hapax", audioFile: "99-outro.wav", actions: [] },
];
