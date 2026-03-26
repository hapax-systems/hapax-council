import { memo, useCallback } from "react";
import { Region } from "../Region";
import { AmbientCanvas } from "../ground/AmbientCanvas";
import { TimeDisplay } from "../ground/TimeDisplay";
import { CameraPip } from "../ground/CameraPip";
import { CameraGrid } from "../ground/CameraGrid";
import { CameraHero } from "../ground/CameraHero";
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { PresenceIndicator } from "../ground/PresenceIndicator";
import { GroundNudgePills } from "../ground/GroundNudgePills";
import { useSignals } from "../../../contexts/ClassificationOverlayContext";
import { useTerrainActions, useTerrainDisplay } from "../../../contexts/TerrainContext";
import { useGroundStudio } from "../../../contexts/GroundStudioContext";
import { useWorkingMode } from "../../../api/hooks";
import { FortressDashboard } from "../fortress/FortressDashboard";
import type { VisualLayerState } from "../../../api/types";

interface GroundRegionProps {
  vl: VisualLayerState | undefined;
}

export const GroundRegion = memo(function GroundRegion({ vl }: GroundRegionProps) {
  const { signalsByRegion, stimmungStance, perception } = useSignals();
  const { setRegionDepth, focusRegion } = useTerrainActions();
  const { regionDepths } = useTerrainDisplay();
  const groundSignals = signalsByRegion.ground;
  const {
    heroRole, setHeroRole,
    effectSourceId, smoothMode,
  } = useGroundStudio();
  const { data: workingMode } = useWorkingMode();
  const isFortress = workingMode?.mode === "fortress";

  /** CameraPip click -> advance to stratum */
  const handlePipClick = useCallback(() => {
    focusRegion("ground");
    setRegionDepth("ground", "stratum");
  }, [focusRegion, setRegionDepth]);

  /** CameraGrid tile click -> set hero + advance to core */
  const handleGridSelect = useCallback(
    (role: string) => {
      setHeroRole(role);
      focusRegion("ground");
      setRegionDepth("ground", "core");
    },
    [focusRegion, setRegionDepth, setHeroRole],
  );

  return (
    <Region name="ground" style={regionDepths.ground === "core" ? { zIndex: 1 } : undefined} stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full relative">
          {/* Fortress mode: show fortress dashboard instead of cameras */}
          {isFortress && <FortressDashboard depth={depth} />}

          {/* Surface: ambient canvas + time + camera pip */}
          <AmbientCanvas
            ambientText={vl?.ambient_text ?? ""}
            secondaryText={vl?.secondary_ambient_text ?? ""}
            speed={vl?.ambient_params?.speed ?? 0.08}
          />
          <TimeDisplay
            activityLabel={vl?.activity_label ?? "present"}
            activityDetail={vl?.activity_detail ?? ""}
            displayState={vl?.display_state ?? "ambient"}
          />

          {/* Surface: faint nudge pills — bottom-left, above ambient text */}
          {depth === "surface" && (
            <div className="absolute bottom-20 left-8 pointer-events-none" style={{ zIndex: 2 }}>
              <GroundNudgePills />
            </div>
          )}

          {/* Surface: small camera pip -- bottom-right, above presence indicator */}
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
                effectSourceId={effectSourceId}
                smoothMode={smoothMode}
              />
            </div>
          )}

          {/* Presence indicator -- bottom-right */}
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

          {/* Signal pips -- bottom-left */}
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
