/**
 * AgentSummary — compact agent counts for Field region surface.
 */

import { useAgents } from "../../../api/hooks";

export function AgentSummary() {
  const { data: agents } = useAgents();

  const agentList = Array.isArray(agents) ? agents : (agents as any)?.agents ?? [];
  const total = agentList.length;
  const byCategory: Record<string, number> = {};
  for (const a of agentList) {
    const cat = a.category ?? "other";
    byCategory[cat] = (byCategory[cat] ?? 0) + 1;
  }

  return (
    <div className="flex gap-3 text-[10px] text-zinc-600">
      <span>{total} agents</span>
      {Object.entries(byCategory)
        .slice(0, 3)
        .map(([cat, count]) => (
          <span key={cat} className="text-zinc-700">
            {count} {cat}
          </span>
        ))}
    </div>
  );
}
