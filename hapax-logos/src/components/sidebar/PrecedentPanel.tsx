import { useConsentPrecedents } from "../../api/hooks";

export function PrecedentPanel() {
  const { data: precedents } = useConsentPrecedents();

  const items = Array.isArray(precedents) ? precedents : [];
  const recent = items.slice(-8).reverse();

  const authorityColor = (auth: string) => {
    if (auth === "operator") return "text-emerald-400";
    if (auth === "agent") return "text-amber-400";
    return "text-zinc-500";
  };

  return (
    <div className="space-y-2 text-xs">
      <div className="flex justify-between">
        <span className="text-zinc-500">total precedents</span>
        <span className="text-zinc-300">{items.length}</span>
      </div>

      {recent.length > 0 ? (
        <div className="space-y-1.5">
          {recent.map((p: any, i: number) => (
            <div key={i} className="rounded bg-zinc-800/50 px-2 py-1">
              <div className="flex justify-between text-[10px]">
                <span className="text-zinc-400 truncate max-w-[70%]">{p?.situation?.slice(0, 50) || p?.id || "—"}</span>
                <span className={authorityColor(p?.authority || "")}>{p?.authority || "?"}</span>
              </div>
              {p?.axiom_id && (
                <div className="text-[9px] text-zinc-600">{p.axiom_id}</div>
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
