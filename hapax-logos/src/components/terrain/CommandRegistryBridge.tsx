/**
 * Bridges GroundStudio and Detection contexts into the command registry.
 * Must be rendered inside GroundStudioProvider and ClassificationOverlayProvider.
 */
import { useEffect, useRef } from "react";
import { useCommandRegistry } from "../../contexts/CommandRegistryContext";
import { useGroundStudio } from "../../contexts/GroundStudioContext";
import { useDetections } from "../../contexts/ClassificationOverlayContext";
import { useTerrain } from "../../contexts/TerrainContext";
import { useRecordingToggle } from "../../api/hooks";
import { registerStudioCommands } from "../../lib/commands/studio";
import { registerDetectionCommands } from "../../lib/commands/detection";

export function CommandRegistryBridge() {
  const registry = useCommandRegistry();
  const { smoothMode, setSmoothMode } = useGroundStudio();
  const { detectionTier, setDetectionTier, detectionLayerVisible, setDetectionLayerVisible } =
    useDetections();
  const { regionDepths, setRegionDepth } = useTerrain();
  const recordingToggle = useRecordingToggle();

  // Refs for values that change frequently
  const smoothRef = useRef(smoothMode);
  smoothRef.current = smoothMode;
  const tierRef = useRef(detectionTier);
  tierRef.current = detectionTier;
  const visibleRef = useRef(detectionLayerVisible);
  visibleRef.current = detectionLayerVisible;
  const depthsRef = useRef(regionDepths);
  depthsRef.current = regionDepths;

  useEffect(() => {
    registerStudioCommands(
      registry,
      () => ({
        smoothMode: smoothRef.current,
        activePreset: "",
        recording: false,
      }),
      {
        setSmoothMode: (on: boolean) => {
          setSmoothMode(on);
          if (on && depthsRef.current.ground !== "core") {
            setRegionDepth("ground", "core");
          }
        },
        setActivePreset: (name: string) => {
          fetch(`/api/studio/presets/${name}/activate`, { method: "POST" }).catch(() => {});
        },
        cyclePreset: (direction: "next" | "prev") => {
          fetch(`/api/studio/presets/cycle?direction=${direction}`, { method: "POST" }).catch(
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
      () => ({
        tier: tierRef.current as 1 | 2 | 3,
        visible: visibleRef.current,
      }),
      {
        setTier: setDetectionTier,
        setVisible: setDetectionLayerVisible,
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
