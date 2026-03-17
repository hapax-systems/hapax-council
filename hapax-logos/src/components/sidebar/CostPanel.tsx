import { useCost } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

export function CostPanel() {
  const { data: cost, dataUpdatedAt } = useCost();

  if (!cost?.available) return null;

  return (
    <SidebarSection title="Cost" age={formatAge(dataUpdatedAt)}>
      <div className="flex justify-between">
        <span>Today</span>
        <span className="text-zinc-300">${cost.today_cost.toFixed(2)}</span>
      </div>
      <div className="flex justify-between">
        <span>7d avg</span>
        <span className="text-zinc-300">${cost.daily_average.toFixed(2)}/d</span>
      </div>
      {cost.top_models.slice(0, 3).map((m) => (
        <p key={m.model} className="text-zinc-500">
          {m.model}: ${m.cost.toFixed(2)}
        </p>
      ))}
    </SidebarSection>
  );
}
