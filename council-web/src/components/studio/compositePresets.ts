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
    colorFilter: "saturate(0.4) sepia(0.2) hue-rotate(180deg) brightness(0.95)",
    trail: {
      filter: "saturate(0.3) sepia(0.3) hue-rotate(180deg) brightness(1.4)",
      blendMode: "lighter",
      opacity: 0.55,
      count: 5,
      driftX: 12,
      driftY: 18,
    },
    overlay: {
      delayFrames: 10,
      filter: "saturate(0.2) sepia(0.3) hue-rotate(200deg) brightness(1.6)",
      alpha: 0.35,
      blendMode: "lighter",
      driftY: 12,
    },
    warp: {
      panX: 6,
      panY: 4,
      rotate: 0.008,
      zoom: 1.02,
      zoomBreath: 0.008,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.4 },
    overlays: [],
  },
  {
    name: "Trails",
    description: "Bright motion trails",
    colorFilter: "saturate(0.5) sepia(0.15) hue-rotate(30deg) brightness(1.05)",
    trail: {
      filter: "saturate(0.6) sepia(0.2) hue-rotate(60deg) brightness(1.5)",
      blendMode: "lighter",
      opacity: 0.6,
      count: 8,
      driftX: 8,
      driftY: 10,
    },
    overlay: {
      delayFrames: 5,
      filter: "saturate(0.5) sepia(0.3) hue-rotate(90deg) brightness(1.8)",
      alpha: 0.3,
      blendMode: "lighter",
      driftY: 6,
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
    description: "Glitch — RGB split + difference",
    colorFilter: "saturate(0.5) contrast(1.5) hue-rotate(40deg) brightness(1.1)",
    trail: {
      filter: "saturate(0.6) contrast(1.6) hue-rotate(90deg) brightness(1.3)",
      blendMode: "difference",
      opacity: 0.9,
      count: 7,
      driftX: 6,
      driftY: 5,
    },
    overlay: {
      delayFrames: 6,
      filter: "saturate(0.4) hue-rotate(180deg) contrast(1.8) brightness(1.4)",
      alpha: 0.55,
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
      bandChance: 0.45,
      bandMaxShift: 35,
      scanlines: true,
    },
    overlays: [],
  },
  {
    name: "VHS",
    description: "Lo-fi tape — scan lines, jitter",
    colorFilter:
      "saturate(0.35) sepia(0.5) hue-rotate(-10deg) contrast(1.3) brightness(1.15) blur(0.5px)",
    trail: {
      filter: "saturate(0.3) sepia(0.6) blur(2px) brightness(1.1)",
      blendMode: "lighter",
      opacity: 0.3,
      count: 3,
      driftX: 2,
      driftY: 3,
    },
    overlay: {
      delayFrames: 8,
      filter: "saturate(0.3) sepia(0.5) blur(1.5px) brightness(1.3)",
      alpha: 0.2,
      blendMode: "lighter",
      driftY: 4,
    },
    warp: {
      panX: 2,
      panY: 1,
      rotate: 0.003,
      zoom: 1.02,
      zoomBreath: 0.005,
      sliceCount: 12,
      sliceAmplitude: 3,
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
      bandChance: 0.25,
      bandMaxShift: 18,
      vignette: true,
      vignetteStrength: 0.45,
    },
    overlays: [],
  },
  {
    name: "Neon",
    description: "Color-cycling glow",
    colorFilter: "saturate(0.3) sepia(0.2) contrast(1.4) brightness(1.2)",
    trail: {
      filter: "saturate(0.4) sepia(0.1) contrast(1.3) brightness(1.6)",
      blendMode: "lighter",
      opacity: 0.5,
      count: 6,
      driftX: 4,
      driftY: 5,
    },
    overlay: {
      delayFrames: 5,
      filter: "saturate(0.5) contrast(1.5) brightness(1.5)",
      alpha: 0.35,
      blendMode: "lighter",
      driftY: 3,
    },
    warp: {
      panX: 5,
      panY: 4,
      rotate: 0.01,
      zoom: 1.03,
      zoomBreath: 0.015,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.3 },
    overlays: [],
  },
  {
    name: "Trap",
    description: "Dark, underground, oppressive",
    colorFilter:
      "saturate(0.2) sepia(0.5) hue-rotate(160deg) contrast(1.6) brightness(0.55)",
    trail: {
      filter: "saturate(0.15) sepia(0.6) hue-rotate(180deg) brightness(0.3)",
      blendMode: "multiply",
      opacity: 0.7,
      count: 4,
      driftX: 1,
      driftY: 5,
    },
    overlay: {
      delayFrames: 10,
      filter: "saturate(0.3) sepia(0.4) hue-rotate(200deg) brightness(0.6)",
      alpha: 0.25,
      blendMode: "multiply",
      driftY: 3,
    },
    warp: {
      panX: 2,
      panY: 1,
      rotate: 0.003,
      zoom: 1.01,
      zoomBreath: 0.005,
      sliceCount: 0,
      sliceAmplitude: 0,
    },
    effects: {
      ...NO_EFFECTS,
      vignette: true,
      vignetteStrength: 0.7,
      bandDisplacement: true,
      bandChance: 0.08,
      bandMaxShift: 8,
      syrupGradient: true,
      syrupColor: "0, 10, 20",
    },
    overlays: [],
  },
  {
    name: "Diff",
    description: "Motion detection — movement glows",
    colorFilter: "saturate(0) contrast(1.3) brightness(0.9)",
    trail: {
      filter: "saturate(0) contrast(1.8) brightness(1.5)",
      blendMode: "difference",
      opacity: 0.95,
      count: 2,
      driftX: 0,
      driftY: 0,
    },
    overlay: {
      delayFrames: 3,
      filter: "saturate(0) contrast(2) brightness(1.2)",
      alpha: 0.85,
      blendMode: "difference",
      driftY: 0,
    },
    effects: { ...NO_EFFECTS, vignette: true, vignetteStrength: 0.2 },
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
