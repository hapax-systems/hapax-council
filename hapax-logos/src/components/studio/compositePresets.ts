/** Composite visual presets for studio camera feeds. */

export type OverlayType =
  | "scanlines"
  | "rgbsplit"
  | "vignette"
  | "huecycle"
  | "noise"
  | "screwed";

export interface CompositePreset {
  name: string;
  description: string;

  colorFilter: string; // ctx.filter for main frame

  trail: {
    filter: string; // ctx.filter for ghost frames
    blendMode: string; // globalCompositeOperation
    opacity: number; // base opacity (fades with age)
    count: number; // number of ghost frames
    driftX: number; // px per layer horizontal
    driftY: number; // px per layer vertical
  };

  overlay?: {
    delayFrames: number;
    filter: string;
    alpha: number;
    blendMode: string;
    driftY: number;
  };

  warp?: {
    panX: number;
    panY: number;
    rotate: number;
    zoom: number;
    zoomBreath: number;
    sliceCount: number; // 0 = no slicing, >0 = horizontal slice warp
    sliceAmplitude: number;
  };

  stutter?: {
    checkInterval: number;
    freezeChance: number;
    freezeMin: number;
    freezeMax: number;
    replayFrames: number;
  };

  effects: {
    scanlines: boolean;
    bandDisplacement: boolean;
    bandChance: number;
    bandMaxShift: number;
    vignette: boolean;
    vignetteStrength: number;
    syrupGradient: boolean;
    syrupColor: string; // e.g. "60, 20, 80"
  };

  overlays: OverlayType[]; // CSS overlays (kept for non-canvas elements if needed)
  cellAnimation?: string;
  livePullIntervalMs?: number;
}

const NO_EFFECTS: CompositePreset["effects"] = {
  scanlines: false,
  bandDisplacement: false,
  bandChance: 0,
  bandMaxShift: 0,
  vignette: false,
  vignetteStrength: 0,
  syrupGradient: false,
  syrupColor: "0, 0, 0",
};

