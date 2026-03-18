import { Suspense, lazy } from "react";
import { Region } from "../Region";
import { AmbientCanvas } from "../ground/AmbientCanvas";
import { TimeDisplay } from "../ground/TimeDisplay";
import { AccommodationPanel } from "../../sidebar/AccommodationPanel";
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { PresenceIndicator } from "../ground/PresenceIndicator";
import { useOverlay } from "../../../contexts/ClassificationOverlayContext";
import type { useVisualLayerPoll } from "../../../hooks/useVisualLayer";

const StudioPage = lazy(() =>
  import("../../../pages/StudioPage").then((m) => ({ default: m.StudioPage }))
);

interface GroundRegionProps {
  vl: ReturnType<typeof useVisualLayerPoll>;
}

export function GroundRegion({ vl }: GroundRegionProps) {
  const { signalsByRegion, stimmungStance, perception } = useOverlay();
  const groundSignals = signalsByRegion.ground;

  return (
    <Region name="ground" stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full relative">
          {/* Surface: ambient canvas + time (SignalZones replaced by SignalCluster) */}
          <AmbientCanvas ambientText={vl.ambientText} speed={vl.ambient.speed} />
          <TimeDisplay
            activityLabel={vl.activityLabel}
            activityDetail={vl.activityDetail}
            displayState={vl.state}
          />

          {/* Stratum: accommodation panel */}
          {depth === "stratum" && (
            <div className="absolute inset-0 top-16 overflow-y-auto p-4" style={{ zIndex: 5 }}>
              <AccommodationPanel />
            </div>
          )}

          {/* Core: studio live grid */}
          {depth === "core" && (
            <div className="absolute inset-0 overflow-hidden" style={{ zIndex: 5 }}>
              <Suspense
                fallback={
                  <div className="flex items-center justify-center h-full text-zinc-600 text-xs">
                    Loading studio...
                  </div>
                }
              >
                <StudioPage />
              </Suspense>
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
}
