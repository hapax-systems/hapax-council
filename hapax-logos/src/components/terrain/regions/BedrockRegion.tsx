import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Region } from "../Region";
import { useHealth, useGovernanceHeartbeat, useCost } from "../../../api/hooks";
import { HealthPanel } from "../../sidebar/HealthPanel";
import { VramPanel } from "../../sidebar/VramPanel";
import { ContainersPanel } from "../../sidebar/ContainersPanel";
import { CostPanel } from "../../sidebar/CostPanel";
import { ConsentPanel } from "../../sidebar/ConsentPanel";
import { GovernancePanel } from "../../sidebar/GovernancePanel";
import { OverheadPanel } from "../../sidebar/OverheadPanel";
import { PrecedentPanel } from "../../sidebar/PrecedentPanel";
import { TimersPanel } from "../../sidebar/TimersPanel";
import { AccommodationPanel } from "../../sidebar/AccommodationPanel";
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { useOverlay } from "../../../contexts/ClassificationOverlayContext";

function BedrockSurface() {
  const { data: health } = useHealth();
  const { data: heartbeat } = useGovernanceHeartbeat();
  const { data: cost } = useCost();

  const score = heartbeat?.score ?? null;
  const axiomCount = heartbeat?.axiom_count ?? 5;
  const healthScore = health?.score ?? null;
  const healthTotal = health?.total ?? null;
  const stance = health?.summary?.stance ?? "unknown";
  const costPct = cost?.tax_percentage ?? null;

  return (
    <div className="h-full flex items-center gap-6 px-6">
      {/* Axiom dots */}
      <div className="flex gap-1.5" title="Axiom compliance">
        {Array.from({ length: axiomCount }).map((_, i) => {
          const axiomNames = ["single_user", "exec_function", "corp_boundary", "transparency", "mgmt_governance"];
          return (
          <div
            key={i}
            className="w-2 h-2 rounded-full"
            title={axiomNames[i] ?? `axiom-${i}`}
            style={{
              background:
                score === null
                  ? "#504945"
                  : score >= 0.8
                    ? "#b8bb26"
                    : score >= 0.5
                      ? "#fabd2f"
                      : "#fb4934",
            }}
          />
          );
        })}
      </div>

      {/* Health summary */}
      <div className="text-[10px] text-zinc-500">
        {healthScore !== null ? `${healthScore}/${healthTotal}` : "—"}
      </div>

      {/* Stance word */}
      <div
        className="text-[10px] uppercase tracking-[0.3em]"
        style={{
          color:
            stance === "healthy"
              ? "#b8bb26"
              : stance === "degraded"
                ? "#fabd2f"
                : stance === "critical"
                  ? "#fb4934"
                  : "#504945",
        }}
      >
        {stance === "unknown" ? "—" : stance}
      </div>

      {/* Cost tax % */}
      {costPct !== null && (
        <div className="text-[10px] text-zinc-600 ml-auto">{costPct.toFixed(1)}% tax</div>
      )}
    </div>
  );
}

export function BedrockRegion() {
  const { signalsByRegion, stimmungStance } = useOverlay();
  const bedrockSignals = signalsByRegion.bedrock;
  const [accommOpen, setAccommOpen] = useState(false);

  return (
    <Region name="bedrock" className="col-span-3" stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full relative">
          {depth === "surface" && <BedrockSurface />}
          {depth !== "surface" && (
            <div className="h-full overflow-y-auto p-3">
              <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                <HealthPanel />
                <VramPanel />
                <ContainersPanel />
                <CostPanel />
                <ConsentPanel />
                <GovernancePanel />
                <OverheadPanel />
                <PrecedentPanel />
                <TimersPanel />
              </div>
              {/* Accommodations — collapsible, governance-adjacent */}
              <div className="mt-3">
                <button
                  onClick={() => setAccommOpen(!accommOpen)}
                  className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
                >
                  {accommOpen ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )}
                  Accommodations
                </button>
                {accommOpen && (
                  <div className="mt-2">
                    <AccommodationPanel />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Signal pips — bottom-right */}
          {bedrockSignals.length > 0 && (
            <SignalCluster
              signals={bedrockSignals}
              density={densityFromDepth(depth)}
              className={
                depth === "surface"
                  ? "absolute bottom-1.5 right-8 pointer-events-none"
                  : "absolute top-2 right-8"
              }
            />
          )}
        </div>
      )}
    </Region>
  );
}
