import { createContext, useContext, useCallback, useState, type ReactNode } from "react";

export type RegionName = "horizon" | "field" | "ground" | "watershed" | "bedrock";
export type Depth = "surface" | "stratum" | "core";
export type Overlay = "voice" | "investigation" | null;
export type InvestigationTab = "chat" | "insight" | "demos";

interface TerrainState {
  focusedRegion: RegionName | null;
  regionDepths: Record<RegionName, Depth>;
  activeOverlay: Overlay;
  investigationTab: InvestigationTab;
}

interface TerrainActions {
  focusRegion: (region: RegionName | null) => void;
  setRegionDepth: (region: RegionName, depth: Depth) => void;
  cycleDepth: (region: RegionName) => void;
  setOverlay: (overlay: Overlay) => void;
  setInvestigationTab: (tab: InvestigationTab) => void;
}

type TerrainContextValue = TerrainState & TerrainActions;

const TerrainContext = createContext<TerrainContextValue | null>(null);

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

  return (
    <TerrainContext.Provider
      value={{
        focusedRegion,
        regionDepths,
        activeOverlay,
        investigationTab,
        focusRegion,
        setRegionDepth,
        cycleDepth,
        setOverlay,
        setInvestigationTab,
      }}
    >
      {children}
    </TerrainContext.Provider>
  );
}

export function useTerrain(): TerrainContextValue {
  const ctx = useContext(TerrainContext);
  if (!ctx) throw new Error("useTerrain must be used within TerrainProvider");
  return ctx;
}
