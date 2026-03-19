/**
 * DetailPane — renders a single region's content for the split-view right pane.
 * The region is rendered inside a Region wrapper so depth cycling, breadcrumbs, etc. work.
 *
 * Ground region gets a specialized StudioDetailPane with camera controls instead of
 * rendering the full GroundRegion again.
 */

import { useState } from "react";
import { HorizonRegion } from "./regions/HorizonRegion";
import { FieldRegion } from "./regions/FieldRegion";
import { GroundRegion } from "./regions/GroundRegion";
import { WatershedRegion } from "./regions/WatershedRegion";
import { BedrockRegion } from "./regions/BedrockRegion";
import { StudioDetailPane } from "./ground/StudioDetailPane";
import { useVisualLayerPoll } from "../../hooks/useVisualLayer";
import type { RegionName } from "../../contexts/TerrainContext";

interface DetailPaneProps {
  region: RegionName;
}

export function DetailPane({ region }: DetailPaneProps) {
  const vl = useVisualLayerPoll();
  const [heroRole, setHeroRole] = useState("brio-operator");
  const [fxMode, setFxMode] = useState(false);
  const [smoothMode, setSmoothMode] = useState(false);

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
      {region === "ground" && (
        <StudioDetailPane
          heroRole={heroRole}
          onHeroChange={setHeroRole}
          classificationDetections={vl.classificationDetections}
          fxMode={fxMode}
          onFxModeChange={setFxMode}
          smoothMode={smoothMode}
          onSmoothModeChange={setSmoothMode}
        />
      )}
      {region === "watershed" && <WatershedRegion />}
      {region === "bedrock" && <BedrockRegion />}
    </div>
  );
}
