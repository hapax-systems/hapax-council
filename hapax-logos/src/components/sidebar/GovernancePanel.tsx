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
    : score >= 0.8 ? "text-emerald-400"
    : score >= 0.5 ? "text-amber-400"
    : "text-red-400";

  return (
    <div className="space-y-2 text-xs">
      <div className="flex justify-between">
        <span className="text-zinc-500">heartbeat</span>
        <span className={scoreColor}>{score != null ? score.toFixed(2) : "—"}</span>
      </div>

      {cov && typeof cov === "object" && (
        <>
          {Object.entries(cov.principals ?? cov).map(([pid, val]: [string, any]) => (
            <div key={pid} className="flex justify-between text-[10px]">
              <span className="text-zinc-500 truncate max-w-[60%]">{pid}</span>
              <span className="text-zinc-400">{typeof val === "number" ? `${(val * 100).toFixed(0)}%` : String(val?.coverage ?? val)}</span>
            </div>
          ))}
        </>
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
