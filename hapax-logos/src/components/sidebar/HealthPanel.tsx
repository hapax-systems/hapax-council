import { useState } from "react";
import { useHealth } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { DetailModal } from "../shared/DetailModal";
import { SidebarSection } from "./SidebarSection";
import { HealthHistoryChart } from "./HealthHistoryChart";
import { formatAge } from "../../utils";
import { Wrench } from "lucide-react";

const STATUS_COLOR: Record<string, string> = {
  healthy: "text-green-400",
  degraded: "text-amber-400",
  failed: "text-red-400",
};

function healthSeverity(status?: string): "nominal" | "degraded" | "critical" | undefined {
  if (status === "failed") return "critical";
  if (status === "degraded") return "degraded";
  return undefined;
}

export function HealthPanel() {
  const { data: health, dataUpdatedAt } = useHealth();
  const { requestAgentRun } = useAgentRun();
  const [detailOpen, setDetailOpen] = useState(false);

  return (
    <>
      <SidebarSection
        title="Health"
        onClick={() => setDetailOpen(true)}
        clickable
        loading={!health}
        age={health ? formatAge(dataUpdatedAt) : undefined}
        severity={health ? healthSeverity(health.overall_status) : undefined}
      >
        {health && (
          <>
            <div className="flex items-center gap-2">
              <span className={STATUS_COLOR[health.overall_status] ?? "text-zinc-500"}>
                {health.overall_status}
              </span>
              <span className="text-zinc-500">
                {health.healthy}/{health.total_checks}
              </span>
            </div>
            {health.failed_checks.map((c) => (
              <p key={c} className="text-red-400 text-[10px]">{c}</p>
            ))}
          </>
        )}
      </SidebarSection>

      <DetailModal title="Health Detail" open={detailOpen} onClose={() => setDetailOpen(false)}>
        {health ? (
          <div className="space-y-3 text-xs">
            <div className="flex items-center gap-2">
              <span className={STATUS_COLOR[health.overall_status] ?? "text-zinc-500"}>
                {health.overall_status}
              </span>
              <span className="text-zinc-500">
                {health.healthy} healthy, {health.degraded} degraded, {health.failed} failed — {health.duration_ms}ms
              </span>
            </div>
            {health.failed_checks.length > 0 && (
              <div>
                <h3 className="mb-1 text-[11px] font-semibold text-red-400">Failed Checks</h3>
                <ul className="space-y-1">
                  {health.failed_checks.map((c) => (
                    <li key={c} className="text-red-400 text-[10px]">{c}</li>
                  ))}
                </ul>
              </div>
            )}
            {health.failed > 0 && (
              <button
                onClick={() => {
                  setDetailOpen(false);
                  requestAgentRun({ agent: "health_monitor", flags: { "--fix": "" } });
                }}
                className="flex items-center gap-1.5 rounded-sm border border-zinc-700 px-2 py-1 text-[10px] text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 active:scale-[0.97]"
              >
                <Wrench className="h-3 w-3" />
                Auto-fix
              </button>
            )}
            <div>
              <h3 className="mb-2 text-[11px] font-semibold text-zinc-500">7-Day History</h3>
              <HealthHistoryChart />
            </div>
          </div>
        ) : (
          <p className="text-zinc-600 text-[10px]">No health data available.</p>
        )}
      </DetailModal>
    </>
  );
}
