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
      <div className="flex gap-1.5">
        {Array.from({ length: axiomCount }).map((_, i) => (
          <div
            key={i}
            className="w-2 h-2 rounded-full"
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
        ))}
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
        {stance}
      </div>

      {/* Cost tax % */}
      {costPct !== null && (
        <div className="text-[10px] text-zinc-600 ml-auto">{costPct.toFixed(1)}% tax</div>
      )}
    </div>
  );
}

export function BedrockRegion() {
  return (
    <Region name="bedrock" className="col-span-3">
      {(depth) => (
        <div className="h-full">
          {depth === "surface" && <BedrockSurface />}
          {depth !== "surface" && (
            <div className="h-full overflow-y-auto p-3">
              <div className="grid grid-cols-4 gap-3">
                <HealthPanel />
                <VramPanel />
                <ContainersPanel />
                <CostPanel />
                <ConsentPanel />
                <GovernancePanel />
                <OverheadPanel />
                <PrecedentPanel />
              </div>
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
