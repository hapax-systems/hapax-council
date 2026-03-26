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
import { ClassificationOverlayProvider, useDetections } from "../../contexts/ClassificationOverlayContext";
import type { DetectionTier } from "../studio/DetectionOverlay";
import { GroundStudioProvider, useGroundStudio } from "../../contexts/GroundStudioContext";
import { PRESETS } from "../studio/compositePresets";
import { useRecordingToggle } from "../../api/hooks";
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

/** Keyboard handler for detection tier/visibility (must be inside ClassificationOverlayProvider). */
function DetectionKeyboardHandler() {
  const { detectionTier, setDetectionTier, detectionLayerVisible, setDetectionLayerVisible } =
    useDetections();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)
        return;

      if (e.key === "d" && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        e.preventDefault();
        const next = ((detectionTier % 3) + 1) as DetectionTier;
        setDetectionTier(next);
      } else if (e.key === "D" && e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setDetectionLayerVisible(!detectionLayerVisible);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detectionTier, setDetectionTier, detectionLayerVisible, setDetectionLayerVisible]);

  return null;
}

/** URL param sync for studio state (must be inside GroundStudioProvider). */
function StudioParamSync() {
  const { setCompositeMode, setSmoothMode, setPresetIdx, setEffectSourceId } = useGroundStudio();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const presetName = params.get("preset");
    const source = params.get("source");
    const hls = params.get("hls");

    if (presetName) {
      const idx = PRESETS.findIndex(p => p.name.toLowerCase() === presetName.toLowerCase());
      if (idx >= 0) {
        setPresetIdx(idx);
        setCompositeMode(true);
      }
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

/** Keyboard shortcuts for studio controls (must be inside GroundStudioProvider). */
function StudioKeyboardHandler() {
  const { focusedRegion, regionDepths, setRegionDepth } = useTerrain();
  const {
    compositeMode, setCompositeMode,
    smoothMode, setSmoothMode,
    presetIdx, setPresetIdx,
    setEffectOverrides,
  } = useGroundStudio();
  const recordingToggle = useRecordingToggle();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)
        return;
      if (focusedRegion !== "ground") return;

      // E: cycle mode (Live → FX → HLS), auto-advance to core for FX/HLS
      if (e.key === "e" && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        e.preventDefault();
        if (!compositeMode && !smoothMode) {
          setCompositeMode(true); setSmoothMode(false);
          if (regionDepths.ground !== "core") setRegionDepth("ground", "core");
        } else if (compositeMode && !smoothMode) {
          setCompositeMode(false); setSmoothMode(true);
        } else {
          setCompositeMode(false); setSmoothMode(false);
        }
        return;
      }

      // R: toggle recording
      if (e.key === "r" && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        e.preventDefault();
        recordingToggle.mutate(true); // toggle handled server-side
        return;
      }

      // [ / ]: previous / next preset (FX mode only)
      if (compositeMode && (e.key === "[" || e.key === "]") && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const delta = e.key === "]" ? 1 : -1;
        const next = (presetIdx + delta + PRESETS.length) % PRESETS.length;
        setPresetIdx(next);
        setEffectOverrides(null);
        return;
      }

      // 1-9, 0: select preset by number (FX mode only)
      if (compositeMode && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const num = e.key === "0" ? 10 : parseInt(e.key, 10);
        if (num >= 1 && num <= 10 && num <= PRESETS.length) {
          e.preventDefault();
          setPresetIdx(num - 1);
          setEffectOverrides(null);
          return;
        }
        // Shift+1-8: presets 11-18
        if (e.shiftKey) {
          const shiftNum = "!@#$%^&*".indexOf(e.key);
          if (shiftNum >= 0 && shiftNum + 11 <= PRESETS.length) {
            e.preventDefault();
            setPresetIdx(shiftNum + 10);
            setEffectOverrides(null);
          }
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedRegion, compositeMode, smoothMode, presetIdx, setCompositeMode, setSmoothMode, setPresetIdx, setEffectOverrides, recordingToggle, regionDepths, setRegionDepth]);

  return null;
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
    <DetectionKeyboardHandler />
    {/* <ModifierShortcutOverlay /> */}
    <GroundStudioProvider>
      <StudioParamSync />
      <StudioKeyboardHandler />
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
