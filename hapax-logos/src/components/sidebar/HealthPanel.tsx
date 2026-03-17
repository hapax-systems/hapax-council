import { useState } from "react";
import { useHealth } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { DetailModal } from "../shared/DetailModal";
import { StatusBadge } from "../shared/StatusBadge";
import { SidebarSection } from "./SidebarSection";
import { HealthHistoryChart } from "./HealthHistoryChart";
import { formatAge } from "../../utils";
import { Wrench } from "lucide-react";

export function HealthPanel() {
  const { data: health, dataUpdatedAt } = useHealth();
  const { requestAgentRun } = useAgentRun();
  const [detailOpen, setDetailOpen] = useState(false);

  return (
    <>
      <SidebarSection title="Health" onClick={() => setDetailOpen(true)} clickable loading={!health} age={health ? formatAge(dataUpdatedAt) : undefined}>
        {health && (
          <>
            <div className="flex items-center gap-2">
              <StatusBadge status={health.overall_status} />
              <span className="text-zinc-400">
                {health.healthy}/{health.total_checks} ({health.duration_ms}ms)
              </span>
            </div>
            {health.failed_checks.map((c) => (
              <p key={c} className="text-red-400">{c}</p>
            ))}
          </>
        )}
      </SidebarSection>

      <DetailModal title="Health Detail" open={detailOpen} onClose={() => setDetailOpen(false)}>
        {health ? (
          <div className="space-y-3 text-xs">
            <div className="flex items-center gap-2">
              <StatusBadge status={health.overall_status} />
              <span className="text-zinc-400">
                {health.healthy} healthy, {health.degraded} degraded, {health.failed} failed
              </span>
            </div>
            <p className="text-zinc-500">Duration: {health.duration_ms}ms</p>
            <p className="text-zinc-500">Timestamp: {health.timestamp}</p>
            {health.failed_checks.length > 0 && (
              <div>
                <h3 className="mb-1 font-medium text-red-400">Failed Checks</h3>
                <ul className="space-y-1">
                  {health.failed_checks.map((c) => (
                    <li key={c} className="text-red-400">- {c}</li>
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
                className="flex items-center gap-1.5 rounded border border-green-500/30 bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-400 hover:bg-green-500/20 active:scale-[0.97]"
              >
                <Wrench className="h-3.5 w-3.5" />
                Auto-fix
              </button>
            )}
            <div>
              <h3 className="mb-2 font-medium text-zinc-300">7-Day History</h3>
              <HealthHistoryChart />
            </div>
          </div>
        ) : (
          <p className="text-zinc-500">No health data available.</p>
        )}
      </DetailModal>
    </>
  );
}
