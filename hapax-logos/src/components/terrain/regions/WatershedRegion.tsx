import { Region } from "../Region";
import { FlowSummary } from "../watershed/FlowSummary";
import { useSystemFlow } from "../../../hooks/useSystemFlow";
import { ProfilePanel } from "../../sidebar/ProfilePanel";

export function WatershedRegion() {
  const flow = useSystemFlow();

  return (
    <Region name="watershed">
      {(depth) => (
        <div className="h-full">
          {/* Surface: stance + counts */}
          <FlowSummary
            stance={flow.stance}
            activeCount={flow.activeCount}
            totalCount={flow.totalCount}
            activeFlows={flow.activeFlows}
            totalFlows={flow.totalFlows}
          />

          {/* Stratum: profile + compact topology info */}
          {depth !== "surface" && (
            <div className="px-3 overflow-y-auto" style={{ maxHeight: "calc(100% - 60px)" }}>
              <ProfilePanel />
              {depth === "core" && (
                <div className="mt-2 text-[10px] text-zinc-600">
                  Full flow topology available at /flow
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
