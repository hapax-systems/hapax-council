import { useState } from "react";
import { useInfrastructure } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

const INITIAL_SHOW = 8;

function formatNextFire(next: string): string {
  if (!next || next === "-") return "inactive";
  // ISO timestamp → relative time
  if (next.startsWith("20")) {
    try {
      const d = new Date(next);
      const now = Date.now();
      const diff = d.getTime() - now;
      if (diff < 0) return "overdue";
      if (diff < 60_000) return "< 1m";
      if (diff < 3600_000) return `${Math.round(diff / 60_000)}m`;
      if (diff < 86400_000) return `${Math.round(diff / 3600_000)}h`;
      return `${Math.round(diff / 86400_000)}d`;
    } catch {
      return next.slice(0, 16).replace("T", " ");
    }
  }
  // Cron expression — show as-is
  return next;
}

const statusColor: Record<string, string> = {
  inactive: "text-zinc-600",
  overdue: "text-red-400",
};

export function TimersPanel() {
  const { data: infra, dataUpdatedAt } = useInfrastructure();
  const [expanded, setExpanded] = useState(false);

  const items = infra?.timers ?? [];
  const visible = expanded ? items : items.slice(0, INITIAL_SHOW);
  const remaining = items.length - INITIAL_SHOW;

  return (
    <SidebarSection title="Timers" loading={!infra} age={infra ? formatAge(dataUpdatedAt) : undefined}>
      {infra && items.length > 0 ? (
        <>
          {visible.map((t) => {
            const display = formatNextFire(t.next_fire);
            const color = statusColor[display] ?? "text-zinc-400";
            return (
              <div key={t.unit} className="flex items-center justify-between gap-2">
                <span className="truncate text-zinc-500">{t.unit.replace(".timer", "")}</span>
                <span className={`shrink-0 text-xs ${color}`}>{display}</span>
              </div>
            );
          })}
          {remaining > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-0.5 text-zinc-500 hover:text-zinc-300"
            >
              {expanded ? "show less" : `+${remaining} more`}
            </button>
          )}
        </>
      ) : (
        infra && <p className="text-zinc-500">No timers found.</p>
      )}
    </SidebarSection>
  );
}
