/**
 * Exposes React context actions to window.__demo for the demo runner.
 * Must be mounted inside TerrainProvider. Studio control uses API calls
 * since GroundStudioProvider wraps only the Ground region, not the page.
 */
import { useEffect } from "react";
import { useTerrainActions } from "../contexts/TerrainContext";
import { api } from "../api/client";
import type { RegionName, Depth, Overlay, InvestigationTab } from "../contexts/TerrainContext";

export interface DemoBridge {
  terrain: {
    focusRegion: (region: RegionName | null) => void;
    setRegionDepth: (region: RegionName, depth: Depth) => void;
    cycleDepth: (region: RegionName) => void;
    setOverlay: (overlay: Overlay) => void;
    setInvestigationTab: (tab: InvestigationTab) => void;
    setSplitRegion: (region: RegionName | null) => void;
    setSplitFullscreen: (fs: boolean) => void;
    highlightRegion: (region: RegionName | null, durationMs?: number) => void;
  };
  studio: {
    selectPreset: (preset: string) => void;
  };
}

declare global {
  interface Window {
    __demo?: DemoBridge;
  }
}

export function useDemoBridge(): DemoBridge {
  const terrain = useTerrainActions();

  const bridge: DemoBridge = {
    terrain: {
      focusRegion: terrain.focusRegion,
      setRegionDepth: terrain.setRegionDepth,
      cycleDepth: terrain.cycleDepth,
      setOverlay: terrain.setOverlay,
      setInvestigationTab: terrain.setInvestigationTab,
      setSplitRegion: terrain.setSplitRegion,
      setSplitFullscreen: terrain.setSplitFullscreen,
      highlightRegion: (region: RegionName | null, durationMs?: number) => {
        terrain.highlightRegion(region);
        if (region && durationMs) {
          setTimeout(() => terrain.highlightRegion(null), durationMs);
        }
      },
    },
    studio: {
      selectPreset: (preset: string) => {
        api.post("/studio/effect/select", { preset }).catch(() => {});
      },
    },
  };

  useEffect(() => {
    window.__demo = bridge;
    return () => {
      delete window.__demo;
    };
  });

  return bridge;
}
