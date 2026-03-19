import { memo, useCallback, useState } from "react";
import { Region } from "../Region";
import { AgentSummary } from "../field/AgentSummary";
import { FreshnessPanel } from "../../sidebar/FreshnessPanel";
import { ScoutPanel } from "../../sidebar/ScoutPanel";
import { DriftPanel } from "../../sidebar/DriftPanel";
import { ManagementPanel } from "../../sidebar/ManagementPanel";
import { AgentGrid } from "../../dashboard/AgentGrid";
import { PerceptionCanvas } from "../../perception/PerceptionCanvas";
import { PerceptionSidebar } from "../../perception/PerceptionSidebar";
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { OperatorVitals } from "../field/OperatorVitals";
import { useSignals, type SignalCategory } from "../../../contexts/ClassificationOverlayContext";
import { useAgentRun } from "../../../contexts/AgentRunContext";
import type { AgentInfo } from "../../../api/types";

export const FieldRegion = memo(function FieldRegion() {
  const { runAgent } = useAgentRun();
  const { signalsByRegion, stimmungStance, visualLayer } = useSignals();
  const [activeZone, setActiveZone] = useState<SignalCategory | null>(null);
  const fieldSignals = signalsByRegion.field;
  const biometrics = visualLayer?.biometrics ?? null;

  const handleRun = useCallback(
    (agent: AgentInfo, flags: string[]) => {
      runAgent(agent.name, flags);
    },
    [runAgent],
  );

  return (
    <Region name="field" stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full flex flex-col min-h-0 relative">
          {/* Surface: compact summaries */}
          <div className="px-4 py-2 shrink-0">
            <AgentSummary />
          </div>

          {depth === "surface" && (
            <div className="px-4 shrink-0">
              <FreshnessPanel />
              {biometrics && (biometrics.heart_rate_bpm > 0 || biometrics.phone_connected) && (
                <div className="mt-1">
                  <OperatorVitals biometrics={biometrics} />
                </div>
              )}
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
            <div className="flex h-full min-h-0">
              <PerceptionCanvas activeZone={activeZone} onZoneClick={setActiveZone} />
              <PerceptionSidebar activeZone={activeZone} onZoneSelect={setActiveZone} />
            </div>
          )}

          {/* Signal pips — top-right */}
          {fieldSignals.length > 0 && (
            <SignalCluster
              signals={fieldSignals}
              density={densityFromDepth(depth)}
              className={
                depth === "surface"
                  ? "absolute top-2 right-8 pointer-events-none"
                  : "absolute top-2 right-8"
              }
            />
          )}
        </div>
      )}
    </Region>
  );
});
