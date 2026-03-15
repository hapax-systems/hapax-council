/** Composite visual presets for studio camera feeds. */

export interface CompositePreset {
  name: string;
  description: string;
  trail: {
    blendMode: string;
    opacity: number;
    filter: string;
    count: number;
    intervalMs: number;
  };
  liveFilter: string;
  overlays: OverlayType[];
  cellAnimation?: string;
}

export type OverlayType = "scanlines" | "rgbsplit" | "vignette" | "huecycle" | "noise";

export const PRESETS: CompositePreset[] = [
  {
    name: "Ghost",
    description: "Transparent echo",
    trail: { blendMode: "screen", opacity: 0.35, filter: "none", count: 4, intervalMs: 1200 },
    liveFilter: "none",
    overlays: [],
  },
  {
    name: "Trails",
    description: "Bright motion trails",
    trail: { blendMode: "lighten", opacity: 0.5, filter: "none", count: 8, intervalMs: 600 },
    liveFilter: "none",
    overlays: [],
  },
  {
    name: "Screwed",
    description: "Purple haze, slow drift",
    trail: {
      blendMode: "screen", opacity: 0.4,
      filter: "sepia(0.4) hue-rotate(270deg) saturate(1.8) brightness(0.7)",
      count: 6, intervalMs: 1500,
    },
    liveFilter: "sepia(0.2) hue-rotate(260deg) saturate(1.3) brightness(0.85) contrast(1.1)",
    overlays: ["scanlines"],
    cellAnimation: "studio-drift",
  },
  {
    name: "Datamosh",
    description: "Glitch — RGB split + difference",
    trail: {
      blendMode: "difference", opacity: 0.9,
      filter: "saturate(2) contrast(1.3)",
      count: 3, intervalMs: 400,
    },
    liveFilter: "contrast(1.15) saturate(1.2)",
    overlays: ["rgbsplit"],
  },
  {
    name: "VHS",
    description: "Lo-fi tape — scan lines, jitter",
    trail: {
      blendMode: "screen", opacity: 0.2,
      filter: "blur(1px) brightness(1.3)",
      count: 2, intervalMs: 2000,
    },
    liveFilter: "contrast(1.35) saturate(1.4) brightness(1.05)",
    overlays: ["scanlines", "noise"],
    cellAnimation: "studio-vhs-jitter",
  },
  {
    name: "Neon",
    description: "Color-cycling glow",
    trail: {
      blendMode: "screen", opacity: 0.45,
      filter: "saturate(3) brightness(0.8)",
      count: 5, intervalMs: 800,
    },
    liveFilter: "contrast(1.2) saturate(1.5)",
    overlays: ["huecycle", "vignette"],
  },
  {
    name: "Trap",
    description: "Dark, high-contrast",
    trail: {
      blendMode: "multiply", opacity: 0.6,
      filter: "sepia(0.5) hue-rotate(-20deg) saturate(2) brightness(0.5)",
      count: 4, intervalMs: 1000,
    },
    liveFilter: "contrast(1.4) saturate(0.7) brightness(0.85)",
    overlays: ["vignette"],
  },
  {
    name: "Diff",
    description: "Motion highlight",
    trail: {
      blendMode: "difference", opacity: 1.0,
      filter: "none", count: 1, intervalMs: 500,
    },
    liveFilter: "none",
    overlays: [],
  },
  {
    name: "Clean",
    description: "Subtle overlay + vignette",
    trail: {
      blendMode: "overlay", opacity: 0.25,
      filter: "none", count: 2, intervalMs: 2000,
    },
    liveFilter: "none",
    overlays: ["vignette"],
  },
];
