/** Available sources for live/smooth layer selection. */
import { api } from "../../api/client";

export interface EffectSource {
  id: string;
  label: string;
}

export const EFFECT_SOURCES: EffectSource[] = [
  { id: "camera", label: "Camera" },
  { id: "fx-clean", label: "Clean" },
  { id: "fx-ghost", label: "Ghost" },
  { id: "fx-trails", label: "Trails" },
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
  { id: "fx-nightvision", label: "Night Vision" },
  { id: "fx-silhouette", label: "Silhouette" },
  { id: "fx-ambient", label: "Ambient" },
];

/** Convert source ID to fetch URL. "camera" returns undefined (use default). */
/** All non-camera sources read from the single FX snapshot endpoint.
 *  The compositor is told which effect to render via POST /api/studio/effect/select.
 */
export function sourceUrl(id: string): string | undefined {
  if (id === "camera") return undefined;
  return "/api/studio/stream/fx";
}

/** Map frontend source IDs to backend preset names.
 *  Most strip the 'fx-' prefix directly. CSS-only presets (nightvision)
 *  route to 'clean' since their visual character comes from the composite preset's
 *  colorFilter, not from a GPU shader. Silhouette has a dedicated backend preset.
 */
const BACKEND_PRESET_MAP: Record<string, string> = {
  "fx-nightvision": "clean",
  "fx-silhouette": "silhouette",
};

/** Tell the compositor to switch to a different effect preset.
 *  Strip the 'fx-' prefix since the backend uses bare names (e.g. 'vhs' not 'fx-vhs').
 */
export async function selectEffect(id: string): Promise<void> {
  if (id === "camera") return;
  const name = BACKEND_PRESET_MAP[id] ?? (id.startsWith("fx-") ? id.slice(3) : id);
  await api.post("/studio/effect/select", { preset: name }).catch(() => {});
}
