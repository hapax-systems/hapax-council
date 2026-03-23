import { useCost } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

export function CostPanel() {
  const { data: cost, dataUpdatedAt } = useCost();

  if (!cost) return <SidebarSection title="Cost" loading>{null}</SidebarSection>;
  if (!cost.available) return null;

  return (
    <SidebarSection title="Cost" age={formatAge(dataUpdatedAt)}>
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
    </SidebarSection>
  );
}
