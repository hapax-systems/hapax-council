import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { usePerception, useVisualLayer } from "../api/hooks";
import type { ClassificationDetection, PerceptionState, VisualLayerState, SignalEntry, StimmungStance } from "../api/types";
import type { DetectionTier } from "../components/studio/DetectionOverlay";
import type { RegionName } from "./TerrainContext";

export type OverlayMode = "off" | "minimal" | "full";

export type SignalCategory =
  | "context_time"
  | "governance"
  | "work_tasks"
  | "health_infra"
  | "profile_state"
  | "ambient_sensor"
  | "voice_session"
  | "system_state";

export const SIGNAL_CATEGORIES: SignalCategory[] = [
  "context_time",
  "governance",
  "work_tasks",
  "health_infra",
  "profile_state",
  "ambient_sensor",
  "voice_session",
  "system_state",
];

// Category → region mapping: where signals naturally belong
const CATEGORY_REGION: Record<SignalCategory, RegionName> = {
  context_time: "horizon",
  work_tasks: "horizon",
  profile_state: "field",
  ambient_sensor: "ground",
  voice_session: "ground",
  governance: "bedrock",
  system_state: "bedrock",
  health_infra: "bedrock",
};

// Raw hex colors from gruvbox palette for CSS use (not Tailwind classes)
export const CATEGORY_HEX: Record<SignalCategory, string> = {
  context_time: "#83a598",
  governance: "#d3869b",
  work_tasks: "#fe8019",
  health_infra: "#fb4934",
  profile_state: "#b8bb26",
  ambient_sensor: "#8ec07c",
  voice_session: "#fabd2f",
  system_state: "#bdae93",
};

// Category text colors — gruvbox palette only
export const CATEGORY_COLORS: Record<SignalCategory, string> = {
  context_time: "text-blue-400",
  governance: "text-fuchsia-400",
  work_tasks: "text-orange-400",
  health_infra: "text-red-400",
  profile_state: "text-green-400",
  ambient_sensor: "text-emerald-400",
  voice_session: "text-yellow-400",
  system_state: "text-zinc-400",
};

// Category background pills — gruvbox 500 level
export const CATEGORY_BG: Record<SignalCategory, string> = {
  context_time: "bg-blue-500",
  governance: "bg-fuchsia-500",
  work_tasks: "bg-orange-500",
  health_infra: "bg-red-500",
  profile_state: "bg-green-500",
  ambient_sensor: "bg-emerald-500",
  voice_session: "bg-yellow-500",
  system_state: "bg-zinc-500",
};

// Tinted zone backgrounds — dark gruvbox tints
export const CATEGORY_ZONE_BG: Record<SignalCategory, string> = {
  context_time: "bg-blue-600/20",
  governance: "bg-fuchsia-600/20",
  work_tasks: "bg-orange-600/20",
  health_infra: "bg-red-600/20",
  profile_state: "bg-green-600/20",
  ambient_sensor: "bg-emerald-600/20",
  voice_session: "bg-yellow-600/20",
  system_state: "bg-zinc-700/30",
};

// Zone border accent (left edge glow)
export const CATEGORY_BORDER: Record<SignalCategory, string> = {
  context_time: "border-l-blue-500/50",
  governance: "border-l-fuchsia-500/50",
  work_tasks: "border-l-orange-500/50",
  health_infra: "border-l-red-500/50",
  profile_state: "border-l-green-500/50",
  ambient_sensor: "border-l-emerald-500/50",
  voice_session: "border-l-yellow-500/50",
  system_state: "border-l-zinc-500/50",
};

export const CATEGORY_LABELS: Record<SignalCategory, string> = {
  context_time: "Context",
  governance: "Governance",
  work_tasks: "Tasks",
  health_infra: "Health",
  profile_state: "Operator",
  ambient_sensor: "Environment",
  voice_session: "Voice",
  system_state: "System",
};

