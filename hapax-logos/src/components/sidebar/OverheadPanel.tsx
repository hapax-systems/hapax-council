import { useConsentOverhead } from "../../api/hooks";

export function OverheadPanel() {
  const { data: overhead } = useConsentOverhead();

  const oh = overhead as any;
  const tokenPct = oh?.token_cost_pct ?? oh?.token_overhead_pct ?? null;
  const sdlcPct = oh?.sdlc_pipeline_pct ?? oh?.pipeline_overhead_pct ?? null;
  const joinUs = oh?.label_join_us ?? oh?.label_ops?.join_us ?? null;
  const flowUs = oh?.label_flow_us ?? oh?.label_ops?.flow_check_us ?? null;
  const govUs = oh?.label_gov_us ?? oh?.label_ops?.governor_check_us ?? null;
  const events = oh?.sdlc_events ?? oh?.event_count ?? null;

  return (
    <div className="space-y-2 text-xs">
      {tokenPct != null && (
        <div className="flex justify-between">
          <span className="text-zinc-500">token overhead</span>
          <span className={tokenPct > 30 ? "text-amber-400" : "text-zinc-300"}>{tokenPct.toFixed(1)}%</span>
        </div>
      )}
      {sdlcPct != null && (
        <div className="flex justify-between">
          <span className="text-zinc-500">SDLC overhead</span>
          <span className={sdlcPct > 30 ? "text-amber-400" : "text-zinc-300"}>{sdlcPct.toFixed(1)}%</span>
        </div>
      )}

      <div className="text-[9px] text-zinc-600 uppercase tracking-wider pt-1">label operations</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
        {joinUs != null && (
          <div className="flex justify-between">
            <span className="text-zinc-500">join</span>
            <span className="text-zinc-400">{joinUs.toFixed(1)}µs</span>
          </div>
        )}
        {flowUs != null && (
          <div className="flex justify-between">
            <span className="text-zinc-500">flow check</span>
            <span className="text-zinc-400">{flowUs.toFixed(1)}µs</span>
          </div>
        )}
        {govUs != null && (
          <div className="flex justify-between">
            <span className="text-zinc-500">governor</span>
            <span className="text-zinc-400">{govUs.toFixed(1)}µs</span>
          </div>
        )}
      </div>

      {events != null && (
        <div className="flex justify-between text-[10px] pt-1 border-t border-zinc-800">
          <span className="text-zinc-500">SDLC events</span>
          <span className="text-zinc-400">{events}</span>
        </div>
      )}

      {!oh && <div className="text-zinc-600 text-[10px]">No overhead data available</div>}
    </div>
  );
}
