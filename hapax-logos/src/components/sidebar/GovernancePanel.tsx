import { useGovernanceHeartbeat, useGovernanceCoverage, useGovernanceCarriers } from "../../api/hooks";

export function GovernancePanel() {
  const { data: heartbeat } = useGovernanceHeartbeat();
  const { data: coverage } = useGovernanceCoverage();
  const { data: carriers } = useGovernanceCarriers();

  const hb = heartbeat as any;
  const cov = coverage as any;
  const carr = carriers as any;

  const score = hb?.score ?? null;
  const scoreColor = score === null ? "text-zinc-600"
    : score >= 0.8 ? "text-fuchsia-400"
    : score >= 0.5 ? "text-amber-400"
    : "text-red-400";

  return (
    <div className="space-y-1 text-xs">
      <div className="flex justify-between">
        <span className="text-zinc-500">heartbeat</span>
        <span className={`text-zinc-200 ${scoreColor}`}>{score != null ? score.toFixed(2) : "—"}</span>
      </div>

      {cov && typeof cov === "object" && (
        <div className="border-t border-zinc-800/30 pt-1 space-y-0.5">
          {Object.entries(cov.principals ?? cov).map(([pid, val]: [string, any]) => (
            <div key={pid} className="flex justify-between text-[10px]">
              <span className="text-zinc-500 flex-1 truncate">{pid}</span>
              <span className="text-zinc-400 shrink-0 ml-2">{typeof val === "number" ? `${(val * 100).toFixed(0)}%` : String(val?.coverage ?? val)}</span>
            </div>
          ))}
        </div>
      )}

      {carr && typeof carr === "object" && (
        <div className="flex justify-between text-[10px]">
          <span className="text-zinc-500">carrier facts</span>
          <span className="text-zinc-400">{carr.total_facts ?? carr.count ?? "—"}</span>
        </div>
      )}
    </div>
  );
}
