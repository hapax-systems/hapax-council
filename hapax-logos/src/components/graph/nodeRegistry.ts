/**
 * Shader node type registry — loads manifests from the backend
 * and provides typed definitions for the node palette and param editor.
 */

export interface ParamDef {
  type: "float" | "int" | "enum" | "bool";
  default: number | string | boolean;
  min?: number;
  max?: number;
  enum_values?: string[];
  description?: string;
}

export interface NodeTypeDef {
  node_type: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  params: Record<string, ParamDef>;
  temporal: boolean;
  temporal_buffers: number;
}

/** 10 aesthetic categories from the spec. */
export const AESTHETIC_CATEGORIES = [
  {
    id: "minimal",
    label: "Minimal / Transparent",
    types: ["colorgrade", "vignette", "postprocess"],
  },
  {
    id: "temporal",
    label: "Temporal Persistence / Feedback",
    types: ["trail", "feedback", "echo", "diff"],
  },
  {
    id: "analog",
    label: "Analog Degradation",
    types: ["vhs", "dither", "scanlines", "noise_gen"],
  },
  {
    id: "glitch",
    label: "Databending / Glitch",
    types: ["glitch_block", "pixsort", "chromatic_aberration", "displacement_map"],
  },
  {
    id: "syrup",
    label: "Houston Syrup / Temporal",
    types: ["stutter", "syrup", "warp", "transform"],
  },
  {
    id: "spectral",
    label: "False Color / Spectral",
    types: ["thermal", "color_map", "posterize", "invert"],
  },
  {
    id: "edge",
    label: "Edge / Silhouette / Relief",
    types: ["edge_detect", "emboss", "sharpen", "threshold"],
  },
  {
    id: "mosaic",
    label: "Halftone / Mosaic / Character",
    types: ["halftone", "ascii", "tile"],
  },
  {
    id: "geometric",
    label: "Geometric Distortion / Symmetry",
    types: ["mirror", "kaleidoscope", "fisheye", "droste", "tunnel"],
  },
  {
    id: "reactive",
    label: "Biometric / Reactive",
    types: ["slitscan", "strobe", "breathing", "bloom"],
  },
] as const;

/** All available modulation signal sources. */
export const MODULATION_SIGNALS = [
  { id: "audio_rms", label: "Audio Energy", group: "audio" },
  { id: "audio_beat", label: "Beat", group: "audio" },
  { id: "mixer_energy", label: "Mixer Energy", group: "audio" },
  { id: "mixer_beat", label: "Mixer Beat", group: "audio" },
  { id: "mixer_bass", label: "Bass", group: "audio" },
  { id: "mixer_mid", label: "Mid", group: "audio" },
  { id: "mixer_high", label: "High", group: "audio" },
  { id: "desk_energy", label: "Desk Energy", group: "audio" },
  { id: "desk_onset_rate", label: "Onset Rate", group: "audio" },
  { id: "desk_centroid", label: "Spectral Centroid", group: "audio" },
  { id: "time", label: "Time", group: "temporal" },
  { id: "beat_phase", label: "Beat Phase", group: "temporal" },
  { id: "bar_phase", label: "Bar Phase", group: "temporal" },
  { id: "beat_pulse", label: "Beat Pulse", group: "temporal" },
  { id: "heart_rate", label: "Heart Rate", group: "biometric" },
  { id: "stress", label: "Stress", group: "biometric" },
  { id: "flow_score", label: "Flow Score", group: "perception" },
  { id: "stimmung_valence", label: "Valence", group: "perception" },
  { id: "stimmung_arousal", label: "Arousal", group: "perception" },
  { id: "perlin_drift", label: "Perlin Drift", group: "computed" },
] as const;

export type ModulationSignalId = (typeof MODULATION_SIGNALS)[number]["id"];

export interface ModulationBinding {
  source: ModulationSignalId | "";
  scale: number;
  offset: number;
  smoothing: number;
}

/** Categorize a node type into an aesthetic category. */
export function categoryForType(nodeType: string): string {
  for (const cat of AESTHETIC_CATEGORIES) {
    if ((cat.types as readonly string[]).includes(nodeType)) return cat.id;
  }
  return "minimal"; // fallback
}
