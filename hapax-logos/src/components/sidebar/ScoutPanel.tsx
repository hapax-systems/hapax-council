import { useState } from "react";
import { useScout, useScoutDecisions, useScoutDecide } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { SidebarSection } from "./SidebarSection";
import { DetailModal } from "../shared/DetailModal";
import { StatusBadge } from "../shared/StatusBadge";
import { useToast } from "../shared/ToastProvider";
import { formatAge } from "../../utils";
import { Check, Clock, X, Loader2 } from "lucide-react";

export function ScoutPanel() {
  const { data: scout, dataUpdatedAt } = useScout();
  const { data: decisionsData } = useScoutDecisions();
  const scoutDecide = useScoutDecide();
  const { requestAgentRun } = useAgentRun();
  const { addToast } = useToast();
  const [detailOpen, setDetailOpen] = useState(false);
  const [pendingComponent, setPendingComponent] = useState<string | null>(null);

  if (!scout) return <SidebarSection title="Scout" loading>{null}</SidebarSection>;

  const decisions = decisionsData?.decisions ?? [];
  const decisionMap = new Map(decisions.map((d) => [d.component, d]));

  const actionable = scout.adopt_count + scout.evaluate_count;

  function handleDecision(component: string, decision: "adopted" | "deferred" | "dismissed") {
    setPendingComponent(component);
    scoutDecide.mutate(
      { component, decision },
      {
        onSuccess: () => {
          if (decision === "adopted") {
            setDetailOpen(false);
            requestAgentRun({
              agent: "research",
              flags: { "query": `Evaluate migrating to ${component}: benefits, risks, migration effort, and step-by-step plan` },
            });
          }
        },
        onError: () => addToast(`Failed to record decision for ${component}`, "error"),
        onSettled: () => setPendingComponent(null),
      },
    );
  }

  return (
    <>
      <SidebarSection title="Scout" clickable onClick={() => setDetailOpen(true)} age={formatAge(dataUpdatedAt)}>
        <p>
          {scout.components_scanned} scanned
          {actionable > 0 && (
            <span className="text-yellow-400"> · {actionable} actionable</span>
          )}
        </p>
        {scout.recommendations.filter(r => r.tier === "adopt").slice(0, 2).map((r) => (
          <p key={r.component} className="text-green-400 truncate">
            adopt: {r.component}
          </p>
        ))}
      </SidebarSection>

      <DetailModal title="Scout Report" open={detailOpen} onClose={() => setDetailOpen(false)}>
        <div className="space-y-3 text-xs">
          <p className="text-zinc-500">
            {scout.components_scanned} components scanned · {scout.generated_at}
          </p>
          {scout.recommendations.map((r) => {
            const existing = decisionMap.get(r.component);
            return (
              <div key={r.component} className={`rounded border p-2 ${existing ? "border-zinc-800 opacity-60" : "border-zinc-700"}`}>
                <div className="flex items-center gap-2">
                  <StatusBadge status={r.tier} />
                  <span className="font-medium text-zinc-200">{r.component}</span>
                  <span className="text-zinc-500">({r.current})</span>
                  {existing && (
                    <span className={`ml-auto text-[10px] ${
                      existing.decision === "adopted" ? "text-green-400" :
                      existing.decision === "deferred" ? "text-yellow-400" : "text-zinc-500"
                    }`}>
                      {existing.decision}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-zinc-400">{r.summary}</p>
                <p className="text-zinc-500">
                  confidence: {r.confidence} · effort: {r.migration_effort}
                </p>
                {!existing && (
                  <div className="mt-2 flex gap-1">
                    {pendingComponent === r.component ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />
                    ) : (
                      <>
                        <button
                          onClick={() => handleDecision(r.component, "adopted")}
                          className="flex items-center gap-1.5 rounded border border-green-500/30 bg-green-500/10 px-2.5 py-1 text-xs font-medium text-green-400 hover:bg-green-500/20 active:scale-[0.97]"
                          title="Adopt — generate migration plan"
                        >
                          <Check className="h-3.5 w-3.5" /> Adopt
                        </button>
                        <button
                          onClick={() => handleDecision(r.component, "deferred")}
                          className="flex items-center gap-1.5 rounded border border-yellow-500/30 bg-yellow-500/10 px-2.5 py-1 text-xs font-medium text-yellow-400 hover:bg-yellow-500/20 active:scale-[0.97]"
                          title="Defer — revisit later"
                        >
                          <Clock className="h-3.5 w-3.5" /> Defer
                        </button>
                        <button
                          onClick={() => handleDecision(r.component, "dismissed")}
                          className="rounded border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs text-zinc-500 hover:bg-zinc-700 active:scale-[0.97]"
                          title="Dismiss"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </DetailModal>
    </>
  );
}
