/**
 * DetailPane -- renders a single region's content for the split-view right pane.
 * The region is rendered inside a Region wrapper so depth cycling, breadcrumbs, etc. work.
 *
 * Ground region gets a specialized StudioDetailPane with camera controls instead of
 * rendering the full GroundRegion again.
 */

import { HorizonRegion } from "./regions/HorizonRegion";
import { FieldRegion } from "./regions/FieldRegion";
import { WatershedRegion } from "./regions/WatershedRegion";
import { BedrockRegion } from "./regions/BedrockRegion";
import type { RegionName } from "../../contexts/TerrainContext";

interface DetailPaneProps {
  region: RegionName;
}

export function DetailPane({ region }: DetailPaneProps) {
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
        <div className="flex items-center justify-center h-full text-[var(--color-fg4)] text-sm">
          Graph canvas controls (Plan B)
        </div>
      )}
      {region === "watershed" && <WatershedRegion />}
      {region === "bedrock" && <BedrockRegion />}
    </div>
  );
}
