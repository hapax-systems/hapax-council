import { memo } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Region } from "../Region";
import { StudioCanvas } from "../../graph/StudioCanvas";
import { useSignals } from "../../../contexts/ClassificationOverlayContext";
import { useTerrainDisplay } from "../../../contexts/TerrainContext";
import type { VisualLayerState } from "../../../api/types";

interface GroundRegionProps {
  vl: VisualLayerState | undefined;
}

export const GroundRegion = memo(function GroundRegion() {
  const { stimmungStance } = useSignals();
  const { regionDepths } = useTerrainDisplay();

  return (
    <Region
      name="ground"
      style={regionDepths.ground === "core" ? { zIndex: 1 } : undefined}
      stimmungStance={stimmungStance}
    >
      {() => (
        <div className="h-full relative">
          <ReactFlowProvider>
            <StudioCanvas />
          </ReactFlowProvider>
        </div>
      )}
    </Region>
  );
});

export { type GroundRegionProps };
