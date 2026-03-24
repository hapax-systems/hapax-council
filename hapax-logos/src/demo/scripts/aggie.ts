/**
 * Aggie demo — hand-choreographed for Agatha (11).
 * Updated with classification inspector, theme switching, boot overlay,
 * ground surface enrichment, keyboard hints.
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
  // Riser + bing
  { title: "", audioFile: "00-riser.wav", actions: [] },
  { title: "", audioFile: "00-bing.wav", actions: [] },

  // Intro
  { title: "Introduction", audioFile: "00-intro.wav", actions: [] },

  // What It Is — ambient, briefly show field for agents
  {
    title: "What It Is",
    audioFile: "01-what-it-is.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 22, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 32, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 3000) },
      { at: 42, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // Consent — bedrock
  {
    title: "Consent",
    audioFile: "02-consent.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 8, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 10, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "stratum") },
      { at: 13, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
      { at: 15, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 4000) },
      { at: 35, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
      { at: 46, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // The Interface — regions + theme mention
  {
    title: "The Interface",
    audioFile: "03-the-interface.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 10, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 2000) },
      { at: 13, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("field", 2000) },
      { at: 16, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 2000) },
      { at: 19, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("watershed", 2000) },
      { at: 22, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 2000) },
      // Depth demo on field
      { at: 26, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 30, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "core") },
      { at: 34, action: (ctx: DemoBridge) => reset(ctx) },
      // "R and D mode" / "Research mode" — narration mentions theme, UI shows current theme
    ],
  },

  // Horizon
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

  // Perception — field core
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

  // Agents — field stratum
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

  // Ground — surface → stratum → core with detection overlays
  {
    title: "Ground",
    audioFile: "07-ground.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1.5, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
      // "nudge indicators" / "presence indicator" — visible at surface
      { at: 18, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "stratum") },
      { at: 22, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "core") },
      { at: 30, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 4000) },
      { at: 50, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 3000) },
    ],
  },

  // Classification Inspector — open C overlay
  {
    title: "Classification Inspector",
    audioFile: "08-inspector.wav",
    actions: [
      // Stay on ground core, then open classification inspector
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.setOverlay("classification") },
      // Hold inspector open for the entire narration
      { at: 55, action: (ctx: DemoBridge) => ctx.terrain.setOverlay(null) },
    ],
  },

  // Effects — ground core
  {
    title: "Effects",
    audioFile: "09-effects.wav",
    actions: [
      // Ground stays at core from previous
    ],
  },

  // Stimmung — all regions surface, borders visible
  {
    title: "Stimmung",
    audioFile: "10-stimmung.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 38, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("horizon", 2000) },
      { at: 41, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 2000) },
      { at: 44, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 2000) },
    ],
  },

  // Governance — bedrock core
  {
    title: "Governance",
    audioFile: "11-governance.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("bedrock") },
      { at: 4, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core") },
      { at: 6, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("bedrock", 3000) },
    ],
  },

  // Ethics — bedrock, briefly ground
  {
    title: "Ethics",
    audioFile: "12-ethics.wav",
    actions: [
      { at: 20, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("bedrock", "surface"); ctx.terrain.focusRegion("ground"); ctx.terrain.setRegionDepth("ground", "stratum"); } },
      { at: 30, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("ground", "surface"); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "core"); } },
      { at: 44, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // Research intro — ambient
  {
    title: "Research",
    audioFile: "13-research-intro.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
    ],
  },

  // Clark
  { title: "Clark & Brennan", audioFile: "14-clark.wav", actions: [] },

  // Why Not
  { title: "The Gap", audioFile: "15-why-not.wav", actions: [] },

  // Voice System — briefly field
  {
    title: "Voice System",
    audioFile: "16-voice-system.wav",
    actions: [
      { at: 25, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 35, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("ground"); } },
    ],
  },

  // Methodology — ambient
  { title: "Methodology", audioFile: "17-methodology.wav", actions: [] },

  // Philosophy — cycle regions
  {
    title: "Philosophy",
    audioFile: "18-philosophy.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.highlightRegion("ground", 3000) },
      { at: 15, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "core"); } },
      { at: 22, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 35, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("watershed"); ctx.terrain.setRegionDepth("watershed", "core"); } },
      { at: 44, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // What Is Proven — field → bedrock
  {
    title: "What Is Proven",
    audioFile: "19-what-is-proven.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 2, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); } },
      { at: 15, action: (ctx: DemoBridge) => { reset(ctx); ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "stratum"); } },
      { at: 26, action: (ctx: DemoBridge) => reset(ctx) },
    ],
  },

  // Closing — ambient
  {
    title: "Closing",
    audioFile: "20-closing.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => reset(ctx) },
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("ground") },
    ],
  },

  // Outro
  { title: "That Is Hapax", audioFile: "99-outro.wav", actions: [] },
];
