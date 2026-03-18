import { useConsentContracts, useConsentCoverage } from "../../api/hooks";

export function ConsentPanel() {
  const { data: contracts } = useConsentContracts();
  const { data: coverage } = useConsentCoverage();

  const items = Array.isArray(contracts) ? contracts : [];
  const active = items.filter((c: any) => c?.active);
  const revoked = items.filter((c: any) => !c?.active);
  const cov = coverage as any;

  return (
    <div className="space-y-2 text-xs">
      <div className="flex justify-between">
        <span className="text-zinc-500">contracts</span>
        <span className="text-zinc-300">
          <span className="text-emerald-400">{active.length}</span>
          {revoked.length > 0 && <span className="text-zinc-600"> / {revoked.length} revoked</span>}
        </span>
      </div>
      {active.map((c: any, i: number) => (
        <div key={i} className="rounded bg-zinc-800/50 px-2 py-1 text-[10px]">
          <div className="text-zinc-300">{c?.parties?.[1] || "unknown"}</div>
          <div className="text-zinc-600">{Array.isArray(c?.scope) ? c.scope.join(", ") : String(c?.scope || "")}</div>
        </div>
      ))}
      {items.length === 0 && (
        <div className="text-zinc-600 text-[10px]">No consent contracts established</div>
      )}
      {cov && typeof cov === "object" && (
        <div className="flex justify-between text-[10px]">
          <span className="text-zinc-500">coverage</span>
          <span className="text-zinc-400">{cov.coverage_ratio != null ? `${(cov.coverage_ratio * 100).toFixed(0)}%` : "—"}</span>
        </div>
      )}
    </div>
  );
}
