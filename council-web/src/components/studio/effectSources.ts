/** Available sources for live/smooth layer selection. */

export interface EffectSource {
  id: string;
  label: string;
}

export const EFFECT_SOURCES: EffectSource[] = [
  { id: "camera", label: "Camera" },
  { id: "fx-clean", label: "Clean" },
  { id: "fx-ghost", label: "Ghost" },
  { id: "fx-datamosh", label: "Datamosh" },
  { id: "fx-vhs", label: "VHS" },
  { id: "fx-neon", label: "Neon" },
  { id: "fx-screwed", label: "Screwed" },
  { id: "fx-trap", label: "Trap" },
  { id: "fx-diff", label: "Diff" },
  { id: "fx-pixsort", label: "Pixsort" },
  { id: "fx-slitscan", label: "Slit-scan" },
  { id: "fx-thermal", label: "Thermal" },
  { id: "fx-feedback", label: "Feedback" },
  { id: "fx-halftone", label: "Halftone" },
  { id: "fx-glitchblocks", label: "Glitch" },
  { id: "fx-ascii", label: "ASCII" },
];

/** Convert source ID to fetch URL. "camera" returns undefined (use default). */
export function sourceUrl(id: string, _role: string): string | undefined {
  if (id === "camera") return undefined;
  return `/api/studio/stream/live/${id}`;
}
