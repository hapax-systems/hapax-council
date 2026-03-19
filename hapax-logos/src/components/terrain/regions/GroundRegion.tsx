import { memo, useCallback, useState } from "react";
import { Region } from "../Region";
import { AmbientCanvas } from "../ground/AmbientCanvas";
import { TimeDisplay } from "../ground/TimeDisplay";
import { CameraPip } from "../ground/CameraPip";
import { CameraGrid } from "../ground/CameraGrid";
import { CameraHero } from "../ground/CameraHero";
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { PresenceIndicator } from "../ground/PresenceIndicator";
import { useSignals } from "../../../contexts/ClassificationOverlayContext";
import { useTerrain } from "../../../contexts/TerrainContext";
import type { VisualLayerState } from "../../../api/types";

interface GroundRegionProps {
  vl: VisualLayerState | undefined;
}

export const GroundRegion = memo(function GroundRegion({ vl }: GroundRegionProps) {
  const { signalsByRegion, stimmungStance, perception } = useSignals();
  const { setRegionDepth, focusRegion } = useTerrain();
  const groundSignals = signalsByRegion.ground;
  const [heroRole, setHeroRole] = useState("brio-operator");
  const [fxMode, setFxMode] = useState(false);
  const [smoothMode, setSmoothMode] = useState(false);

  /** CameraPip click → advance to stratum */
  const handlePipClick = useCallback(() => {
    focusRegion("ground");
    setRegionDepth("ground", "stratum");
  }, [focusRegion, setRegionDepth]);

  /** CameraGrid tile click → set hero + advance to core */
  const handleGridSelect = useCallback(
    (role: string) => {
      setHeroRole(role);
      focusRegion("ground");
      setRegionDepth("ground", "core");
    },
    [focusRegion, setRegionDepth],
  );

  return (
    <Region name="ground" stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full relative">
          {/* Surface: ambient canvas + time + camera pip */}
          <AmbientCanvas ambientText={vl?.ambient_text ?? ""} speed={vl?.ambient_params?.speed ?? 0.08} />
          <TimeDisplay
            activityLabel={vl?.activity_label ?? "present"}
            activityDetail={vl?.activity_detail ?? ""}
            displayState={vl?.display_state ?? "ambient"}
          />

          {/* Surface: small camera pip — bottom-right, above presence indicator */}
          {depth === "surface" && (
            <div className="absolute bottom-8 right-8 pointer-events-auto" style={{ zIndex: 4 }}>
              <CameraPip
                heroRole={heroRole}
                classificationDetections={vl?.classification_detections ?? []}
                onClick={handlePipClick}
              />
            </div>
          )}

          {/* Stratum: compact camera grid */}
          {depth === "stratum" && (
            <div className="absolute inset-0 top-16 overflow-y-auto p-4" style={{ zIndex: 5 }}>
              <CameraGrid
                classificationDetections={vl?.classification_detections ?? []}
                onSelectHero={handleGridSelect}
              />
            </div>
          )}

          {/* Core: hero camera fills region */}
          {depth === "core" && (
            <div className="absolute inset-0 overflow-hidden" style={{ zIndex: 5 }}>
              <CameraHero
                heroRole={heroRole}
                classificationDetections={vl?.classification_detections ?? []}
                onHeroChange={setHeroRole}
                fxMode={fxMode}
                smoothMode={smoothMode}
              />
            </div>
          )}

          {/* Presence indicator — bottom-right */}
          {perception && (
            <div className="absolute bottom-1.5 right-8 pointer-events-none" style={{ zIndex: 3 }}>
              <PresenceIndicator
                presenceScore={perception.presence_score}
                operatorPresent={perception.operator_present}
                interruptibility={perception.interruptibility_score}
                guestPresent={perception.guest_present}
              />
            </div>
          )}

          {/* Signal pips — bottom-left */}
          {groundSignals.length > 0 && (
            <SignalCluster
              signals={groundSignals}
              density={densityFromDepth(depth)}
              className={
                depth === "surface"
                  ? "absolute bottom-1.5 left-8 pointer-events-none"
                  : "absolute bottom-2 left-8"
              }
            />
          )}
        </div>
      )}
    </Region>
  );
});

// Re-export state for DetailPane
export { type GroundRegionProps };
