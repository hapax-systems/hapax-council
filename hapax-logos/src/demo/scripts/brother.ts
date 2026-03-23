/**
 * Demo script — scene definitions with timed actions.
 *
 * Actions fire at exact offsets from scene start, synced to narration audio.
 * Principle: actions happen when the narration mentions them.
 * Scenes with no actions hold the previous view.
 */
import type { DemoBridge } from "../useDemoBridge";
import type { RegionName } from "../../contexts/TerrainContext";

const REGIONS: RegionName[] = ["horizon", "field", "ground", "watershed", "bedrock"];

function resetAllToSurface(ctx: DemoBridge) {
  for (const r of REGIONS) ctx.terrain.setRegionDepth(r, "surface");
  ctx.terrain.focusRegion(null);
  ctx.terrain.setOverlay(null);
}

export interface DemoAction {
  at: number;
  action: (ctx: DemoBridge) => void;
  label?: string;
}

export interface DemoScene {
  title: string;
  audioFile: string;
  actions: DemoAction[];
}

export const DEMO_SCRIPT: DemoScene[] = [
  // ── 0: Intro (77.8s) ─────────────────────────────────────────────────
  {
    title: "Introduction",
    audioFile: "00-intro.wav",
    actions: [
      // Terrain at surface — calm ambient view during consent discussion
    ],
  },

  // ── 1: What Is Hapax (58.5s) ─────────────────────────────────────────
  {
    title: "What Is Hapax",
    audioFile: "01-what-is-hapax.wav",
    actions: [
      // Hold ambient view — narration is conceptual
    ],
  },

  // ── 2: The Terrain Model (65.2s) ─────────────────────────────────────
  {
    title: "The Terrain Model",
    audioFile: "02-the-terrain-model.wav",
    actions: [
      // "five regions, from top to bottom" — expand each one
      { at: 5, action: (ctx) => ctx.terrain.setRegionDepth("horizon", "stratum"), label: "Expand horizon" },
      { at: 10, action: (ctx) => ctx.terrain.setRegionDepth("field", "stratum"), label: "Expand field" },
      { at: 14, action: (ctx) => ctx.terrain.setRegionDepth("ground", "stratum"), label: "Expand ground" },
      { at: 18, action: (ctx) => ctx.terrain.setRegionDepth("watershed", "stratum"), label: "Expand watershed" },
      { at: 22, action: (ctx) => ctx.terrain.setRegionDepth("bedrock", "stratum"), label: "Expand bedrock" },
      // "three depths" — demonstrate depth cycling on ground
      { at: 30, action: (ctx) => resetAllToSurface(ctx), label: "Reset to surface" },
      { at: 33, action: (ctx) => ctx.terrain.setRegionDepth("ground", "stratum"), label: "Ground stratum" },
      { at: 38, action: (ctx) => ctx.terrain.setRegionDepth("ground", "core"), label: "Ground core" },
      { at: 45, action: (ctx) => ctx.terrain.setRegionDepth("ground", "surface"), label: "Ground back to surface" },
      { at: 50, action: (ctx) => resetAllToSurface(ctx), label: "Reset all" },
    ],
  },

  // ── 3: Horizon (53.1s) ───────────────────────────────────────────────
  {
    title: "Horizon — Time Awareness",
    audioFile: "03-horizon-time-awareness.wav",
    actions: [
      { at: 1, action: (ctx) => ctx.terrain.setRegionDepth("horizon", "stratum"), label: "Horizon stratum" },
      { at: 5, action: (ctx) => ctx.terrain.setRegionDepth("horizon", "core"), label: "Horizon core" },
      // Hold at core for rest of narration — goals, nudges, engine, briefing
    ],
  },

  // ── 4: Field & Perception (76.8s) ────────────────────────────────────
  {
    title: "Field — Agents and Perception",
    audioFile: "04-field-agents-and-perception.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        resetAllToSurface(ctx);
        ctx.terrain.setRegionDepth("field", "stratum");
      }, label: "Reset + field stratum" },
      { at: 3, action: (ctx) => ctx.terrain.setRegionDepth("field", "core"), label: "Field core — perception canvas" },
      // Hold at core — narration describes zones, signals, severity
    ],
  },

  // ── 5: Agent Architecture (89.0s) ────────────────────────────────────
  {
    title: "The Agent Architecture",
    audioFile: "05-the-agent-architecture.wav",
    actions: [
      // HOLD — field at core from previous scene, narration is conceptual
    ],
  },

  // ── 6: Ground — Cameras (69.3s) ──────────────────────────────────────
  {
    title: "Ground — Presence and Cameras",
    audioFile: "06-ground-presence-and-cameras.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        resetAllToSurface(ctx);
      }, label: "Reset to surface — ambient visible" },
      // "At surface depth, you see the ambient canvas"
      { at: 10, action: (ctx) => ctx.terrain.setRegionDepth("ground", "stratum"), label: "Ground stratum — camera grid" },
      // "At stratum depth, a camera grid appears"
      { at: 22, action: (ctx) => ctx.terrain.setRegionDepth("ground", "core"), label: "Ground core — hero camera" },
      // "At core depth, the hero camera fills the region"
      // Narration describes detection overlays, gaze colors, emotion tints
    ],
  },

  // ── 7: Visual Effects (63.2s) ────────────────────────────────────────
  {
    title: "Visual Effects and Compositing",
    audioFile: "07-visual-effects-and-compositing.wav",
    actions: [
      // Ground still at core from scene 6
      { at: 2, action: (ctx) => ctx.studio.selectPreset("ghost"), label: "Ghost preset" },
      { at: 8, action: (ctx) => ctx.studio.selectPreset("trails"), label: "Trails preset" },
      { at: 14, action: (ctx) => ctx.studio.selectPreset("screwed"), label: "Screwed preset" },
      { at: 20, action: (ctx) => ctx.studio.selectPreset("datamosh"), label: "Datamosh preset" },
      { at: 25, action: (ctx) => ctx.studio.selectPreset("vhs"), label: "VHS preset" },
      { at: 30, action: (ctx) => ctx.studio.selectPreset("neon"), label: "Neon preset" },
      { at: 36, action: (ctx) => ctx.studio.selectPreset("nightvision"), label: "NightVision preset" },
      { at: 42, action: (ctx) => ctx.studio.selectPreset("thermal"), label: "Thermal IR preset" },
      { at: 50, action: (ctx) => ctx.studio.selectPreset("clean"), label: "Clean preset" },
    ],
  },

  // ── 8: Stimmung (85.2s) ──────────────────────────────────────────────
  {
    title: "Stimmung — System Self-Awareness",
    audioFile: "08-stimmung-system-self-awareness.wav",
    actions: [
      // Hold ground at core — stimmung borders visible on all regions
      // Narration explains the 10 dimensions and stance derivation
    ],
  },

  // ── 9: Watershed & Bedrock (53.5s) ───────────────────────────────────
  {
    title: "Watershed and Bedrock",
    audioFile: "09-watershed-and-bedrock.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        resetAllToSurface(ctx);
        ctx.terrain.setRegionDepth("watershed", "stratum");
      }, label: "Reset + watershed stratum" },
      { at: 5, action: (ctx) => ctx.terrain.setRegionDepth("watershed", "core"), label: "Watershed core — flow topology" },
      // "profile panel here shows the operator profile" — watershed core includes profile
    ],
  },

  // ── 10: Bedrock (69.3s) ──────────────────────────────────────────────
  {
    title: "Bedrock — Infrastructure and Governance",
    audioFile: "10-bedrock-infrastructure-and-governance.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        resetAllToSurface(ctx);
        ctx.terrain.setRegionDepth("bedrock", "stratum");
      }, label: "Reset + bedrock stratum" },
      { at: 5, action: (ctx) => ctx.terrain.setRegionDepth("bedrock", "core"), label: "Bedrock core — all panels" },
      // Narration walks through health, VRAM, containers, cost, consent, governance
    ],
  },

  // ── 11: Investigation Overlay (40.5s) ────────────────────────────────
  {
    title: "Investigation Overlay",
    audioFile: "11-investigation-overlay.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        resetAllToSurface(ctx);
      }, label: "Reset" },
      { at: 2, action: (ctx) => {
        ctx.terrain.setOverlay("investigation");
        ctx.terrain.setInvestigationTab("chat");
      }, label: "Open investigation — chat" },
      { at: 12, action: (ctx) => ctx.terrain.setInvestigationTab("insight"), label: "Switch to insight" },
      { at: 22, action: (ctx) => ctx.terrain.setInvestigationTab("demos"), label: "Switch to demos" },
      { at: 32, action: (ctx) => ctx.terrain.setOverlay(null), label: "Close overlay" },
    ],
  },

  // ── 12: Constitutional Governance (100.3s) ───────────────────────────
  {
    title: "Constitutional Governance",
    audioFile: "12-constitutional-governance.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        ctx.terrain.setRegionDepth("bedrock", "core");
      }, label: "Bedrock core — governance panels visible" },
      // Hold — narration explains 5 axioms, enforcement tiers
    ],
  },

  // ── 13: Ethics (106.5s) ──────────────────────────────────────────────
  {
    title: "Ethics of Continuous Perception",
    audioFile: "13-ethics-of-continuous-perception.wav",
    actions: [
      // HOLD bedrock core — consent panel visible during ethics discussion
    ],
  },

  // ── 14: Voice & Grounding (94.9s) ────────────────────────────────────
  {
    title: "Voice and Conversational Grounding",
    audioFile: "14-voice-and-conversational-grounding.wav",
    actions: [
      { at: 0.5, action: (ctx) => {
        resetAllToSurface(ctx);
      }, label: "Reset — ambient canvas for conceptual narration" },
      // Hold ambient — Clark & Brennan theory
    ],
  },

  // ── 15: Why No One Implemented Clark (94.6s) ─────────────────────────
  {
    title: "Why No One Implemented Clark",
    audioFile: "15-why-no-one-implemented-clark.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 16: The Bands System (82.6s) ─────────────────────────────────────
  {
    title: "The Bands System",
    audioFile: "16-the-bands-system.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 17: The Grounding Loop (98.8s) ───────────────────────────────────
  {
    title: "The Grounding Loop",
    audioFile: "17-the-grounding-loop.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 18: Salience Routing (93.5s) ─────────────────────────────────────
  {
    title: "Salience-Based Model Routing",
    audioFile: "18-salience-based-model-routing.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 19: Research — Done (91.3s) ──────────────────────────────────────
  {
    title: "Research — What Has Been Done",
    audioFile: "19-research-what-has-been-done.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 20: Research — Methodology (76.7s) ───────────────────────────────
  {
    title: "Research — Methodology and Threats",
    audioFile: "20-research-methodology-and-threats.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 21: Research — Remains (103.3s) ──────────────────────────────────
  {
    title: "Research — What Remains",
    audioFile: "21-research-what-remains.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 22: Research — Significance (78.3s) ──────────────────────────────
  {
    title: "Research — Significance and Originality",
    audioFile: "22-research-significance-and-originality.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 23: Temporal — Husserl (95.8s) ───────────────────────────────────
  {
    title: "Temporal Experience — Husserl's Model",
    audioFile: "23-temporal-experience-husserls-model.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 24: Philosophical Foundations (101.5s) ────────────────────────────
  {
    title: "Philosophical Foundations",
    audioFile: "24-philosophical-foundations.wav",
    actions: [
      // HOLD ambient
    ],
  },

  // ── 25: What Is Proven (85.0s) ───────────────────────────────────────
  {
    title: "What Is Proven, What Remains",
    audioFile: "25-what-is-proven-what-remains.wav",
    actions: [
      // Show field stratum for agent grid context
      { at: 2, action: (ctx) => ctx.terrain.setRegionDepth("field", "stratum"), label: "Field stratum — agent view" },
    ],
  },

  // ── 26: Closing (45.9s) ──────────────────────────────────────────────
  {
    title: "Closing",
    audioFile: "26-closing.wav",
    actions: [
      { at: 0.5, action: (ctx) => resetAllToSurface(ctx), label: "Reset to ambient for closing" },
    ],
  },

  // ── 27: Outro (2.5s) ─────────────────────────────────────────────────
  {
    title: "Thank You",
    audioFile: "99-outro.wav",
    actions: [],
  },
];
