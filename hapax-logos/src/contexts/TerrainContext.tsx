import { createContext, useContext, useCallback, useMemo, useState, type ReactNode } from "react";

export type RegionName = "horizon" | "field" | "ground" | "watershed" | "bedrock";
export type Depth = "surface" | "stratum" | "core";
export type Overlay = "voice" | "investigation" | null;
export type InvestigationTab = "chat" | "insight" | "demos";

// ── Display Context ─────────────────────────────────────────────────────
// Read-only state that drives grid layout. Changes when regions cycle depth.
interface TerrainDisplayValue {
  focusedRegion: RegionName | null;
  regionDepths: Record<RegionName, Depth>;
  activeOverlay: Overlay;
  investigationTab: InvestigationTab;
  splitRegion: RegionName | null;
  splitFullscreen: boolean;
}

const TerrainDisplayContext = createContext<TerrainDisplayValue | null>(null);

// ── Action Context ──────────────────────────────────────────────────────
// Stable callbacks — never change identity after mount.
interface TerrainActionValue {
  focusRegion: (region: RegionName | null) => void;
  setRegionDepth: (region: RegionName, depth: Depth) => void;
  cycleDepth: (region: RegionName) => void;
  setOverlay: (overlay: Overlay) => void;
  setInvestigationTab: (tab: InvestigationTab) => void;
  setSplitRegion: (region: RegionName | null) => void;
  setSplitFullscreen: (fs: boolean) => void;
}

const TerrainActionContext = createContext<TerrainActionValue | null>(null);

type TerrainContextValue = TerrainDisplayValue & TerrainActionValue;

const DEFAULT_DEPTHS: Record<RegionName, Depth> = {
  horizon: "surface",
  field: "surface",
  ground: "surface",
  watershed: "surface",
  bedrock: "surface",
};

const DEPTH_ORDER: Depth[] = ["surface", "stratum", "core"];

export function TerrainProvider({ children }: { children: ReactNode }) {
  const [focusedRegion, setFocusedRegion] = useState<RegionName | null>(null);
  const [regionDepths, setRegionDepths] = useState<Record<RegionName, Depth>>(DEFAULT_DEPTHS);
  const [activeOverlay, setActiveOverlay] = useState<Overlay>(null);
  const [investigationTab, setInvestigationTab] = useState<InvestigationTab>("chat");
  const [splitRegion, setSplitRegionState] = useState<RegionName | null>(null);
  const [splitFullscreen, setSplitFullscreen] = useState(false);

  const setSplitRegion = useCallback((region: RegionName | null) => {
    setSplitRegionState(region);
    setSplitFullscreen(false);
    // Auto-deepen to stratum when splitting
    if (region) {
      setRegionDepths((prev) => ({
        ...prev,
        [region]: prev[region] === "surface" ? "stratum" : prev[region],
      }));
    }
  }, []);

  const focusRegion = useCallback((region: RegionName | null) => {
    setFocusedRegion(region);
  }, []);

  const setRegionDepth = useCallback((region: RegionName, depth: Depth) => {
    setRegionDepths((prev) => ({ ...prev, [region]: depth }));
  }, []);

  const cycleDepth = useCallback((region: RegionName) => {
    setRegionDepths((prev) => {
      const current = prev[region];
      const idx = DEPTH_ORDER.indexOf(current);
      const next = DEPTH_ORDER[(idx + 1) % DEPTH_ORDER.length];
      return { ...prev, [region]: next };
    });
  }, []);

  const setOverlay = useCallback((overlay: Overlay) => {
    setActiveOverlay(overlay);
  }, []);

  const displayValue = useMemo(
    () => ({ focusedRegion, regionDepths, activeOverlay, investigationTab, splitRegion, splitFullscreen }),
    [focusedRegion, regionDepths, activeOverlay, investigationTab, splitRegion, splitFullscreen],
  );

  const actionValue = useMemo(
    () => ({ focusRegion, setRegionDepth, cycleDepth, setOverlay, setInvestigationTab, setSplitRegion, setSplitFullscreen }),
    [focusRegion, setRegionDepth, cycleDepth, setOverlay, setInvestigationTab, setSplitRegion, setSplitFullscreen],
  );

  return (
    <TerrainDisplayContext.Provider value={displayValue}>
      <TerrainActionContext.Provider value={actionValue}>
        {children}
      </TerrainActionContext.Provider>
    </TerrainDisplayContext.Provider>
  );
}

// ── Narrow hooks ────────────────────────────────────────────────────────

const noopFn = () => {};
const DISPLAY_FALLBACK: TerrainDisplayValue = {
  focusedRegion: null,
  regionDepths: DEFAULT_DEPTHS,
  activeOverlay: null,
  investigationTab: "chat",
  splitRegion: null,
  splitFullscreen: false,
};
const ACTION_FALLBACK: TerrainActionValue = {
  focusRegion: noopFn,
  setRegionDepth: noopFn,
  cycleDepth: noopFn,
  setOverlay: noopFn,
  setInvestigationTab: noopFn,
  setSplitRegion: noopFn,
  setSplitFullscreen: noopFn,
};

export function useTerrainDisplay(): TerrainDisplayValue {
  const ctx = useContext(TerrainDisplayContext);
  return ctx ?? DISPLAY_FALLBACK;
}

export function useTerrainActions(): TerrainActionValue {
  const ctx = useContext(TerrainActionContext);
  return ctx ?? ACTION_FALLBACK;
}

// ── Convenience hook (reads both — use narrower hooks when possible) ──

export function useTerrain(): TerrainContextValue {
  const display = useTerrainDisplay();
  const actions = useTerrainActions();
  return { ...display, ...actions };
}
