import { useState } from "react";
import { useGoals } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

const INITIAL_SHOW = 4;

export function GoalsPanel() {
  const { data: goals, dataUpdatedAt } = useGoals();
  const [expanded, setExpanded] = useState(false);

  const items = goals?.goals ?? [];
  const visible = expanded ? items : items.slice(0, INITIAL_SHOW);
  const remaining = items.length - INITIAL_SHOW;

  return (
    <SidebarSection title="Goals" loading={!goals} age={goals ? formatAge(dataUpdatedAt) : undefined}>
      {goals && (
        <>
          <p>
            {goals.active_count} active
            {goals.stale_count > 0 && (
              <span className="text-yellow-400"> · {goals.stale_count} stale</span>
            )}
          </p>
          {visible.map((g) => (
            <p key={g.id} className={g.stale ? "text-yellow-400" : "text-zinc-400"}>
              {g.stale ? "! " : ""}{g.name}
            </p>
          ))}
          {remaining > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-0.5 text-zinc-500 hover:text-zinc-300"
            >
              {expanded ? "show less" : `+${remaining} more`}
            </button>
          )}
        </>
      )}
    </SidebarSection>
  );
}
