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
    description: "Transparent echo",
    colorFilter: "none",
    trail: {
      filter: "none",
      blendMode: "lighter",
      opacity: 0.3,
      count: 4,
      driftX: 0,
      driftY: 3,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
  {
    name: "Trails",
    description: "Bright motion trails",
    colorFilter: "none",
    trail: {
      filter: "none",
      blendMode: "lighter",
      opacity: 0.4,
      count: 6,
      driftX: 1,
      driftY: 2,
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
    description: "Glitch — RGB split + difference",
    colorFilter: "contrast(1.15) saturate(1.2)",
    trail: {
      filter: "none",
      blendMode: "difference",
      opacity: 0.9,
      count: 12,
      driftX: 2,
      driftY: 0,
    },
    effects: {
      ...NO_EFFECTS,
      bandDisplacement: true,
      bandChance: 0.25,
      bandMaxShift: 20,
    },
    overlays: [],
  },
  {
    name: "VHS",
    description: "Lo-fi tape — scan lines, jitter",
    colorFilter: "contrast(1.35) saturate(1.4) brightness(1.05)",
    trail: {
      filter: "none",
      blendMode: "lighter",
      opacity: 0.15,
      count: 2,
      driftX: 0,
      driftY: 1,
    },
    effects: {
      ...NO_EFFECTS,
      scanlines: true,
      bandDisplacement: true,
      bandChance: 0.15,
      bandMaxShift: 10,
      vignette: true,
      vignetteStrength: 0.3,
    },
    overlays: [],
  },
  {
    name: "Neon",
    description: "Color-cycling glow",
    colorFilter: "contrast(1.2) saturate(1.5)",
    trail: {
      filter: "saturate(3) brightness(0.8)",
      blendMode: "lighter",
      opacity: 0.35,
      count: 4,
      driftX: 0,
      driftY: 2,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
  {
    name: "Trap",
    description: "Dark, high-contrast",
    colorFilter: "contrast(1.4) saturate(0.7) brightness(0.85)",
    trail: {
      filter: "sepia(0.5) hue-rotate(-20deg) saturate(2) brightness(0.5)",
      blendMode: "multiply",
      opacity: 0.5,
      count: 3,
      driftX: 0,
      driftY: 3,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.5 },
    overlays: [],
  },
  {
    name: "Diff",
    description: "Motion highlight",
    colorFilter: "none",
    trail: {
      filter: "none",
      blendMode: "difference",
      opacity: 0.7,
      count: 3,
      driftX: 0,
      driftY: 0,
    },
    effects: { ...NO_EFFECTS },
    overlays: [],
  },
  {
    name: "Clean",
    description: "Subtle overlay + vignette",
    colorFilter: "none",
    trail: {
      filter: "none",
      blendMode: "source-over",
      opacity: 0.2,
      count: 2,
      driftX: 0,
      driftY: 1,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.15 },
    overlays: [],
  },
];
