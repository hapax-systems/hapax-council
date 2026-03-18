import { useCallback } from "react";
import { Region } from "../Region";
import { AgentSummary } from "../field/AgentSummary";
import { FreshnessPanel } from "../../sidebar/FreshnessPanel";
import { ScoutPanel } from "../../sidebar/ScoutPanel";
import { DriftPanel } from "../../sidebar/DriftPanel";
import { ManagementPanel } from "../../sidebar/ManagementPanel";
import { AgentGrid } from "../../dashboard/AgentGrid";
import type { AgentInfo } from "../../../api/types";

export function FieldRegion() {
  const handleRun = useCallback((_agent: AgentInfo, _flags: string[]) => {
    // Agent run handled by AgentRunContext at layout level
  }, []);

  return (
    <Region name="field">
      {(depth) => (
        <div className="h-full">
          {/* Surface: compact summaries */}
          <div className="px-4 py-2">
            <AgentSummary />
          </div>

          {depth === "surface" && (
            <div className="px-4">
              <FreshnessPanel />
            </div>
          )}

          {/* Stratum: panels */}
          {depth === "stratum" && (
            <div className="px-3 overflow-y-auto" style={{ maxHeight: "calc(100% - 40px)" }}>
              <FreshnessPanel />
              <ScoutPanel />
              <DriftPanel />
              <ManagementPanel />
              <AgentGrid onRun={handleRun} />
            </div>
          )}

          {/* Core: full agent view */}
          {depth === "core" && (
            <div className="px-3 overflow-y-auto" style={{ maxHeight: "calc(100% - 40px)" }}>
              <ScoutPanel />
              <DriftPanel />
              <ManagementPanel />
              <AgentGrid onRun={handleRun} />
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
