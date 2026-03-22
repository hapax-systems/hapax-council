import { useState } from "react";
import { useNudges, useNudgeAction } from "../../api/hooks";
import type { Nudge } from "../../api/types";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { useToast } from "../shared/ToastProvider";
import { parseAgentCommand } from "../../utils";
import { Check, X, Play, Loader2 } from "lucide-react";

const titleColor: Record<string, string> = {
  critical: "text-red-400",
  high: "text-orange-400",
  medium: "text-amber-400",
  low: "text-zinc-300",
};

export function NudgeList() {
  const { data: nudges } = useNudges();
  const nudgeAction = useNudgeAction();
  const { requestAgentRun } = useAgentRun();
  const { addToast } = useToast();
  const [pendingId, setPendingId] = useState<string | null>(null);

  function handleAction(nudge: Nudge, action: "act" | "dismiss") {
    setPendingId(nudge.source_id);
    nudgeAction.mutate(
      { sourceId: nudge.source_id, action },
      {
        onSuccess: () => {
          if (action === "act" && nudge.command_hint) {
            const parsed = parseAgentCommand(nudge.command_hint);
            if (parsed) {
              requestAgentRun(parsed);
            }
          }
        },
        onError: () => addToast(`Failed to ${action} nudge`, "error"),
        onSettled: () => setPendingId(null),
      },
    );
  }

  const items = nudges ?? [];

  return (
    <section>
      <h2 className="mb-1.5 text-[11px] font-semibold tracking-[0.15em] uppercase text-zinc-500">
        Action Items ({items.length})
      </h2>
      {items.length === 0 ? (
        <p className="text-xs text-zinc-600">No action items right now.</p>
      ) : (
        <ul className="space-y-0">
          {items.map((n) => {
            const isMeta = n.category === "meta";
            const canRun = n.command_hint ? !!parseAgentCommand(n.command_hint) : false;
            return (
            <li
              key={n.source_id}
              className="border-b border-zinc-800/20 py-1.5 text-xs"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className={titleColor[n.priority_label] ?? "text-zinc-300"}>{n.title}</span>
                    <span className="text-[10px] text-zinc-600">{n.category}</span>
                  </div>
                  {n.detail && <p className="mt-0.5 text-[10px] text-zinc-500">{n.detail}</p>}
                  {n.suggested_action && (
                    <p className="mt-0.5 text-[10px] text-zinc-500">
                      {canRun ? (
                        <span className="text-green-400/70">{n.suggested_action}</span>
                      ) : (
                        n.suggested_action
                      )}
                    </p>
                  )}
                </div>
                {!isMeta && (
                <div className="flex shrink-0 gap-0.5 items-center">
                  {pendingId === n.source_id ? (
                    <Loader2 className="h-3 w-3 animate-spin text-zinc-500" />
                  ) : (
                    <>
                      <button
                        onClick={() => handleAction(n, "act")}
                        className="p-0.5 text-zinc-500 hover:text-zinc-300 active:scale-[0.95]"
                        title={canRun ? n.suggested_action || "Run agent" : "Mark done"}
                      >
                        {canRun ? <Play className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      </button>
                      <button
                        onClick={() => handleAction(n, "dismiss")}
                        className="p-0.5 text-zinc-600 hover:text-zinc-400 active:scale-[0.95]"
                        title="Dismiss"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </>
                  )}
                </div>
                )}
              </div>
            </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
