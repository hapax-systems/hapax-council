import { useConsentPrecedents } from "../../api/hooks";

export function PrecedentPanel() {
  const { data: precedents } = useConsentPrecedents();

  const items = Array.isArray(precedents) ? precedents : [];
  const recent = items.slice(-8).reverse();

  const authorityColor = (auth: string) => {
    if (auth === "operator") return "text-blue-400";
    if (auth === "agent") return "text-amber-400";
    return "text-zinc-500";
  };

  return (
    <div className="space-y-1 text-xs">
      <div className="flex justify-between">
        <span className="text-zinc-500">total precedents</span>
        <span className="text-zinc-300">{items.length}</span>
      </div>

      {recent.length > 0 ? (
        <div className="space-y-1">
          {recent.map((p: any, i: number) => (
            <div key={i} className="text-[10px] border-b border-zinc-800/20 pb-1">
              <div className="flex justify-between gap-2">
                <span className="text-zinc-400 flex-1 truncate">{p?.situation?.slice(0, 80) || p?.id || "—"}</span>
                <span className={`shrink-0 ${authorityColor(p?.authority || "")}`}>{p?.authority || "?"}</span>
              </div>
              {p?.axiom_id && (
                <div className="text-[10px] text-zinc-500">{p.axiom_id}</div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-zinc-600 text-[10px]">No precedents recorded</div>
      )}
    </div>
  );
}
