import { useCcHygieneState } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";
import type { CcHygieneSession } from "../../api/types";

// Workstream hygiene panel — surfaces the most recent sweep from
// scripts/cc-hygiene-sweeper.py (PR1). Read-only display: no
// acknowledge / clear / revert affordances. Per the cc-hygiene
// design (PR4 spec), in-band action wiring is deferred until the
// hygiene-actions UDS shipped by a follow-on cc-task; this panel
// renders only what the sweeper observed.
//
// Anti-anthropomorphization: the four session dots match the
// waybar widget glyph set so the operator sees the same row in
// two surfaces.
export function WorkstreamHygieneView() {
  const { data, dataUpdatedAt, isLoading } = useCcHygieneState();
  const stale = dataUpdatedAt > 0 && Date.now() - dataUpdatedAt > 90_000;
  const state = data?.state ?? null;

  return (
    <SidebarSection
      title="Workstream Hygiene"
      loading={isLoading}
      age={dataUpdatedAt > 0 ? formatAge(dataUpdatedAt) : undefined}
    >
      <div className={stale ? "opacity-40" : ""}>
        {state === null ? (
          <div className="text-[11px] text-zinc-600">no sweep state on record</div>
        ) : (
          <>
            <SessionRow sessions={state.sessions} killswitch={state.killswitch_active} />
            <CheckSummaryRow summaries={state.check_summaries} />
            <EventList events={state.events} />
          </>
        )}
      </div>
    </SidebarSection>
  );
}

const ROLES = ["alpha", "beta", "delta", "epsilon"] as const;

function SessionRow({
  sessions,
  killswitch,
}: {
  sessions: CcHygieneSession[];
  killswitch: boolean;
}) {
  const byRole = new Map(sessions.map((s) => [s.role, s]));
  return (
    <div className="mb-1 flex items-center gap-2 font-mono text-[11px]">
      {killswitch ? (
        <span className="shrink-0 rounded bg-red-900/40 px-1 text-red-300" title="killswitch active">
          KS
        </span>
      ) : null}
      {ROLES.map((role) => {
        const s = byRole.get(role);
        const dot = sessionDot(s);
        const claim = s?.current_claim ?? null;
        const inProg = s?.in_progress_count ?? 0;
        return (
          <span
            key={role}
            className="flex shrink-0 items-center gap-0.5 text-zinc-400"
            title={`${role}: ${claim ?? "no claim"} (in_progress=${inProg})`}
          >
            <span className="text-zinc-500">{role[0]}</span>
            <span>{dot}</span>
          </span>
        );
      })}
    </div>
  );
}

function sessionDot(s: CcHygieneSession | undefined): string {
  if (!s || !s.current_claim) return "○";
  if (s.in_progress_count > 0) return "●";
  return "◐";
}

function CheckSummaryRow({
  summaries,
}: {
  summaries: { check_id: string; fired: number }[];
}) {
  const fired = summaries.filter((s) => s.fired > 0);
  if (fired.length === 0) {
    return <div className="mb-1 text-[10px] text-zinc-600">no checks fired</div>;
  }
  return (
    <ul className="mb-1 flex flex-wrap gap-1 font-mono text-[10px] leading-tight">
      {fired.map((s) => (
        <li key={s.check_id} className="rounded bg-zinc-800/60 px-1 text-zinc-400">
          {s.check_id} <span className="text-zinc-300">{s.fired}</span>
        </li>
      ))}
    </ul>
  );
}

function EventList({
  events,
}: {
  events: { timestamp: string; check_id: string; task_id?: string | null; message: string }[];
}) {
  if (events.length === 0) {
    return <div className="text-[10px] text-zinc-600">no recent hygiene events</div>;
  }
  const recent = events.slice(-20).reverse();
  return (
    <ul className="max-h-72 space-y-0.5 overflow-y-auto font-mono text-[10px] leading-tight">
      {recent.map((e, idx) => (
        <li
          key={`${e.timestamp}-${e.check_id}-${idx}`}
          className="flex gap-1 text-zinc-400"
        >
          <span className="shrink-0 text-zinc-600">{shortTime(e.timestamp)}</span>
          <span className="shrink-0 text-zinc-500">{e.check_id}</span>
          {e.task_id ? <span className="shrink-0 text-zinc-300">{e.task_id}</span> : null}
          <span className="truncate text-zinc-400">{e.message}</span>
        </li>
      ))}
    </ul>
  );
}

function shortTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toISOString().slice(11, 16) + "Z";
  } catch {
    return "--:--Z";
  }
}
