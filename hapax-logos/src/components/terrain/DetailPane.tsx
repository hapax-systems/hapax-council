/**
 * DetailPane — renders a single region's content for the split-view right pane.
 * The region is rendered inside a Region wrapper so depth cycling, breadcrumbs, etc. work.
 */

import { HorizonRegion } from "./regions/HorizonRegion";
import { FieldRegion } from "./regions/FieldRegion";
import { GroundRegion } from "./regions/GroundRegion";
import { WatershedRegion } from "./regions/WatershedRegion";
import { BedrockRegion } from "./regions/BedrockRegion";
import { useVisualLayerPoll } from "../../hooks/useVisualLayer";
import type { RegionName } from "../../contexts/TerrainContext";

interface DetailPaneProps {
  region: RegionName;
}

export function DetailPane({ region }: DetailPaneProps) {
  const vl = useVisualLayerPoll();

  return (
    <div
      className="w-full h-full"
      style={{
        background: "#1d2021",
        display: "grid",
        gridTemplateRows: "1fr",
        gridTemplateColumns: "1fr",
      }}
    >
      {region === "horizon" && <HorizonRegion />}
      {region === "field" && <FieldRegion />}
      {region === "ground" && <GroundRegion vl={vl} />}
      {region === "watershed" && <WatershedRegion />}
      {region === "bedrock" && <BedrockRegion />}
    </div>
  );
}
