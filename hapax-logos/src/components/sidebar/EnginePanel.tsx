import { useEngineStatus, useEngineHistory } from "../../api/hooks";

export function EnginePanel() {
  const { data: status } = useEngineStatus();
  const { data: history } = useEngineHistory();

  const s = status as any;
  const events = s?.events_processed ?? 0;
  const actions = s?.actions_executed ?? 0;
  const errors = s?.errors ?? 0;
  const uptime = s?.uptime_s ?? 0;
  const rules = s?.rules_count ?? s?.active_rules ?? "—";
  const novelty = s?.novelty_score ?? null;

  const recentHistory = Array.isArray(history) ? history.slice(-5).reverse() : [];

  return (
    <div className="space-y-2 text-xs">
      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        <div className="flex justify-between">
          <span className="text-zinc-500">events</span>
          <span className="text-zinc-300">{events.toLocaleString()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">actions</span>
          <span className="text-zinc-300">{actions}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">errors</span>
          <span className={errors > 0 ? "text-amber-400" : "text-zinc-300"}>{errors}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">rules</span>
          <span className="text-zinc-300">{rules}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">uptime</span>
          <span className="text-zinc-400">{uptime > 3600 ? `${(uptime / 3600).toFixed(1)}h` : `${(uptime / 60).toFixed(0)}m`}</span>
        </div>
        {novelty != null && (
          <div className="flex justify-between">
            <span className="text-zinc-500">novelty</span>
            <span className="text-zinc-400">{(novelty * 100).toFixed(0)}%</span>
          </div>
        )}
      </div>

      {recentHistory.length > 0 && (
        <div className="space-y-1 pt-1 border-t border-zinc-800">
          <div className="text-[9px] text-zinc-600 uppercase tracking-wider">recent</div>
          {recentHistory.map((e: any, i: number) => (
            <div key={i} className="text-[10px] text-zinc-500 truncate">
              {e?.doc_type || e?.event_type || "event"}: {e?.rules_matched || 0} rules
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
