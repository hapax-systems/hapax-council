import { useEffect, useCallback, useState } from "react";
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
import { GroundStudioProvider } from "../../contexts/GroundStudioContext";
import { useVisualLayer } from "../../api/hooks";
import { useTerrain, useTerrainDisplay, type RegionName } from "../../contexts/TerrainContext";

const REGION_KEYS: Record<string, RegionName> = {
  h: "horizon",
  f: "field",
  g: "ground",
  w: "watershed",
  b: "bedrock",
};

function useGridRows(): string {
  const { regionDepths } = useTerrainDisplay();
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
  const { regionDepths } = useTerrainDisplay();
  const middleRegions: RegionName[] = ["field", "ground", "watershed"];
  return middleRegions.find((r) => regionDepths[r] === "core") ?? null;
}

const HINT_STORAGE_KEY = "terrain-hints-dismissed";

function KeyboardHintBar() {
  const [visible, setVisible] = useState(() => {
    try {
      return !localStorage.getItem(HINT_STORAGE_KEY);
    } catch {
      return true;
    }
  });

  const dismiss = useCallback(() => {
    setVisible(false);
    try {
      localStorage.setItem(HINT_STORAGE_KEY, "1");
    } catch {
      /* ignore */
    }
  }, []);

  // Auto-dismiss on first meaningful interaction
  useEffect(() => {
    if (!visible) return;
    const handler = () => dismiss();
    // Dismiss on any region click or keyboard shortcut
    window.addEventListener("keydown", handler, { once: true });
    return () => window.removeEventListener("keydown", handler);
  }, [visible, dismiss]);

  if (!visible) return null;

  return (
    <div
      className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-4 items-center px-4 py-1.5 rounded"
      style={{
        zIndex: 10,
        background: "rgba(29, 32, 33, 0.85)",
        backdropFilter: "blur(8px)",
        border: "1px solid rgba(180, 160, 120, 0.12)",
        fontSize: 11,
        color: "rgba(180, 160, 120, 0.5)",
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: "0.04em",
      }}
    >
      <span><kbd>H</kbd> <kbd>F</kbd> <kbd>G</kbd> <kbd>W</kbd> <kbd>B</kbd> regions</span>
      <span><kbd>/</kbd> investigate</span>
      <span><kbd>?</kbd> manual</span>
      <span><kbd>S</kbd> split</span>
      <button
        onClick={dismiss}
        style={{ color: "rgba(180, 160, 120, 0.3)", cursor: "pointer", background: "none", border: "none", padding: "0 0 0 4px", fontSize: 11 }}
        aria-label="Dismiss hints"
      >
        ×
      </button>
    </div>
  );
}

export function TerrainLayout() {
  const { data: vl } = useVisualLayer();
  const { activeOverlay, setOverlay, focusRegion, cycleDepth, focusedRegion, regionDepths, setRegionDepth, splitRegion, splitFullscreen, setSplitRegion, setSplitFullscreen } = useTerrain();
  const gridRows = useGridRows();
  const coreMiddle = useCoreMiddleRegion();

  // Extract fields with defaults
  const ambient = vl?.ambient_params ?? { speed: 0.08, turbulence: 0.1, color_warmth: 0.3, brightness: 0.25 };
  const displayState = vl?.display_state ?? "ambient";
  const voiceActive = vl?.voice_session?.active ?? false;

  // Voice overlay: auto-show when voice active
  useEffect(() => {
    if (voiceActive && activeOverlay !== "investigation") {
      setOverlay("voice");
    } else if (!voiceActive && activeOverlay === "voice") {
      setOverlay(null);
    }
  }, [voiceActive, activeOverlay, setOverlay]);

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
      if (e.key.toLowerCase() === "s" && !isInput && !e.ctrlKey && !e.metaKey && !e.altKey && activeOverlay !== "investigation") {
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
          if (focusedRegion === region) {
            cycleDepth(region);
          } else {
            focusRegion(region);
          }
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
    <GroundStudioProvider>
      <div
        className="h-screen w-screen overflow-hidden relative"
        style={{ fontFamily: "'JetBrains Mono', monospace", background: "#1d2021" }}
      >
        {/* z-0: Ambient shader background */}
        <AmbientShader
          speed={ambient.speed}
          turbulence={ambient.turbulence}
          warmth={ambient.color_warmth}
          brightness={ambient.brightness * 0.6}
          displayState={displayState}
        />

        {/* z-1: Terrain grid (optionally wrapped in SplitPane) */}
        {splitRegion ? (
          <SplitPane
            left={
              <div
                className="w-full h-full overflow-hidden"
                style={{
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
            }
            fullscreenLeft={
              splitRegion === "ground" ? (
                <div className="w-full h-full overflow-hidden relative" style={{ background: "#1d2021" }}>
                  <GroundRegion vl={vl} />
                </div>
              ) : undefined
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

        {/* z-10: Keyboard hint bar — dismisses on first interaction */}
        <KeyboardHintBar />

      </div>
    </GroundStudioProvider>
    </ClassificationOverlayProvider>
  );
}
