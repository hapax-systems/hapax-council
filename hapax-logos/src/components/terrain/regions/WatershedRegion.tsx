import { Suspense, lazy, memo } from "react";
import { Region } from "../Region";
import { FlowSummary } from "../watershed/FlowSummary";
import { EventRippleStack } from "../watershed/EventRipple";
import { useSystemFlow } from "../../../hooks/useSystemFlow";
import { ProfilePanel } from "../../sidebar/ProfilePanel";
import { useSignals } from "../../../contexts/ClassificationOverlayContext";
import { useVisualLayer } from "../../../api/hooks";

const FlowPage = lazy(() =>
  import("../../../pages/FlowPage").then((m) => ({ default: m.FlowPage }))
);

export const WatershedRegion = memo(function WatershedRegion() {
  const flow = useSystemFlow();
  const { stimmungStance } = useSignals();
  const { data: vl } = useVisualLayer();
  const watershedEvents = vl?.watershed_events ?? [];

  return (
    <Region name="watershed" stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full flex flex-col min-h-0">
          {/* Surface: stance + counts + event ripples */}
          <div className="shrink-0">
            <FlowSummary
              stance={flow.stance}
              activeCount={flow.activeCount}
              totalCount={flow.totalCount}
              activeFlows={flow.activeFlows}
              totalFlows={flow.totalFlows}
            />
            <EventRippleStack events={watershedEvents} />
          </div>

          {/* Stratum: profile panel + event ripples */}
          {depth === "stratum" && (
            <div className="px-3 overflow-y-auto flex-1 min-h-0">
              <EventRippleStack events={watershedEvents} />
              <ProfilePanel />
            </div>
          )}

          {/* Core: full flow topology */}
          {depth === "core" && (
            <Suspense
              fallback={
                <div className="flex items-center justify-center h-full text-zinc-600 text-xs">
                  Loading flow topology...
                </div>
              }
            >
              <div className="flex-1 min-h-0 w-full" style={{ minHeight: "200px" }}>
                <FlowPage />
              </div>
            </Suspense>
          )}
        </div>
      )}
    </Region>
  );
});
