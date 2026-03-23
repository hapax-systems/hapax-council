/**
 * Alexis demo v4 — hand-choreographed.
 * Every action precisely timed to narration content.
 * No Opus inference. No keyword matching. Direct control.
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
  // 0: Riser (6s) — no actions
  { title: "", audioFile: "00-riser.wav", actions: [] },

  // 0.5: Bing (0.8s) — pleasant chime before narration
  { title: "", audioFile: "00-bing.wav", actions: [] },

  // 1: Intro (7.5s) — ambient
  { title: "Introduction", audioFile: "00-intro.wav", actions: [] },

  // 2: What Is Hapax (52.8s) — ambient, then briefly show field for agents
  {
    title: "What Is Hapax",
    audioFile: "01-what-is-hapax.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "Forty-five specialized agents" ~35s in
      { at: 34, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 44, action: (ctx: DemoBridge) => { reset(ctx); } },
    ],
  },

  // 3: Consent Foundation (79.2s) — bedrock for governance/consent
  {
    title: "Consent",
    audioFile: "02-consent-foundation.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "constitutional axioms" ~10s
      { at: 9, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 11, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "stratum") },
      { at: 14, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
      { at: 16, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 4000) },
      // "Two consent contracts currently exist" ~50s
      { at: 50, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
      // Settle back
      { at: 70, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 4: What Logos Looks Like (34.5s) — show all regions at surface
  {
    title: "The Interface",
    audioFile: "03-what-logos-looks-like.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "Five horizontal regions" ~12s
      { at: 12, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 2000) },
      { at: 15, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 2000) },
      { at: 18, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 2000) },
      { at: 21, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("watershed", 2000) },
      { at: 24, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 2000) },
    ],
  },

  // 5: The Five Regions (38.1s) — expand each briefly
  {
    title: "Five Regions",
    audioFile: "04-the-five-regions.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "Horizon" ~1s
      { at: 1, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("horizon"); ctx.terrain.setRegionDepth("horizon", "stratum"); } },
      // "Field" ~8s
      { at: 8, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      // "Ground" ~14s
      { at: 14, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("ground"); } },
      // "Watershed" ~20s
      { at: 20, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("watershed"); ctx.terrain.setRegionDepth("watershed", "stratum"); } },
      // "Bedrock" ~26s
      { at: 26, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "stratum"); } },
      { at: 34, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 6: Depth (22.6s) — demo depth cycling on field
  {
    title: "Depth",
    audioFile: "05-depth.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "Surface" ~3s
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("field") },
      // "Stratum" ~8s
      { at: 8, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "stratum") },
      // "Core" ~12s
      { at: 12, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "core") },
      // "What they focus on opens up" ~18s
      { at: 18, action: (ctx: DemoBridge) => { reset(ctx); } },
    ],
  },

  // 7: Horizon (43.5s) — horizon at core
  {
    title: "Horizon",
    audioFile: "06-horizon.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("horizon") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "stratum") },
      { at: 6, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "core") },
      // "Nudges in the center" ~10s
      { at: 10, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 3000) },
      // Stay on horizon core for the whole scene
    ],
  },

  // 8: Perception (47.7s) — field at core
  {
    title: "Perception",
    audioFile: "07-perception.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("field") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "core") },
      // "severity between zero and one" ~20s
      { at: 20, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 3000) },
    ],
  },

  // 9: Agents (49.2s) — field at stratum (agent grid)
  {
    title: "Agents",
    audioFile: "08-agents.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("field") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 3000) },
    ],
  },

  // 10: Ground (55.9s) — surface → stratum → core
  {
    title: "Ground",
    audioFile: "09-ground.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
      // "ambient canvas" — stay at surface ~10s
      // "camera feeds appear" ~15s
      { at: 15, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "stratum") },
      // "core depth, hero camera" ~20s
      { at: 20, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "core") },
      // "Cyan for looking at a screen" ~30s
      { at: 30, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 4000) },
      // "desaturated. Grey." ~48s
      { at: 48, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 3000) },
    ],
  },

  // 11: Effects (46.1s) — stay on ground core, narration describes effects
  // NOTE: Effect preset switching requires GroundStudioContext which DemoRunner
  // can't access (it wraps only Ground region). Effects are narrated over hero camera.
  {
    title: "Effects",
    audioFile: "10-effects.wav",
    actions: [
      // Ground stays at core from previous scene — hero camera visible
      // Narration describes effects over the live camera feed
    ],
  },

  // 12: Stimmung (62.5s) — show all regions at surface (borders visible)
  {
    title: "Stimmung",
    audioFile: "11-stimmung.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // Stimmung is visible on borders of all regions — stay at surface
      // "warm glow on the region borders" ~42s
      { at: 42, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 2000) },
      { at: 45, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 2000) },
      { at: 48, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 2000) },
    ],
  },

  // 13: Watershed (44.2s) — watershed at core
  {
    title: "Watershed",
    audioFile: "12-watershed-and-profile.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("watershed") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("watershed", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("watershed", "core") },
      // "Eleven dimensions" ~16s
      { at: 16, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("watershed", 3000) },
    ],
  },

  // 14: Bedrock (22.7s) — bedrock at core
  {
    title: "Bedrock",
    audioFile: "13-bedrock.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "stratum") },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
    ],
  },

  // 15: Investigation (14.2s) — overlay
  {
    title: "Investigation",
    audioFile: "14-investigation.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 2, action: (ctx: DemoBridge) => { ctx.terrain.setOverlay("investigation"); ctx.terrain.setInvestigationTab("chat"); } },
      { at: 6, action: (ctx: DemoBridge) => ctx.terrain.setInvestigationTab("insight") },
      { at: 10, action: (ctx: DemoBridge) => ctx.terrain.setInvestigationTab("demos") },
      { at: 13, action: (ctx: DemoBridge) => ctx.terrain.setOverlay(null) },
    ],
  },

  // 16: Axioms (71.9s) — bedrock at core
  {
    title: "Axioms",
    audioFile: "15-axioms.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 4, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
      // "Single user" ~5s
      { at: 6, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
      // "interpretive law" ~65s
      { at: 65, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
    ],
  },

  // 17: Ethics (67.2s) — bedrock, then briefly ground for cameras
  {
    title: "Ethics",
    audioFile: "16-ethics.wav",
    actions: [
      // Stay on bedrock from axioms — no reset
      // "cameras" context ~25s — briefly show ground
      { at: 25, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("bedrock", "surface"); ctx.terrain.focusRegion("ground"); ctx.terrain.setRegionDepth("ground", "stratum"); } },
      // "consent is structural" ~35s — back to bedrock
      { at: 35, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("ground", "surface"); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "core"); } },
      // "fundamentally different" ~60s
      { at: 60, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 18: Transition (20.7s) — ambient
  {
    title: "Research Transition",
    audioFile: "17-transition.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
    ],
  },

  // 19: Clark (65s) — ambient (conceptual)
  {
    title: "Clark & Brennan",
    audioFile: "18-clark.wav",
    actions: [
      // Hold ambient — conceptual narration
    ],
  },

  // 20: Gap (57.5s) — ambient (conceptual)
  {
    title: "The 35-Year Gap",
    audioFile: "19-gap.wav",
    actions: [
      // Hold ambient
    ],
  },

  // 21: Voice Architecture (72.2s) — ambient, briefly show field
  {
    title: "Voice Architecture",
    audioFile: "20-voice-architecture.wav",
    actions: [
      // Conceptual — hold ambient
      // "grounding loop classifies every response" ~50s — briefly show field
      { at: 50, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 60, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("ground"); } },
    ],
  },

  // 22: Salience (31.5s) — ambient
  {
    title: "Salience",
    audioFile: "21-salience.wav",
    actions: [
      // Hold ambient — conceptual
    ],
  },

  // 23: Methodology (46s) — ambient
  {
    title: "Methodology",
    audioFile: "22-methodology.wav",
    actions: [
      // Hold ambient
    ],
  },

  // 24: Results (55.9s) — ambient
  {
    title: "Results",
    audioFile: "23-results.wav",
    actions: [
      // Hold ambient — research data
    ],
  },

  // 25: Originality (41.8s) — ambient
  {
    title: "Originality",
    audioFile: "24-originality.wav",
    actions: [
      // Hold ambient
    ],
  },

  // 26: Temporal (64.9s) — watershed for flow/temporal
  {
    title: "Temporal Experience",
    audioFile: "25-temporal.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "ring buffer of perception snapshots" ~28s
      { at: 28, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("watershed"); ctx.terrain.setRegionDepth("watershed", "stratum"); } },
      { at: 35, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("watershed", "core") },
      { at: 55, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 27: Philosophy (70.5s) — cycle through relevant regions
  {
    title: "Philosophy",
    audioFile: "26-philosophy.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "Heidegger → stimmung" ~5s — show borders
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 3000) },
      // "Merleau-Ponty → sensors" ~18s — show field
      { at: 18, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "core"); } },
      { at: 25, action: (ctx: DemoBridge) => reset(ctx) },
      // "Wittgenstein → grounding" ~30s — ambient
      // "Husserl → temporal" ~38s — watershed
      { at: 38, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("watershed"); ctx.terrain.setRegionDepth("watershed", "core"); } },
      { at: 48, action: (ctx: DemoBridge) => reset(ctx) },
      // "engineering problem came first" ~60s
    ],
  },

  // 28: Proven (44.5s) — show field stratum for agents/tests
  {
    title: "What Is Proven",
    audioFile: "27-proven.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      // "infrastructure works" ~3s
      { at: 3, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      // "What remains" ~20s — show bedrock
      { at: 20, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "stratum"); } },
      { at: 35, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // 29: Closing (48.1s) — ambient
  {
    title: "Closing",
    audioFile: "28-closing.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
    ],
  },

  // 30: Outro (0.9s)
  {
    title: "Thank You",
    audioFile: "99-outro.wav",
    actions: [],
  },
];
