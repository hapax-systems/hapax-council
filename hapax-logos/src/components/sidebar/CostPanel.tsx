import { useCost } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

export function CostPanel() {
  const { data: cost, dataUpdatedAt } = useCost();

  if (!cost) return <SidebarSection title="Cost" loading>{null}</SidebarSection>;
  const local = cost.local_capacity;
  const showDollarCost = cost.available;
  const showLocalCapacity = Boolean(local?.available);
  if (!showDollarCost && !showLocalCapacity) return null;

  return (
    <SidebarSection title="Cost" age={formatAge(dataUpdatedAt)}>
      {showDollarCost && (
        <>
          <div className="flex justify-between">
            <span className="text-zinc-500">Today</span>
            <span className="text-zinc-200">${cost.today_cost.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-[10px]">
            <span className="text-zinc-500">7d avg</span>
            <span className="text-zinc-500">${cost.daily_average.toFixed(2)}/d</span>
          </div>
          {cost.top_models.slice(0, 3).map((m) => (
            <div key={m.model} className="flex justify-between text-[10px]">
              <span className="text-zinc-600 truncate flex-1">{m.model}</span>
              <span className="text-zinc-600 shrink-0 ml-2">${m.cost.toFixed(2)}</span>
            </div>
          ))}
        </>
      )}
      {showLocalCapacity && local && (
        <div className="mt-2 border-t border-zinc-800 pt-2">
          <div className="flex justify-between text-[10px]">
            <span className={local.alert_active ? "text-orange-400" : "text-zinc-500"}>
              Local capacity (non-$)
            </span>
            <span className={local.alert_active ? "text-orange-300" : "text-zinc-400"}>
              {(local.pressure * 100).toFixed(0)}%
            </span>
          </div>
          <div className="flex justify-between text-[10px]">
            <span className="text-zinc-600">
              {local.inflight.toFixed(0)}/{local.ceiling.toFixed(0)} inflight
            </span>
            <span className="text-zinc-600">{local.ttft_ratio.toFixed(2)}x TTFT</span>
          </div>
        </div>
      )}
    </SidebarSection>
  );
}
