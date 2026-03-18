import { useCallback, useState } from "react";
import { Region } from "../Region";
import { AgentSummary } from "../field/AgentSummary";
import { FreshnessPanel } from "../../sidebar/FreshnessPanel";
import { ScoutPanel } from "../../sidebar/ScoutPanel";
import { DriftPanel } from "../../sidebar/DriftPanel";
import { ManagementPanel } from "../../sidebar/ManagementPanel";
import { AgentGrid } from "../../dashboard/AgentGrid";
import { PerceptionCanvas } from "../../perception/PerceptionCanvas";
import { PerceptionSidebar } from "../../perception/PerceptionSidebar";
import { ClassificationOverlayProvider } from "../../../contexts/ClassificationOverlayContext";
import { useAgentRun } from "../../../contexts/AgentRunContext";
import type { SignalCategory } from "../../../contexts/ClassificationOverlayContext";
import type { AgentInfo } from "../../../api/types";

export function FieldRegion() {
  const { runAgent } = useAgentRun();
  const [activeZone, setActiveZone] = useState<SignalCategory | null>(null);

  const handleRun = useCallback(
    (agent: AgentInfo, flags: string[]) => {
      runAgent(agent.name, flags);
    },
    [runAgent],
  );

  return (
    <Region name="field">
      {(depth) => (
        <div className="h-full flex flex-col min-h-0">
          {/* Surface: compact summaries */}
          <div className="px-4 py-2 shrink-0">
            <AgentSummary />
          </div>

          {depth === "surface" && (
            <div className="px-4 shrink-0">
              <FreshnessPanel />
            </div>
          )}

          {/* Stratum: panels */}
          {depth === "stratum" && (
            <div className="px-3 overflow-y-auto flex-1 min-h-0">
              <FreshnessPanel />
              <ScoutPanel />
              <DriftPanel />
              <ManagementPanel />
              <AgentGrid onRun={handleRun} />
            </div>
          )}

          {/* Core: perception view */}
          {depth === "core" && (
            <ClassificationOverlayProvider>
              <div className="flex h-full min-h-0">
                <PerceptionCanvas activeZone={activeZone} onZoneClick={setActiveZone} />
                <PerceptionSidebar activeZone={activeZone} onZoneSelect={setActiveZone} />
              </div>
            </ClassificationOverlayProvider>
          )}
        </div>
      )}
    </Region>
  );
}
