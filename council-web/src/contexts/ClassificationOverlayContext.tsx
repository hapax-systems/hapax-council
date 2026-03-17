import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { usePerception, useVisualLayer } from "../api/hooks";
import type { PerceptionState, VisualLayerState, SignalEntry } from "../api/types";

export type OverlayMode = "off" | "minimal" | "full";

export type SignalCategory =
  | "context_time"
  | "governance"
  | "work_tasks"
  | "health_infra"
  | "profile_state"
  | "ambient_sensor";

export const SIGNAL_CATEGORIES: SignalCategory[] = [
  "context_time",
  "governance",
  "work_tasks",
  "health_infra",
  "profile_state",
  "ambient_sensor",
];

// Category text colors — high saturation for overlay legibility
export const CATEGORY_COLORS: Record<SignalCategory, string> = {
  context_time: "text-sky-400",
  governance: "text-violet-400",
  work_tasks: "text-amber-400",
  health_infra: "text-rose-400",
  profile_state: "text-emerald-400",
  ambient_sensor: "text-teal-400",
};

// Category background pills
export const CATEGORY_BG: Record<SignalCategory, string> = {
  context_time: "bg-sky-500",
  governance: "bg-violet-500",
  work_tasks: "bg-amber-500",
  health_infra: "bg-rose-500",
  profile_state: "bg-emerald-500",
  ambient_sensor: "bg-teal-500",
};

// Tinted zone backgrounds — semi-transparent with category hue
export const CATEGORY_ZONE_BG: Record<SignalCategory, string> = {
  context_time: "bg-sky-950/70",
  governance: "bg-violet-950/70",
  work_tasks: "bg-amber-950/70",
  health_infra: "bg-rose-950/70",
  profile_state: "bg-emerald-950/70",
  ambient_sensor: "bg-teal-950/70",
};

// Zone border accent (left edge glow)
export const CATEGORY_BORDER: Record<SignalCategory, string> = {
  context_time: "border-l-sky-500/60",
  governance: "border-l-violet-500/60",
  work_tasks: "border-l-amber-500/60",
  health_infra: "border-l-rose-500/60",
  profile_state: "border-l-emerald-500/60",
  ambient_sensor: "border-l-teal-500/60",
};

export const CATEGORY_LABELS: Record<SignalCategory, string> = {
  context_time: "Context",
  governance: "Governance",
  work_tasks: "Tasks",
  health_infra: "Health",
  profile_state: "Operator",
  ambient_sensor: "Environment",
};

const STORAGE_KEY = "perception-overlay-v2";

function loadVisibility(): Record<SignalCategory, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return Object.fromEntries(SIGNAL_CATEGORIES.map((c) => [c, true])) as Record<SignalCategory, boolean>;
}

function loadMode(): OverlayMode {
  try {
    const raw = localStorage.getItem(`${STORAGE_KEY}-mode`);
    if (raw === "off" || raw === "minimal" || raw === "full") return raw;
  } catch { /* ignore */ }
  return "full";
}

interface OverlayContextValue {
  perception: PerceptionState | undefined;
  visualLayer: VisualLayerState | undefined;
  overlayMode: OverlayMode;
  setOverlayMode: (mode: OverlayMode) => void;
  channelVisibility: Record<SignalCategory, boolean>;
  toggleChannel: (cat: SignalCategory) => void;
  filteredSignals: Record<string, SignalEntry[]>;
  zoneOpacityOverrides: Record<string, number>;
  setZoneOpacity: (zone: string, opacity: number) => void;
}

const OverlayContext = createContext<OverlayContextValue | null>(null);

export function ClassificationOverlayProvider({ children }: { children: ReactNode }) {
  const { data: perception } = usePerception();
  const { data: visualLayer } = useVisualLayer();
  const [channelVisibility, setChannelVisibility] = useState(loadVisibility);
  const [overlayMode, setOverlayModeState] = useState(loadMode);
  const [zoneOpacityOverrides, setZoneOpacityOverrides] = useState<Record<string, number>>({});

  const setOverlayMode = useCallback((mode: OverlayMode) => {
    setOverlayModeState(mode);
    localStorage.setItem(`${STORAGE_KEY}-mode`, mode);
  }, []);

  const toggleChannel = useCallback((cat: SignalCategory) => {
    setChannelVisibility((prev) => {
      const next = { ...prev, [cat]: !prev[cat] };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const setZoneOpacity = useCallback((zone: string, opacity: number) => {
    setZoneOpacityOverrides((prev) => ({ ...prev, [zone]: opacity }));
  }, []);

  const filteredSignals = useMemo(() => {
    const signals = visualLayer?.signals ?? {};
    const result: Record<string, SignalEntry[]> = {};
    for (const cat of SIGNAL_CATEGORIES) {
      if (channelVisibility[cat] && signals[cat]) {
        result[cat] = signals[cat];
      }
    }
    return result;
  }, [visualLayer?.signals, channelVisibility]);

  const value = useMemo(
    () => ({
      perception,
      visualLayer,
      overlayMode,
      setOverlayMode,
      channelVisibility,
      toggleChannel,
      filteredSignals,
      zoneOpacityOverrides,
      setZoneOpacity,
    }),
    [perception, visualLayer, overlayMode, setOverlayMode, channelVisibility, toggleChannel, filteredSignals, zoneOpacityOverrides, setZoneOpacity],
  );

  return <OverlayContext.Provider value={value}>{children}</OverlayContext.Provider>;
}

export function useOverlay(): OverlayContextValue {
  const ctx = useContext(OverlayContext);
  if (!ctx) throw new Error("useOverlay must be used within ClassificationOverlayProvider");
  return ctx;
}
