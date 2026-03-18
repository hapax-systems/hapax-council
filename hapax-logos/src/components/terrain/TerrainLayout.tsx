import { useEffect, useCallback } from "react";
import { AmbientShader } from "../hapax/AmbientShader";
import { HorizonRegion } from "./regions/HorizonRegion";
import { FieldRegion } from "./regions/FieldRegion";
import { GroundRegion } from "./regions/GroundRegion";
import { WatershedRegion } from "./regions/WatershedRegion";
import { BedrockRegion } from "./regions/BedrockRegion";
import { VoiceOverlay } from "./overlays/VoiceOverlay";
import { InvestigationOverlay } from "./overlays/InvestigationOverlay";
import { AgentOutputDrawer } from "./AgentOutputDrawer";
import { useVisualLayerPoll } from "../../hooks/useVisualLayer";
import { useTerrain, type RegionName } from "../../contexts/TerrainContext";

const REGION_KEYS: Record<string, RegionName> = {
  h: "horizon",
  f: "field",
  g: "ground",
  w: "watershed",
  b: "bedrock",
};

function useGridRows(): string {
  const { regionDepths } = useTerrain();
  const horizonExpanded = regionDepths.horizon !== "surface";
  const bedrockExpanded = regionDepths.bedrock !== "surface";

  // Dynamic row sizing: expanded regions claim more space
  const horizonRow = horizonExpanded ? "minmax(12vh, 35vh)" : "12vh";
  const bedrockRow = bedrockExpanded ? "minmax(10vh, 40vh)" : "10vh";
  return `${horizonRow} 1fr ${bedrockRow}`;
}

export function TerrainLayout() {
  const vl = useVisualLayerPoll();
  const { activeOverlay, setOverlay, focusRegion, cycleDepth } = useTerrain();
  const gridRows = useGridRows();

  // Voice overlay: auto-show when voice active
  useEffect(() => {
    if (vl.voiceSession.active && activeOverlay !== "investigation") {
      setOverlay("voice");
    } else if (!vl.voiceSession.active && activeOverlay === "voice") {
      setOverlay(null);
    }
  }, [vl.voiceSession.active, activeOverlay, setOverlay]);

  // Keyboard: `/` toggles investigation, H/F/G/W/B focus regions, Escape dismisses
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput =
        target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;

      if (e.key === "/" && !e.ctrlKey && !e.metaKey && !isInput) {
        e.preventDefault();
        setOverlay(activeOverlay === "investigation" ? null : "investigation");
        return;
      }

      if (e.key === "Escape" && activeOverlay) {
        setOverlay(null);
        return;
      }

      // Region shortcuts — only when no overlay and not in input
      if (!activeOverlay && !isInput && !e.ctrlKey && !e.metaKey) {
        const region = REGION_KEYS[e.key.toLowerCase()];
        if (region) {
          focusRegion(region);
          cycleDepth(region);
        }
      }
    },
    [activeOverlay, setOverlay, focusRegion, cycleDepth],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <div
      className="h-screen w-screen overflow-hidden relative"
      style={{ fontFamily: "'JetBrains Mono', monospace", background: "#1d2021" }}
    >
      {/* z-0: Ambient shader background — always alive, driven by visual layer */}
      <AmbientShader
        speed={vl.ambient.speed}
        turbulence={vl.ambient.turbulence}
        warmth={vl.ambient.color_warmth}
        brightness={vl.ambient.brightness * 0.6}
        displayState={vl.state}
      />

      {/* z-1: Terrain grid */}
      <div
        className="absolute inset-0"
        style={{
          zIndex: 1,
          display: "grid",
          gridTemplateColumns: "minmax(180px, 1fr) 3fr minmax(180px, 1fr)",
          gridTemplateRows: gridRows,
          transition: "grid-template-rows 300ms ease",
        }}
      >
        <HorizonRegion />
        <FieldRegion />
        <GroundRegion vl={vl} />
        <WatershedRegion />
        <BedrockRegion />
      </div>

      {/* z-20: Agent output drawer */}
      <AgentOutputDrawer />

      {/* z-40: Investigation overlay */}
      <InvestigationOverlay />

      {/* z-50: Voice overlay */}
      <VoiceOverlay vl={vl} />
    </div>
  );
}
