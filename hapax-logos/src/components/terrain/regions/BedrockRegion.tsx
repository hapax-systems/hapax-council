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
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { useOverlay } from "../../../contexts/ClassificationOverlayContext";

function BedrockSurface() {
  const { data: health } = useHealth();
  const { data: heartbeat } = useGovernanceHeartbeat();
  const { data: cost } = useCost();

  const hb = heartbeat as any;
  const score = hb?.score ?? null;
  const axiomCount = hb?.axiom_count ?? 5;
  const healthScore = (health as any)?.score ?? null;
  const healthTotal = (health as any)?.total ?? null;
  const stance = (health as any)?.summary?.stance ?? "unknown";
  const costPct = (cost as any)?.tax_percentage ?? null;

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
