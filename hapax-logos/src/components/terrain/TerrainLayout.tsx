import { useEffect, useCallback, useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AmbientShader } from "../hapax/AmbientShader";
import { HorizonRegion } from "./regions/HorizonRegion";
import { FieldRegion } from "./regions/FieldRegion";
import { GroundRegion } from "./regions/GroundRegion";
import { WatershedRegion } from "./regions/WatershedRegion";
import { BedrockRegion } from "./regions/BedrockRegion";
import { VoiceOverlay } from "./overlays/VoiceOverlay";
import { InvestigationOverlay } from "./overlays/InvestigationOverlay";
import { ClassificationInspector } from "./overlays/ClassificationInspector";
import { AgentOutputDrawer } from "./AgentOutputDrawer";
import { SplitPane } from "./SplitPane";
import { DetailPane } from "./DetailPane";
import { ClassificationOverlayProvider } from "../../contexts/ClassificationOverlayContext";
import { GroundStudioProvider, useGroundStudio } from "../../contexts/GroundStudioContext";
import { useVisualLayer } from "../../api/hooks";
import { useTerrain, useTerrainDisplay, type RegionName } from "../../contexts/TerrainContext";
import { CommandRegistryBridge } from "./CommandRegistryBridge";
import { CommandFeedback } from "./CommandFeedback";

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
      <span><kbd>D</kbd> detect</span>
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

/** URL param sync for studio state (must be inside GroundStudioProvider). */
function StudioParamSync() {
  const { setSmoothMode, setEffectSourceId } = useGroundStudio();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const presetName = params.get("preset");
    const source = params.get("source");
    const hls = params.get("hls");

    if (presetName) {
      // Activate preset via backend API
      fetch(`/api/studio/presets/${presetName}/activate`, { method: "POST" }).catch(() => {});
    }
    if (source) {
      setEffectSourceId(source);
    }
    if (hls === "1") {
      setSmoothMode(true);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- run once on mount

  return null;
}

export function TerrainLayout() {
  const { data: vl } = useVisualLayer();
  const { activeOverlay, setOverlay, splitRegion, splitFullscreen, setSplitRegion, setSplitFullscreen } = useTerrain();
  const gridRows = useGridRows();
  const coreMiddle = useCoreMiddleRegion();

  // Extract fields with defaults
  const ambient = vl?.ambient_params ?? { speed: 0.08, turbulence: 0.1, color_warmth: 0.3, brightness: 0.25 };
  const displayState = vl?.display_state ?? "ambient";
  const voiceActive = vl?.voice_session?.active ?? false;
  const readiness = vl?.readiness ?? "waiting";
  const isReady = readiness === "ready";

  // Boot overlay fade-out: stay mounted for 500ms after ready, then unmount
  const [overlayMounted, setOverlayMounted] = useState(true);
  const [overlayVisible, setOverlayVisible] = useState(true);
  const queryClient = useQueryClient();
  const hasInvalidated = useRef(false);
  useEffect(() => {
    if (isReady) {
      // Invalidate all queries so stale cold-cache data is refetched
      if (!hasInvalidated.current) {
        hasInvalidated.current = true;
        queryClient.invalidateQueries();
      }
      setOverlayVisible(false);
      const timer = setTimeout(() => setOverlayMounted(false), 600);
      return () => clearTimeout(timer);
    } else {
      setOverlayMounted(true);
      hasInvalidated.current = false;
      requestAnimationFrame(() => setOverlayVisible(true));
    }
  }, [isReady, queryClient]);

  // Voice overlay: auto-show when voice active
  useEffect(() => {
    if (voiceActive && activeOverlay !== "investigation") {
      setOverlay("voice");
    } else if (!voiceActive && activeOverlay === "voice") {
      setOverlay(null);
    }
  }, [voiceActive, activeOverlay, setOverlay]);

  return (
    <ClassificationOverlayProvider>
    <GroundStudioProvider>
      <StudioParamSync />
      <CommandRegistryBridge />
      <CommandFeedback />
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

        {/* Boot readiness overlay — dims content and blocks interaction until system data flows */}
        {overlayMounted && (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{
              zIndex: 40,
              background: "rgba(29, 32, 33, 0.85)",
              opacity: overlayVisible ? 1 : 0,
              transition: "opacity 500ms ease",
              pointerEvents: overlayVisible ? "auto" : "none",
            }}
          >
            <div className="flex flex-col items-center gap-3">
              <span
                className="text-[12px] uppercase tracking-[0.4em]"
                style={{ color: "rgba(180, 160, 120, 0.4)" }}
              >
                {readiness === "waiting" ? "waiting" : "collecting"}
              </span>
              <div className="flex gap-1.5">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="w-1.5 h-1.5 rounded-full"
                    style={{
                      background:
                        readiness === "collecting"
                          ? "rgba(184, 187, 38, 0.5)"
                          : "rgba(180, 160, 120, 0.3)",
                      animation: `signal-breathe-slow ${2 + i * 0.3}s ease-in-out infinite`,
                    }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

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

        {/* z-40: Classification inspector */}
        <ClassificationInspector />

        {/* z-50: Voice overlay */}
        <VoiceOverlay vl={vl} />

        {/* z-10: Keyboard hint bar — dismisses on first interaction */}
        <KeyboardHintBar />

      </div>
    </GroundStudioProvider>
    </ClassificationOverlayProvider>
  );
}
