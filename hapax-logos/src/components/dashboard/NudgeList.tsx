import { useState } from "react";
import { useNudges, useNudgeAction } from "../../api/hooks";
import type { Nudge } from "../../api/types";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { useToast } from "../shared/ToastProvider";
import { parseAgentCommand } from "../../utils";
import { Check, X, Play, Loader2 } from "lucide-react";

const priorityColor: Record<string, string> = {
  critical: "border-red-500 bg-red-500/10",
  high: "border-orange-500 bg-orange-500/10",
  medium: "border-yellow-500 bg-yellow-500/10",
  low: "border-zinc-600 bg-zinc-800",
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
      <h2 className="mb-2 text-sm font-medium tracking-wide uppercase text-zinc-300">
        Action Items ({items.length})
      </h2>
      {items.length === 0 ? (
        <p className="text-xs text-zinc-500">No action items right now.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((n) => {
            const isMeta = n.category === "meta";
            const canRun = n.command_hint ? !!parseAgentCommand(n.command_hint) : false;
            return (
            <li
              key={n.source_id}
              className={`rounded border-l-2 p-2 text-xs transition-shadow duration-150 hover:shadow-sm hover:shadow-black/20 ${priorityColor[n.priority_label] ?? priorityColor.low}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-zinc-200">{n.title}</span>
                    <span className="shrink-0 text-zinc-500">{n.category}</span>
                  </div>
                  {n.detail && <p className="mt-1 text-zinc-400">{n.detail}</p>}
                  {n.suggested_action && (
                    <p className="mt-1 text-zinc-300">
                      {canRun ? (
                        <span className="text-green-400/80">▸ {n.suggested_action}</span>
                      ) : (
                        <><span className="text-zinc-500">Action:</span> {n.suggested_action}</>
                      )}
                    </p>
                  )}
                </div>
                {!isMeta && (
                <div className="flex shrink-0 gap-1">
                  {pendingId === n.source_id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />
                  ) : (
                    <>
                      <button
                        onClick={() => handleAction(n, "act")}
                        className={`flex items-center gap-1 rounded px-2 py-1 active:scale-[0.97] focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none ${
                          canRun
                            ? "border border-green-500/30 bg-green-500/10 text-green-400 hover:bg-green-500/20"
                            : "border border-zinc-700 bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                        }`}
                        title={canRun ? n.suggested_action || "Run agent" : "Mark done"}
                      >
                        {canRun ? (
                          <Play className="h-4 w-4" />
                        ) : (
                          <Check className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        onClick={() => handleAction(n, "dismiss")}
                        className="rounded border border-zinc-700 bg-zinc-800 p-1 text-zinc-500 hover:bg-zinc-700 active:scale-[0.97]"
                        title="Dismiss"
                      >
                        <X className="h-4 w-4" />
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