export const PRESETS: CompositePreset[] = [
  {
    name: "Ghost",
    description: "Transparent echo — fading dim copies",
    colorFilter: "saturate(0.85) brightness(0.9)",
    trail: {
      filter: "saturate(0.7) brightness(0.6)",
      blendMode: "source-over",
      opacity: 0.4,
      count: 4,
      driftX: 18,
      driftY: 24,
    },
    overlay: {
      delayFrames: 12,
      filter: "saturate(0.5) brightness(0.5)",
      alpha: 0.15,
      blendMode: "source-over",
      driftY: 16,
    },
    warp: {
      panX: 4,
      panY: 3,
      rotate: 0.005,
      zoom: 1.01,
      zoomBreath: 0.005,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.35 },
    overlays: [],
  },
  {
    name: "Trails",
    description: "Bright additive motion trails",
    colorFilter: "saturate(0.7) sepia(0.1) hue-rotate(20deg) brightness(1.15)",
    trail: {
      filter: "saturate(0.9) sepia(0.1) hue-rotate(30deg) brightness(1.2)",
      blendMode: "lighter",
      opacity: 0.7,
      count: 10,
      driftX: 2,
      driftY: 3,
    },
    overlay: {
      delayFrames: 4,
      filter: "saturate(0.7) sepia(0.2) hue-rotate(60deg) brightness(1.2)",
      alpha: 0.2,
      blendMode: "lighter",
      driftY: 5,
    },
    warp: {
      panX: 3,
      panY: 2,
      rotate: 0.004,
      zoom: 1.01,
      zoomBreath: 0.005,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS },
    overlays: [],
  },
  {
    name: "Screwed",
    description: "Houston syrup — dim, heavy, sinking",
    colorFilter:
      "saturate(0.55) sepia(0.4) hue-rotate(250deg) contrast(1.05) brightness(0.9)",
    trail: {
      filter: "saturate(0.3) brightness(0.5) sepia(0.6) hue-rotate(250deg)",
      blendMode: "lighter",
      opacity: 0.2,
      count: 3,
      driftX: 0,
      driftY: 6,
    },
    overlay: {
      delayFrames: 10,
      filter:
        "saturate(0.4) sepia(0.6) hue-rotate(280deg) brightness(1.2)",
      alpha: 0.45,
      blendMode: "lighter",
      driftY: 8,
    },
    warp: {
      panX: 20,
      panY: 22, // 14 + 8
      rotate: 0.025,
      zoom: 1.06,
      zoomBreath: 0.04,
      sliceCount: 24,
      sliceAmplitude: 6,
    },
    stutter: {
      checkInterval: 10,
      freezeChance: 0.5,
      freezeMin: 3,
      freezeMax: 10,
      replayFrames: 3,
    },
    effects: {
      scanlines: true,
      bandDisplacement: true,
      bandChance: 0.18,
      bandMaxShift: 15,
      vignette: true,
      vignetteStrength: 0.3,
      syrupGradient: true,
      syrupColor: "60, 20, 80",
    },
    overlays: [],
    livePullIntervalMs: 180,
  },
  {
    name: "Datamosh",
    description: "Glitch — codec prediction artifacts",
    colorFilter: "saturate(0.6) contrast(1.8) hue-rotate(40deg) brightness(1.15)",
    trail: {
      filter: "saturate(0.8) contrast(2.2) hue-rotate(90deg) brightness(1.4)",
      blendMode: "difference",
      opacity: 0.95,
      count: 7,
      driftX: 8,
      driftY: 6,
    },
    overlay: {
      delayFrames: 6,
      filter: "saturate(0.6) hue-rotate(180deg) contrast(2.0) brightness(1.5)",
      alpha: 0.6,
      blendMode: "difference",
      driftY: 3,
    },
    stutter: {
      checkInterval: 8,
      freezeChance: 0.35,
      freezeMin: 2,
      freezeMax: 6,
      replayFrames: 3,
    },
    effects: {
      ...NO_EFFECTS,
      bandDisplacement: true,
      bandChance: 0.5,
      bandMaxShift: 40,
      scanlines: true,
    },
    overlays: [],
  },
  {
    name: "VHS",
    description: "Lo-fi tape — soft, warm, tracking noise",
    colorFilter:
      "saturate(0.4) sepia(0.55) hue-rotate(-10deg) contrast(1.25) brightness(1.1) blur(1.5px)",
    trail: {
      filter: "saturate(0.3) sepia(0.6) blur(3px) brightness(1.05)",
      blendMode: "lighter",
      opacity: 0.25,
      count: 3,
      driftX: 4,
      driftY: 2,
    },
    overlay: {
      delayFrames: 8,
      filter: "saturate(0.3) sepia(0.5) blur(2px) brightness(1.2)",
      alpha: 0.2,
      blendMode: "lighter",
      driftY: 3,
    },
    warp: {
      panX: 2,
      panY: 1,
      rotate: 0.002,
      zoom: 1.02,
      zoomBreath: 0.004,
      sliceCount: 10,
      sliceAmplitude: 2,
    },
    stutter: {
      checkInterval: 20,
      freezeChance: 0.15,
      freezeMin: 2,
      freezeMax: 5,
      replayFrames: 2,
    },
    effects: {
      ...NO_EFFECTS,
      scanlines: true,
      bandDisplacement: true,
      bandChance: 0.2,
      bandMaxShift: 12,
      vignette: true,
      vignetteStrength: 0.4,
    },
    overlays: [],
  },
  {
    name: "Neon",
    description: "Color-cycling glow bloom",
    colorFilter: "saturate(3.5) contrast(1.5) brightness(1.45)",
    trail: {
      filter: "saturate(4) contrast(1.3) brightness(1.9)",
      blendMode: "lighter",
      opacity: 0.6,
      count: 8,
      driftX: 3,
      driftY: 4,
    },
    overlay: {
      delayFrames: 4,
      filter: "saturate(4) contrast(1.4) brightness(2.2)",
      alpha: 0.45,
      blendMode: "lighter",
      driftY: 3,
    },
    warp: {
      panX: 4,
      panY: 3,
      rotate: 0.008,
      zoom: 1.02,
      zoomBreath: 0.012,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.5 },
    overlays: [],
  },
  {
    name: "Trap",
    description: "Dark, underground, oppressive",
    colorFilter:
      "saturate(0.2) sepia(0.4) hue-rotate(160deg) contrast(1.3) brightness(0.65)",
    trail: {
      filter: "saturate(0.15) sepia(0.5) hue-rotate(180deg) brightness(0.4)",
      blendMode: "multiply",
      opacity: 0.55,
      count: 4,
      driftX: 1,
      driftY: 4,
    },
    overlay: {
      delayFrames: 12,
      filter: "saturate(0.2) sepia(0.4) hue-rotate(200deg) brightness(0.5)",
      alpha: 0.25,
      blendMode: "multiply",
      driftY: 2,
    },
    warp: {
      panX: 1,
      panY: 1,
      rotate: 0.002,
      zoom: 1.005,
      zoomBreath: 0.003,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: {
      ...NO_EFFECTS,
      vignette: true,
      vignetteStrength: 0.55,
      syrupGradient: true,
      syrupColor: "10, 5, 15",
    },
    overlays: [],
  },
  {
    name: "Diff",
    description: "Motion detection — static=black, movement=white",
    colorFilter: "saturate(0) contrast(1.6) brightness(0.85)",
    trail: {
      filter: "saturate(0) contrast(2.5) brightness(1.6)",
      blendMode: "difference",
      opacity: 0.95,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    overlay: {
      delayFrames: 3,
      filter: "saturate(0) contrast(2.2) brightness(1.3)",
      alpha: 0.9,
      blendMode: "difference",
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.15 },
    overlays: [],
  },
  {
    name: "NightVision",
    description: "Green phosphor mono — IR-optimized surveillance",
    colorFilter: "saturate(0) brightness(1.3) contrast(1.4)",
    trail: {
      filter: "saturate(0) brightness(0.8)",
      blendMode: "source-over",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: {
      ...NO_EFFECTS,
      scanlines: true,
      vignette: true,
      vignetteStrength: 0.35,
      syrupGradient: true,
      syrupColor: "0, 60, 0",
    },
    overlays: [],
  },
  {
    name: "Silhouette",
    description: "High-contrast IR-only look — shapes over detail",
    colorFilter: "saturate(0) contrast(3.0) brightness(0.6)",
    trail: {
      filter: "saturate(0) contrast(2.0) brightness(0.4)",
      blendMode: "source-over",
      opacity: 0.1,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.4 },
    overlays: [],
  },
  {
    name: "Thermal IR",
    description: "Enhanced thermal with IR-optimized mono inversion",
    colorFilter:
      "saturate(0) contrast(1.8) brightness(1.1) invert(1) hue-rotate(180deg)",
    trail: {
      filter: "saturate(0) contrast(1.5) brightness(0.9) invert(1) hue-rotate(180deg)",
      blendMode: "source-over",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
  {
    name: "Pixsort",
    description: "Luminance-gated pixel sorting streaks",
    colorFilter: "saturate(1.2) contrast(1.3) brightness(1.05) sepia(0.15)",
    trail: {
      filter: "saturate(1.4) contrast(1.1) brightness(1.2) sepia(0.2)",
      blendMode: "lighter",
      opacity: 0.4,
      count: 4,
      driftX: 0,
      driftY: 5,
    },
    warp: {
      panX: 2,
      panY: 1,
      rotate: 0.003,
      zoom: 1.01,
      zoomBreath: 0.004,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
  {
    name: "Slit-scan",
    description: "Temporal vertical displacement smear",
    colorFilter: "saturate(0.8) contrast(1.2) brightness(1.0)",
    trail: {
      filter: "saturate(0.7) brightness(0.9)",
      blendMode: "source-over",
      opacity: 0.5,
      count: 6,
      driftX: 0,
      driftY: 8,
    },
    overlay: {
      delayFrames: 8,
      filter: "saturate(0.6) brightness(0.8)",
      alpha: 0.3,
      blendMode: "source-over",
      driftY: 12,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.25 },
    overlays: [],
  },
  {
    name: "Feedback",
    description: "Deep recursion — rainbow cycling glow",
    colorFilter: "saturate(3.0) contrast(1.4) brightness(1.3)",
    trail: {
      filter: "saturate(3.5) contrast(1.2) brightness(1.6)",
      blendMode: "lighter",
      opacity: 0.7,
      count: 12,
      driftX: 3,
      driftY: 4,
    },
    overlay: {
      delayFrames: 6,
      filter: "saturate(3.0) contrast(1.3) brightness(1.8)",
      alpha: 0.35,
      blendMode: "lighter",
      driftY: 4,
    },
    warp: {
      panX: 3,
      panY: 2,
      rotate: 0.006,
      zoom: 1.015,
      zoomBreath: 0.01,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.45 },
    overlays: [],
  },
  {
    name: "Halftone",
    description: "Print-dot grid — high saturation halftone",
    colorFilter: "saturate(1.8) contrast(1.4) brightness(1.1)",
    trail: {
      filter: "saturate(1.5) contrast(1.2) brightness(1.0)",
      blendMode: "source-over",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
  {
    name: "Glitch Blocks",
    description: "Digital block corruption — RGB split artifacts",
    colorFilter: "saturate(0.7) contrast(1.6) brightness(1.1) hue-rotate(20deg)",
    trail: {
      filter: "saturate(0.8) contrast(1.8) hue-rotate(60deg) brightness(1.3)",
      blendMode: "difference",
      opacity: 0.6,
      count: 5,
      driftX: 6,
      driftY: 4,
    },
    stutter: {
      checkInterval: 12,
      freezeChance: 0.3,
      freezeMin: 2,
      freezeMax: 8,
      replayFrames: 3,
    },
    effects: {
      ...NO_EFFECTS,
      bandDisplacement: true,
      bandChance: 0.4,
      bandMaxShift: 35,
      scanlines: true,
    },
    overlays: [],
  },
  {
    name: "ASCII",
    description: "Character grid — monochrome text art",
    colorFilter: "saturate(0) contrast(1.6) brightness(1.2)",
    trail: {
      filter: "saturate(0) contrast(1.3) brightness(0.9)",
      blendMode: "source-over",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.25, scanlines: true },
    overlays: [],
  },
  {
    name: "Ambient",
    description: "Very dim, minimal trails — atmospheric presence",
    colorFilter: "saturate(0.4) brightness(0.7) contrast(1.1)",
    trail: {
      filter: "saturate(0.3) brightness(0.5)",
      blendMode: "lighter",
      opacity: 0.12,
      count: 3,
      driftX: 0,
      driftY: 1,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.45 },
    overlays: [],
  },
  {
    name: "Clean",
    description: "Minimal processing — nearly invisible",
    colorFilter: "contrast(1.05) saturate(1.05)",
    trail: {
      filter: "none",
      blendMode: "source-over",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.12 },
    overlays: [],
  },
];
