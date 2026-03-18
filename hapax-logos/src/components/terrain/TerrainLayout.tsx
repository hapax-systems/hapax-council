import { AmbientShader } from "../hapax/AmbientShader";
import { HorizonRegion } from "./regions/HorizonRegion";
import { FieldRegion } from "./regions/FieldRegion";
import { GroundRegion } from "./regions/GroundRegion";
import { WatershedRegion } from "./regions/WatershedRegion";
import { BedrockRegion } from "./regions/BedrockRegion";

export function TerrainLayout() {
  return (
    <div
      className="h-screen w-screen overflow-hidden relative"
      style={{ fontFamily: "'JetBrains Mono', monospace", background: "#1d2021" }}
    >
      {/* z-0: Ambient shader background — always alive */}
      <AmbientShader
        speed={0.08}
        turbulence={0.1}
        warmth={0.3}
        brightness={0.15}
        displayState="ambient"
      />

      {/* z-1: Terrain grid */}
      <div
        className="absolute inset-0"
        style={{
          zIndex: 1,
          display: "grid",
          gridTemplateColumns: "minmax(180px, 1fr) 3fr minmax(180px, 1fr)",
          gridTemplateRows: "12vh 1fr 10vh",
        }}
      >
        {/* Row 1: Horizon — spans all 3 columns */}
        <HorizonRegion />

        {/* Row 2: Field | Ground | Watershed */}
        <FieldRegion />
        <GroundRegion />
        <WatershedRegion />

        {/* Row 3: Bedrock — spans all 3 columns */}
        <BedrockRegion />
      </div>
    </div>
  );
}