export type SignalsByRegion = Record<RegionName, SignalEntry[]>;

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
  signalsByRegion: SignalsByRegion;
  stimmungStance: StimmungStance;
  zoneOpacityOverrides: Record<string, number>;
  setZoneOpacity: (zone: string, opacity: number) => void;
  // Detection overlay state
  detectionLayerVisible: boolean;
  setDetectionLayerVisible: (v: boolean) => void;
  detectionTier: DetectionTier;
  setDetectionTier: (t: DetectionTier) => void;
  classificationDetections: ClassificationDetection[];
}

const OverlayContext = createContext<OverlayContextValue | null>(null);

export function ClassificationOverlayProvider({ children }: { children: ReactNode }) {
  const { data: perception } = usePerception();
  const { data: visualLayer } = useVisualLayer();
  const [channelVisibility, setChannelVisibility] = useState(loadVisibility);
  const [overlayMode, setOverlayModeState] = useState(loadMode);
  const [zoneOpacityOverrides, setZoneOpacityOverrides] = useState<Record<string, number>>({});

  // Detection overlay state — persisted in localStorage
  const [detectionLayerVisible, setDetectionVisibleRaw] = useState(() => {
    try {
      const v = localStorage.getItem("hapax-detection-layer-visible");
      return v === null ? true : v === "true";
    } catch { return true; }
  });
  const [detectionTier, setDetectionTierRaw] = useState<DetectionTier>(() => {
    try {
      const v = localStorage.getItem("hapax-detection-tier");
      const n = v ? Number(v) : 1;
      return (n === 1 || n === 2 || n === 3 ? n : 1) as DetectionTier;
    } catch { return 1 as DetectionTier; }
  });

  const setDetectionLayerVisible = useCallback((v: boolean) => {
    setDetectionVisibleRaw(v);
    try { localStorage.setItem("hapax-detection-layer-visible", String(v)); } catch { /* */ }
  }, []);

  const setDetectionTier = useCallback((t: DetectionTier) => {
    setDetectionTierRaw(t);
    try { localStorage.setItem("hapax-detection-tier", String(t)); } catch { /* */ }
  }, []);

  const classificationDetections: ClassificationDetection[] = visualLayer?.classification_detections ?? [];

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

  const signalsByRegion = useMemo((): SignalsByRegion => {
    const byRegion: SignalsByRegion = {
      horizon: [],
      field: [],
      ground: [],
      watershed: [],
      bedrock: [],
    };
    for (const [cat, entries] of Object.entries(filteredSignals)) {
      const region = CATEGORY_REGION[cat as SignalCategory];
      if (region) {
        byRegion[region].push(...entries);
      }
    }
    return byRegion;
  }, [filteredSignals]);

  const stimmungStance: StimmungStance = visualLayer?.stimmung_stance ?? "nominal";

  const value = useMemo(
    () => ({
      perception,
      visualLayer,
      overlayMode,
      setOverlayMode,
      channelVisibility,
      toggleChannel,
      filteredSignals,
      signalsByRegion,
      stimmungStance,
      zoneOpacityOverrides,
      setZoneOpacity,
      detectionLayerVisible,
      setDetectionLayerVisible,
      detectionTier,
      setDetectionTier,
      classificationDetections,
    }),
    [perception, visualLayer, overlayMode, setOverlayMode, channelVisibility, toggleChannel, filteredSignals, signalsByRegion, stimmungStance, zoneOpacityOverrides, setZoneOpacity, detectionLayerVisible, setDetectionLayerVisible, detectionTier, setDetectionTier, classificationDetections],
  );

  return <OverlayContext.Provider value={value}>{children}</OverlayContext.Provider>;
}

export function useOverlay(): OverlayContextValue {
  const ctx = useContext(OverlayContext);
  if (!ctx) throw new Error("useOverlay must be used within ClassificationOverlayProvider");
  return ctx;
}
