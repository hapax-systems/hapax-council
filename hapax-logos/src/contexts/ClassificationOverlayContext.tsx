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

// Theme-aware signal colors via CSS custom properties (see docs/logos-design-language.md §3.3).
// These resolve at render time through ThemeProvider, so they adapt to working mode.
export const CATEGORY_HEX: Record<SignalCategory, string> = {
  context_time: "var(--color-blue-400)",
  governance: "var(--color-fuchsia-400)",
  work_tasks: "var(--color-orange-400)",
  health_infra: "var(--color-red-400)",
  profile_state: "var(--color-green-400)",
  ambient_sensor: "var(--color-emerald-400)",
  voice_session: "var(--color-yellow-400)",
  system_state: "var(--color-zinc-400)",
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

// ── Signal Context ──────────────────────────────────────────────────────
// Changes at VL poll rate (~2s). Consumers: all 5 regions, PerceptionPage
interface SignalContextValue {
  perception: PerceptionState | undefined;
  visualLayer: VisualLayerState | undefined;
  filteredSignals: Record<string, SignalEntry[]>;
  signalsByRegion: SignalsByRegion;
  stimmungStance: StimmungStance;
}

const SignalContext = createContext<SignalContextValue | null>(null);

// ── Detection Context ───────────────────────────────────────────────────
// Changes at VL poll rate + user toggles. Consumers: DetectionOverlay, camera components, StudioDetailPane
/** Per-classifier enrichment visibility toggles. */
export const ENRICHMENT_KEYS = [
  "gaze", "emotion", "posture", "gesture", "action",
  "depth", "trajectory", "velocity", "dwell",
] as const;
export type EnrichmentKey = (typeof ENRICHMENT_KEYS)[number];

interface DetectionContextValue {
  classificationDetections: ClassificationDetection[];
  detectionLayerVisible: boolean;
  setDetectionLayerVisible: (v: boolean) => void;
  detectionTier: DetectionTier;
  setDetectionTier: (t: DetectionTier) => void;
  enrichmentVisibility: Record<string, boolean>;
  setEnrichmentVisibility: (key: string, visible: boolean) => void;
}

const DetectionContext = createContext<DetectionContextValue | null>(null);

// ── Overlay Control Context ─────────────────────────────────────────────
// Changes on user interaction only. Consumers: PerceptionCanvas, PerceptionSidebar, PerceptionOverlayPortal
interface OverlayControlContextValue {
  overlayMode: OverlayMode;
  setOverlayMode: (mode: OverlayMode) => void;
  channelVisibility: Record<SignalCategory, boolean>;
  toggleChannel: (cat: SignalCategory) => void;
  zoneOpacityOverrides: Record<string, number>;
  setZoneOpacity: (zone: string, opacity: number) => void;
}

const OverlayControlContext = createContext<OverlayControlContextValue | null>(null);

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

  // Per-classifier enrichment visibility — persisted in localStorage
  const [enrichmentVisibility, setEnrichmentVisRaw] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem("hapax-detection-enrichments");
      if (raw) return JSON.parse(raw) as Record<string, boolean>;
    } catch { /* */ }
    return Object.fromEntries(ENRICHMENT_KEYS.map((k) => [k, true]));
  });

  const setEnrichmentVisibility = useCallback((key: string, visible: boolean) => {
    setEnrichmentVisRaw((prev) => {
      const next = { ...prev, [key]: visible };
      try { localStorage.setItem("hapax-detection-enrichments", JSON.stringify(next)); } catch { /* */ }
      return next;
    });
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

  // Signal context — changes at VL poll rate
  const signalValue = useMemo(
    () => ({ perception, visualLayer, filteredSignals, signalsByRegion, stimmungStance }),
    [perception, visualLayer, filteredSignals, signalsByRegion, stimmungStance],
  );

  // Detection context — VL poll rate + user toggles
  const detectionValue = useMemo(
    () => ({ classificationDetections, detectionLayerVisible, setDetectionLayerVisible, detectionTier, setDetectionTier, enrichmentVisibility, setEnrichmentVisibility }),
    [classificationDetections, detectionLayerVisible, setDetectionLayerVisible, detectionTier, setDetectionTier, enrichmentVisibility, setEnrichmentVisibility],
  );

  // Overlay control — user interaction only
  const overlayControlValue = useMemo(
    () => ({ overlayMode, setOverlayMode, channelVisibility, toggleChannel, zoneOpacityOverrides, setZoneOpacity }),
    [overlayMode, setOverlayMode, channelVisibility, toggleChannel, zoneOpacityOverrides, setZoneOpacity],
  );

  return (
    <SignalContext.Provider value={signalValue}>
      <DetectionContext.Provider value={detectionValue}>
        <OverlayControlContext.Provider value={overlayControlValue}>
          {children}
        </OverlayControlContext.Provider>
      </DetectionContext.Provider>
    </SignalContext.Provider>
  );
}

// ── Narrow hooks ────────────────────────────────────────────────────────

export function useSignals(): SignalContextValue {
  const ctx = useContext(SignalContext);
  if (!ctx) throw new Error("useSignals must be used within ClassificationOverlayProvider");
  return ctx;
}

export function useDetections(): DetectionContextValue {
  const ctx = useContext(DetectionContext);
  if (!ctx) throw new Error("useDetections must be used within ClassificationOverlayProvider");
  return ctx;
}

export function useOverlayControl(): OverlayControlContextValue {
  const ctx = useContext(OverlayControlContext);
  if (!ctx) throw new Error("useOverlayControl must be used within ClassificationOverlayProvider");
  return ctx;
}

// ── Convenience hook (reads all 3 — use narrower hooks when possible) ──

type OverlayContextValue = SignalContextValue & DetectionContextValue & OverlayControlContextValue;

export function useOverlay(): OverlayContextValue {
  const signals = useSignals();
  const detections = useDetections();
  const overlayControl = useOverlayControl();
  return { ...signals, ...detections, ...overlayControl };
}
