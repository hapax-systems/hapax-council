import { Suspense, lazy } from "react";
import { Region } from "../Region";
import { FlowSummary } from "../watershed/FlowSummary";
import { useSystemFlow } from "../../../hooks/useSystemFlow";
import { ProfilePanel } from "../../sidebar/ProfilePanel";
import { useOverlay } from "../../../contexts/ClassificationOverlayContext";

const FlowPage = lazy(() =>
  import("../../../pages/FlowPage").then((m) => ({ default: m.FlowPage }))
);

export function WatershedRegion() {
  const flow = useSystemFlow();
  const { stimmungStance } = useOverlay();

  return (
    <Region name="watershed" stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full flex flex-col min-h-0">
          {/* Surface: stance + counts */}
          <div className="shrink-0">
            <FlowSummary
              stance={flow.stance}
              activeCount={flow.activeCount}
              totalCount={flow.totalCount}
              activeFlows={flow.activeFlows}
              totalFlows={flow.totalFlows}
            />
          </div>

          {/* Stratum: profile panel */}
          {depth === "stratum" && (
            <div className="px-3 overflow-y-auto flex-1 min-h-0">
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
}
