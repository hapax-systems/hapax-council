import { useRefusals } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

// First-class refusal display surface — the materialization of the refusal-
// as-data substrate per drop §3 fresh patterns and the
// `feedback_full_automation_or_no_engagement` directive.
//
// CONSTITUTIONAL: this component MUST NOT offer
// acknowledge / dismiss / mark-read / archive / triage / review affordances.
// Refusals are first-class displayed elements, never aggregated, never
// ackable. The CI guard in `tests/no-refusal-action-affordance.test.tsx`
// asserts the rendered tree contains zero buttons matching
// /(ack|acknowledge|dismiss|read|archive|review|triage)/i.
//
// Visual twin of HARDM anti-anthropomorphization (per
// `project_hardm_anti_anthropomorphization` memory): raw signal density,
// no decoration, no operator-action affordance.
export function RefusalBriefPanel() {
  const { data, dataUpdatedAt, isLoading } = useRefusals(50);
  const refusals = data?.refusals ?? [];
  // Stale-state dim: when our query hasn't refreshed in >90s, fade the
  // panel rather than blanking it (consumers prefer "last-known-good
  // dimmed" over an empty panel).
  const stale = dataUpdatedAt > 0 && Date.now() - dataUpdatedAt > 90_000;

  return (
    <SidebarSection
      title="Refusals"
      loading={isLoading}
      age={dataUpdatedAt > 0 ? formatAge(dataUpdatedAt) : undefined}
    >
      <div className={stale ? "opacity-40" : ""}>
        <div className="mb-1 text-[10px] text-zinc-600">
          last {refusals.length} · raw individuals · no aggregation
        </div>
        {refusals.length === 0 ? (
          <div className="text-[11px] text-zinc-600">no refusals on record</div>
        ) : (
          <ul className="max-h-72 space-y-0.5 overflow-y-auto font-mono text-[10px] leading-tight">
            {refusals
              .slice()
              .reverse()
              .map((r, idx) => (
                <li
                  key={`${r.timestamp}-${r.surface}-${idx}`}
                  className="flex gap-1 text-zinc-400"
                >
                  <span className="shrink-0 text-zinc-600">{shortTime(r.timestamp)}</span>
                  {r.axiom ? (
                    <span className="shrink-0 text-zinc-500">{r.axiom}</span>
                  ) : null}
                  <span className="shrink-0 text-zinc-300">{r.surface}</span>
                  <span className="truncate text-zinc-400">{r.reason}</span>
                </li>
              ))}
          </ul>
        )}
      </div>
    </SidebarSection>
  );
}

// Compact ISO-8601 → HH:MMZ for the leading column. Per
// anti-anthropomorphization, no relative-time prose ("3 minutes ago" reads
// like a narrative); fixed wall-clock format keeps the rendering structural.
function shortTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toISOString().slice(11, 16) + "Z";
  } catch {
    return "--:--Z";
  }
}
