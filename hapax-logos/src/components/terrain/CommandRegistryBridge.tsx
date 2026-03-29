/**
 * Bridges GroundStudio and Detection contexts into the command registry.
 * Must be rendered inside GroundStudioProvider and ClassificationOverlayProvider.
 *
 * Uses synchronous state mirrors so query() returns post-execution state
 * without waiting for React re-render.
 */
import { useEffect, useRef } from "react";
import { useCommandRegistry } from "../../contexts/CommandRegistryContext";
import { useGroundStudio } from "../../contexts/GroundStudioContext";
import { useDetections } from "../../contexts/ClassificationOverlayContext";
import { useTerrain } from "../../contexts/TerrainContext";
import { useRecordingToggle } from "../../api/hooks";
import { registerStudioCommands, type StudioState } from "../../lib/commands/studio";
import { registerDetectionCommands, type DetectionState } from "../../lib/commands/detection";
import { selectEffect } from "../../components/studio/effectSources";
import { api } from "../../api/client";

function createMirror<T extends object>(initial: T) {
  let state = { ...initial };
  return {
    get: () => state,
    set: (patch: Partial<T>) => { state = { ...state, ...patch }; },
    sync: (fresh: T) => { state = { ...fresh }; },
  };
}

export function CommandRegistryBridge() {
  const registry = useCommandRegistry();
  const { smoothMode, setSmoothMode, activePreset, setActivePreset, setEffectSourceId } = useGroundStudio();
  const { detectionTier, setDetectionTier, detectionLayerVisible, setDetectionLayerVisible } =
    useDetections();
  const { regionDepths, setRegionDepth } = useTerrain();
  const recordingToggle = useRecordingToggle();

  const studioMirror = useRef(createMirror<StudioState>({
    smoothMode,
    activePreset: "",
    recording: false,
  })).current;

  const detectionMirror = useRef(createMirror<DetectionState>({
    tier: detectionTier as 1 | 2 | 3,
    visible: detectionLayerVisible,
  })).current;

  // Sync mirrors on every render
  studioMirror.sync({ smoothMode, activePreset: activePreset ?? "", recording: false });
  detectionMirror.sync({ tier: detectionTier as 1 | 2 | 3, visible: detectionLayerVisible });

  const depthsRef = useRef(regionDepths);
  depthsRef.current = regionDepths;

  useEffect(() => {
    registerStudioCommands(
      registry,
      () => studioMirror.get(),
      {
        setSmoothMode: (on: boolean) => {
          studioMirror.set({ smoothMode: on });
          setSmoothMode(on);
          if (on && depthsRef.current.ground !== "core") {
            setRegionDepth("ground", "core");
          }
        },
        setActivePreset: (name: string) => {
          studioMirror.set({ activePreset: name });
          setActivePreset(name);
          // Switch hero source to FX so the camera polls the GPU-processed output
          const fxSource = `fx-${name}`;
          setEffectSourceId(fxSource);
          selectEffect(fxSource);
          api.post(`/studio/presets/${name}/activate`).catch(() => {});
        },
        cyclePreset: (direction: "next" | "prev") => {
          api.post(`/studio/presets/cycle?direction=${direction}`).catch(
            () => {},
          );
        },
        setRecording: () => {
          recordingToggle.mutate(true);
        },
      },
    );

    registerDetectionCommands(
      registry,
      () => detectionMirror.get(),
      {
        setTier: (tier: number) => {
          detectionMirror.set({ tier: tier as 1 | 2 | 3 });
          setDetectionTier(tier as 1 | 2 | 3);
        },
        setVisible: (v: boolean) => {
          detectionMirror.set({ visible: v });
          setDetectionLayerVisible(v);
        },
      },
    );

    return () => {
      for (const p of [
        "studio.smooth.enable",
        "studio.smooth.disable",
        "studio.smooth.toggle",
        "studio.preset.activate",
        "studio.preset.cycle",
        "studio.recording.toggle",
      ]) {
        registry.unregister(p);
      }
      for (const p of ["studio.smoothMode", "studio.activePreset", "studio.recording"]) {
        registry.unregisterQuery(p);
      }
      for (const p of [
        "detection.tier.set",
        "detection.tier.cycle",
        "detection.visibility.toggle",
      ]) {
        registry.unregister(p);
      }
      for (const p of ["detection.tier", "detection.visible"]) {
        registry.unregisterQuery(p);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable refs, register once
  }, [registry]);

  return null;
}
