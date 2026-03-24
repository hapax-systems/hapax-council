/**
 * InspectorChannelPanel — right-side channel toggles for classification inspector.
 *
 * 12 classification channels, each with a theme-aware color dot, toggle switch,
 * label, and current value. Confidence threshold slider at bottom.
 * All state persisted to localStorage.
 */

import { useCallback, useEffect, useState } from "react";
import { useTheme } from "../../../theme/ThemeProvider";

/** Classification channel definition. */
export interface Channel {
  id: string;
  label: string;
  colorToken: string;
  group: "enrichment" | "per-camera" | "temporal";
}

export const CHANNELS: Channel[] = [
  { id: "detections", label: "Detections (YOLO)", colorToken: "green-400", group: "enrichment" },
  { id: "gaze", label: "Gaze direction", colorToken: "blue-400", group: "enrichment" },
  { id: "emotion", label: "Emotion", colorToken: "yellow-400", group: "enrichment" },
  { id: "posture", label: "Posture", colorToken: "orange-400", group: "enrichment" },
  { id: "gesture", label: "Gesture", colorToken: "fuchsia-400", group: "enrichment" },
  { id: "scene", label: "Scene type", colorToken: "emerald-400", group: "enrichment" },
  { id: "action", label: "Action", colorToken: "red-400", group: "enrichment" },
  { id: "motion", label: "Motion", colorToken: "orange-600", group: "per-camera" },
  { id: "depth", label: "Depth", colorToken: "blue-600", group: "per-camera" },
  { id: "trajectory", label: "Trajectory", colorToken: "green-600", group: "temporal" },
  { id: "novelty", label: "Novelty", colorToken: "yellow-600", group: "temporal" },
  { id: "dwell", label: "Dwell", colorToken: "fuchsia-600", group: "temporal" },
];

const STORAGE_KEY = "hapax-classification-inspector";

interface InspectorState {
  enabled: Record<string, boolean>;
  threshold: number;
}

function loadState(): InspectorState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore
  }
  return {
    enabled: Object.fromEntries(CHANNELS.map((c) => [c.id, true])),
    threshold: 0.3,
  };
}

interface Props {
  onStateChange: (state: InspectorState) => void;
}

export function InspectorChannelPanel({ onStateChange }: Props) {
  const { palette } = useTheme();
  const [state, setState] = useState<InspectorState>(loadState);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    onStateChange(state);
  }, [state, onStateChange]);

  const toggle = useCallback(
    (id: string) => {
      setState((prev) => ({
        ...prev,
        enabled: { ...prev.enabled, [id]: !prev.enabled[id] },
      }));
    },
    [],
  );

  const setThreshold = useCallback((v: number) => {
    setState((prev) => ({ ...prev, threshold: v }));
  }, []);

  const groups = ["enrichment", "per-camera", "temporal"] as const;
  const groupLabels: Record<string, string> = {
    enrichment: "Classification",
    "per-camera": "Per-Camera",
    temporal: "Temporal",
  };

  return (
    <div className="flex flex-col gap-3 p-3 text-xs font-mono overflow-y-auto h-full">
      {groups.map((group) => (
        <div key={group}>
          <div className="text-zinc-500 uppercase tracking-widest text-[10px] mb-1.5">
            {groupLabels[group]}
          </div>
          {CHANNELS.filter((c) => c.group === group).map((ch) => (
            <button
              key={ch.id}
              onClick={() => toggle(ch.id)}
              className="flex items-center gap-2 w-full py-1 px-1.5 rounded hover:bg-zinc-800/50 transition-colors"
            >
              <span
                className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                style={{
                  backgroundColor: palette[ch.colorToken] ?? "var(--color-zinc-500)",
                  opacity: state.enabled[ch.id] ? 1.0 : 0.2,
                }}
              />
              <span
                className="truncate"
                style={{
                  color: state.enabled[ch.id]
                    ? "var(--color-zinc-200)"
                    : "var(--color-zinc-600)",
                }}
              >
                {ch.label}
              </span>
            </button>
          ))}
        </div>
      ))}

      {/* Confidence threshold slider */}
      <div className="mt-2 pt-2" style={{ borderTop: "1px solid var(--color-zinc-800)" }}>
        <div className="text-zinc-500 uppercase tracking-widest text-[10px] mb-1.5">
          Confidence threshold
        </div>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(state.threshold * 100)}
            onChange={(e) => setThreshold(Number(e.target.value) / 100)}
            className="flex-1"
            style={{ accentColor: palette["emerald-400"] }}
          />
          <span className="text-zinc-400 w-8 text-right">{state.threshold.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}
