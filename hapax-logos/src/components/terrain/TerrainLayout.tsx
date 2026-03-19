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
import { SplitPane } from "./SplitPane";
import { DetailPane } from "./DetailPane";
import { ClassificationOverlayProvider } from "../../contexts/ClassificationOverlayContext";
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
  const middleRegions: RegionName[] = ["field", "ground", "watershed"];
  const coreMiddle = middleRegions.some((r) => regionDepths[r] === "core");

  // When a middle region is at core, minimize horizon/bedrock to give studio max space
  const horizonRow = coreMiddle
    ? "3.5vh"
    : horizonExpanded
      ? "minmax(12vh, 35vh)"
      : "12vh";
  const bedrockRow = coreMiddle
    ? "3vh"
    : bedrockExpanded
      ? "minmax(10vh, 40vh)"
      : "10vh";
  return `${horizonRow} 1fr ${bedrockRow}`;
}

/** Which middle-row region (if any) is at core depth — it should span all columns */
function useCoreMiddleRegion(): RegionName | null {
  const { regionDepths } = useTerrain();
  const middleRegions: RegionName[] = ["field", "ground", "watershed"];
  return middleRegions.find((r) => regionDepths[r] === "core") ?? null;
}

export function TerrainLayout() {
  const vl = useVisualLayerPoll();
  const { activeOverlay, setOverlay, focusRegion, cycleDepth, focusedRegion, regionDepths, setRegionDepth, splitRegion, splitFullscreen, setSplitRegion, setSplitFullscreen } = useTerrain();
  const gridRows = useGridRows();
  const coreMiddle = useCoreMiddleRegion();

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

      if (e.key === "Escape") {
        // Don't navigate when exiting fullscreen — browser handles that Escape
        if (document.fullscreenElement) return;
        if (activeOverlay) {
          setOverlay(null);
          return;
        }
        // Close split pane before collapsing regions
        if (splitRegion) {
          setSplitRegion(null);
          return;
        }
        // Collapse focused region back to surface
        if (focusedRegion && regionDepths[focusedRegion] !== "surface") {
          setRegionDepth(focusedRegion, "surface");
          focusRegion(null);
          return;
        }
        // Unfocus if at surface
        if (focusedRegion) {
          focusRegion(null);
          return;
        }
        return;
      }

      // S key: toggle split for focused region
      if (e.key.toLowerCase() === "s" && !isInput && !e.ctrlKey && !e.metaKey && activeOverlay !== "investigation") {
        if (splitRegion) {
          setSplitRegion(null);
        } else if (focusedRegion) {
          setSplitRegion(focusedRegion);
        }
        return;
      }

      // Region shortcuts — blocked only during investigation overlay, not voice
      if (activeOverlay !== "investigation" && !isInput && !e.ctrlKey && !e.metaKey) {
        const region = REGION_KEYS[e.key.toLowerCase()];
        if (region) {
          focusRegion(region);
          cycleDepth(region);
        }
      }
    },
    [activeOverlay, setOverlay, focusRegion, cycleDepth, focusedRegion, regionDepths, setRegionDepth, splitRegion, setSplitRegion],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <ClassificationOverlayProvider>
      <div
        className="h-screen w-screen overflow-hidden relative"
        style={{ fontFamily: "'JetBrains Mono', monospace", background: "#1d2021" }}
      >
        {/* z-0: Ambient shader background */}
        <AmbientShader
          speed={vl.ambient.speed}
          turbulence={vl.ambient.turbulence}
          warmth={vl.ambient.color_warmth}
          brightness={vl.ambient.brightness * 0.6}
          displayState={vl.state}
        />

        {/* z-1: Terrain grid (optionally wrapped in SplitPane) */}
        {splitRegion ? (
          <SplitPane
            left={
              <div
                className="w-full h-full overflow-hidden"
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(180px, 1fr) 3fr minmax(180px, 1fr)",
                  gridTemplateRows: gridRows,
                  transition: "grid-template-rows 300ms ease",
                }}
              >
                <HorizonRegion />
                {splitRegion !== "field" && <FieldRegion />}
                {splitRegion !== "ground" && <GroundRegion vl={vl} />}
                {splitRegion !== "watershed" && <WatershedRegion />}
                <BedrockRegion />
              </div>
            }
            right={<DetailPane region={splitRegion} />}
            fullscreen={splitFullscreen}
            onClose={() => setSplitRegion(null)}
            onToggleFullscreen={() => setSplitFullscreen(!splitFullscreen)}
            regionLabel={splitRegion}
          />
        ) : (
          <div
            className="absolute inset-0 overflow-hidden"
            style={{
              zIndex: 1,
              display: "grid",
              gridTemplateColumns: coreMiddle ? "1fr" : "minmax(180px, 1fr) 3fr minmax(180px, 1fr)",
              gridTemplateRows: gridRows,
              transition: "grid-template-rows 300ms ease",
            }}
          >
            <HorizonRegion />
            {(!coreMiddle || coreMiddle === "field") && <FieldRegion />}
            {(!coreMiddle || coreMiddle === "ground") && <GroundRegion vl={vl} />}
            {(!coreMiddle || coreMiddle === "watershed") && <WatershedRegion />}
            <BedrockRegion />
          </div>
        )}

        {/* z-20: Agent output drawer */}
        <AgentOutputDrawer />

        {/* z-40: Investigation overlay */}
        <InvestigationOverlay />

        {/* z-50: Voice overlay */}
        <VoiceOverlay vl={vl} />
      </div>
    </ClassificationOverlayProvider>
  );
}
