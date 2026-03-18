import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { TerrainProvider, useTerrain, type RegionName, type Depth, type InvestigationTab } from "../contexts/TerrainContext";
import { TerrainLayout } from "../components/terrain/TerrainLayout";

const REGIONS: RegionName[] = ["horizon", "field", "ground", "watershed", "bedrock"];
const DEPTHS: Depth[] = ["surface", "stratum", "core"];
const TABS: InvestigationTab[] = ["chat", "insight", "demos"];

function TerrainParamSync() {
  const [params] = useSearchParams();
  const { setRegionDepth, focusRegion, setOverlay, setInvestigationTab } = useTerrain();

  useEffect(() => {
    const region = params.get("region") as RegionName | null;
    const depth = params.get("depth") as Depth | null;
    const overlay = params.get("overlay");
    const tab = params.get("tab") as InvestigationTab | null;

    if (region && REGIONS.includes(region)) {
      focusRegion(region);
      if (depth && DEPTHS.includes(depth)) {
        setRegionDepth(region, depth);
      }
    }

    if (overlay === "investigation") {
      setOverlay("investigation");
      if (tab && TABS.includes(tab)) {
        setInvestigationTab(tab);
      }
    }
  }, [params, setRegionDepth, focusRegion, setOverlay, setInvestigationTab]);

  return null;
}

export function TerrainPage() {
  return (
    <TerrainProvider>
      <TerrainParamSync />
      <TerrainLayout />
    </TerrainProvider>
  );
}
