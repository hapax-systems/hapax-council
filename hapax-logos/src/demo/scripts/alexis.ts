/**
 * Alexis demo — comprehensive Hapax walkthrough.
 *
 * Every region change is preceded by focusRegion() for visual emphasis.
 * Ground ambient (surface) is shown with focusRegion("ground") to give it visual weight.
 * Camera grid only appears when narration explicitly introduces it.
 */
import type { DemoBridge } from "../useDemoBridge";
import type { RegionName } from "../../contexts/TerrainContext";

const REGIONS: RegionName[] = ["horizon", "field", "ground", "watershed", "bedrock"];

function resetAll(ctx: DemoBridge) {
  for (const r of REGIONS) ctx.terrain.setRegionDepth(r, "surface");
  ctx.terrain.focusRegion(null);
  ctx.terrain.setOverlay(null);
}

export const DEMO_SCRIPT = [
  // 0: Intro / Consent
  {
    title: "Introduction",
    audioFile: "00-intro.wav",
    actions: [],
  },

  // 1: What Is Hapax
  {
    title: "What Is Hapax",
    audioFile: "01-what-is-hapax.wav",
    actions: [],
  },

  // 2: First look — orient
  {
    title: "Orienting",
    audioFile: "02-terrain-intro.wav",
    actions: [],
  },

  // 3: Terrain walkthrough — expand each region
  {
    title: "The Terrain",
    audioFile: "03-terrain-walk.wav",
    actions: [
      { at: 1, action: (ctx: DemoBridge) => ctx.terrain.focusRegion("horizon"), label: "Focus horizon" },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "stratum"), label: "Horizon stratum" },
      { at: 7, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); }, label: "Field stratum" },
      { at: 12, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("ground"); ctx.terrain.setRegionDepth("ground", "stratum"); }, label: "Ground stratum" },
      { at: 16, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("watershed"); ctx.terrain.setRegionDepth("watershed", "stratum"); }, label: "Watershed stratum" },
      { at: 20, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "stratum"); }, label: "Bedrock stratum" },
      { at: 28, action: (ctx: DemoBridge) => resetAll(ctx), label: "Reset for depth demo" },
    ],
  },

  // 4: Depth cycling demo on Ground
  {
    title: "Depth Levels",
    audioFile: "04-depth-demo.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("ground"); }, label: "Focus ground surface — ambient" },
      { at: 12, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "stratum"), label: "Ground stratum — camera grid" },
      { at: 18, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "core"), label: "Ground core — hero camera" },
      { at: 26, action: (ctx: DemoBridge) => { ctx.terrain.setRegionDepth("ground", "surface"); }, label: "Back to surface" },
    ],
  },

  // 5: Horizon deep
  {
    title: "Horizon",
    audioFile: "05-horizon.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("horizon"); }, label: "Focus horizon" },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "stratum"), label: "Horizon stratum" },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("horizon", "core"), label: "Horizon core" },
    ],
  },

  // 6: Field and perception
  {
    title: "Field — Perception",
    audioFile: "06-field.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("field"); }, label: "Focus field" },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "stratum"), label: "Field stratum" },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("field", "core"), label: "Field core — perception canvas" },
    ],
  },

  // 7: Agents
  {
    title: "Agents",
    audioFile: "07-agents.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); }, label: "Field stratum — agent grid" },
    ],
  },

  // 8: Ground ambient (surface, focused for visual weight)
  {
    title: "Ground — Ambient",
    audioFile: "08-ground-ambient.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("ground"); }, label: "Focus ground — ambient canvas prominent" },
    ],
  },

  // 9: Ground cameras
  {
    title: "Ground — Cameras",
    audioFile: "09-ground-cameras.wav",
    actions: [
      // Narration says "watch what happens when Ground expands"
      { at: 3, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "stratum"), label: "Ground stratum — camera grid" },
      { at: 12, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("ground", "core"), label: "Ground core — hero + detections" },
    ],
  },

  // 10: Effects
  {
    title: "Visual Effects",
    audioFile: "10-effects.wav",
    actions: [
      // Ground still at core from scene 9
      { at: 4, action: (ctx: DemoBridge) => ctx.studio.selectPreset("ghost"), label: "Ghost" },
      { at: 8, action: (ctx: DemoBridge) => ctx.studio.selectPreset("trails"), label: "Trails" },
      { at: 12, action: (ctx: DemoBridge) => ctx.studio.selectPreset("screwed"), label: "Screwed" },
      { at: 16, action: (ctx: DemoBridge) => ctx.studio.selectPreset("datamosh"), label: "Datamosh" },
      { at: 20, action: (ctx: DemoBridge) => ctx.studio.selectPreset("vhs"), label: "VHS" },
      { at: 24, action: (ctx: DemoBridge) => ctx.studio.selectPreset("neon"), label: "Neon" },
      { at: 28, action: (ctx: DemoBridge) => ctx.studio.selectPreset("nightvision"), label: "NightVision" },
      { at: 32, action: (ctx: DemoBridge) => ctx.studio.selectPreset("thermal"), label: "Thermal" },
      { at: 42, action: (ctx: DemoBridge) => ctx.studio.selectPreset("clean"), label: "Clean" },
    ],
  },

  // 11: Stimmung
  {
    title: "Stimmung",
    audioFile: "11-stimmung.wav",
    actions: [
      // Stay on ground core — stimmung borders visible everywhere
    ],
  },

  // 12: Watershed
  {
    title: "Watershed",
    audioFile: "12-watershed.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("watershed"); }, label: "Focus watershed" },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("watershed", "stratum"), label: "Watershed stratum" },
      { at: 5, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("watershed", "core"), label: "Watershed core" },
    ],
  },

  // 13: Bedrock
  {
    title: "Bedrock",
    audioFile: "13-bedrock.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("bedrock"); }, label: "Focus bedrock" },
      { at: 2, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "stratum"), label: "Bedrock stratum" },
      { at: 4, action: (ctx: DemoBridge) => ctx.terrain.setRegionDepth("bedrock", "core"), label: "Bedrock core" },
    ],
  },

  // 14: Investigation
  {
    title: "Investigation",
    audioFile: "14-investigation.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => resetAll(ctx), label: "Reset" },
      { at: 2, action: (ctx: DemoBridge) => { ctx.terrain.setOverlay("investigation"); ctx.terrain.setInvestigationTab("chat"); }, label: "Chat" },
      { at: 8, action: (ctx: DemoBridge) => ctx.terrain.setInvestigationTab("insight"), label: "Insight" },
      { at: 14, action: (ctx: DemoBridge) => ctx.terrain.setInvestigationTab("demos"), label: "Demos" },
      { at: 20, action: (ctx: DemoBridge) => ctx.terrain.setOverlay(null), label: "Close" },
    ],
  },

  // 15: Axioms
  {
    title: "Governance",
    audioFile: "15-axioms.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("bedrock"); ctx.terrain.setRegionDepth("bedrock", "core"); }, label: "Bedrock core — governance" },
    ],
  },

  // 16: Ethics
  {
    title: "Ethics",
    audioFile: "16-ethics.wav",
    actions: [],
  },

  // 17: Research intro
  {
    title: "Research Introduction",
    audioFile: "17-research-intro.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("ground"); }, label: "Ambient for research" },
    ],
  },

  // 18: Clark
  {
    title: "Clark & Grounding",
    audioFile: "18-clark.wav",
    actions: [],
  },

  // 19: Why gap
  {
    title: "The 35-Year Gap",
    audioFile: "19-why-gap.wav",
    actions: [],
  },

  // 20: Architecture
  {
    title: "Voice Architecture",
    audioFile: "20-architecture.wav",
    actions: [],
  },

  // 21: Salience
  {
    title: "Salience Routing",
    audioFile: "21-salience.wav",
    actions: [],
  },

  // 22: Science
  {
    title: "The Science",
    audioFile: "22-science.wav",
    actions: [],
  },

  // 23: Honesty
  {
    title: "Honest Assessment",
    audioFile: "23-honesty.wav",
    actions: [],
  },

  // 24: Significance
  {
    title: "Significance",
    audioFile: "24-significance.wav",
    actions: [],
  },

  // 25: Temporal
  {
    title: "Temporal Experience",
    audioFile: "25-temporal.wav",
    actions: [],
  },

  // 26: Philosophy
  {
    title: "Philosophy",
    audioFile: "26-philosophy.wav",
    actions: [],
  },

  // 27: What Is Proven
  {
    title: "What Is Proven",
    audioFile: "27-proven.wav",
    actions: [
      { at: 1, action: (ctx: DemoBridge) => { ctx.terrain.focusRegion("field"); ctx.terrain.setRegionDepth("field", "stratum"); }, label: "Field — agents" },
    ],
  },

  // 28: Closing
  {
    title: "Closing",
    audioFile: "28-closing.wav",
    actions: [
      { at: 0.5, action: (ctx: DemoBridge) => { resetAll(ctx); ctx.terrain.focusRegion("ground"); }, label: "Ambient for closing" },
    ],
  },

  // 29: Outro
  {
    title: "Thank You",
    audioFile: "99-outro.wav",
    actions: [],
  },
];
