import { useDrift } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { SidebarSection } from "./SidebarSection";
import { StatusBadge } from "../shared/StatusBadge";
import { formatAge } from "../../utils";
import { Wrench } from "lucide-react";

export function DriftPanel() {
  const { data: drift, dataUpdatedAt } = useDrift();
  const { requestAgentRun } = useAgentRun();

  if (!drift) return <SidebarSection title="Drift" loading>{null}</SidebarSection>;
  if (drift.drift_count === 0 && drift.hygiene_count === 0) return null;

  return (
    <SidebarSection title="Drift" age={formatAge(dataUpdatedAt)}>
      <p>{drift.drift_count} findings · {drift.report_age_h.toFixed(0)}h ago</p>
      {drift.hygiene_count > 0 && (
        <p className="text-zinc-600 text-[10px]">+ {drift.hygiene_count} coverage gaps</p>
      )}
      {drift.items.slice(0, 3).map((d, i) => (
        <div key={`${d.doc_file}-${i}`} className="flex items-center gap-1.5">
          <StatusBadge status={d.severity} />
          <span className="truncate text-zinc-400">{d.description}</span>
        </div>
      ))}
      <button
        onClick={() => requestAgentRun({ agent: "drift_detector", flags: { "--fix": "", "--apply": "" } })}
        className="mt-2 flex items-center gap-1.5 rounded border border-yellow-500/30 bg-yellow-500/10 px-2.5 py-1.5 text-xs font-medium text-yellow-400 hover:bg-yellow-500/20 active:scale-[0.97]"
      >
        <Wrench className="h-3.5 w-3.5" />
        Fix drift
      </button>
    </SidebarSection>
  );
}
