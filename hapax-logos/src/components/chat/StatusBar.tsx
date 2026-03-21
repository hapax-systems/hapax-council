import { useState, useEffect } from "react";
import { useChatContext } from "./ChatProvider";
import { useChatModels } from "../../api/hooks";

export function StatusBar() {
  const { state, switchModel, getInterviewStatus } = useChatContext();
  const { data: modelsData } = useChatModels();
  const [interviewInfo, setInterviewInfo] = useState<{
    topics_explored: number;
    total_topics: number;
    facts_count: number;
  } | null>(null);

  const messageCount = state.messages.filter((m) => m.role === "user").length;
  const models = modelsData?.models ?? [];

  // Poll interview status when in interview mode
   
  useEffect(() => {
    if (state.mode !== "interview") {
      setInterviewInfo(null);
      return;
    }

    let cancelled = false;
    async function poll() {
      const status = await getInterviewStatus();
      if (!cancelled && status?.active) {
        setInterviewInfo({
          topics_explored: status.topics_explored ?? 0,
          total_topics: status.total_topics ?? 0,
          facts_count: status.facts_count ?? 0,
        });
      }
    }

    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [state.mode, state.messages.length, getInterviewStatus]);
   

  return (
    <div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900/80 px-4 py-1 text-xs text-zinc-500">
      <div className="flex items-center gap-3">
        {models.length > 0 ? (
          <select
            value={state.model}
            onChange={(e) => switchModel(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-900 px-1 py-0.5 text-xs text-zinc-400 outline-none hover:border-zinc-600"
          >
            {models.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        ) : (
          <span>model: {state.model}</span>
        )}
        {state.mode === "interview" && (
          <span className="text-fuchsia-400">
            interview
            {interviewInfo
              ? ` ${interviewInfo.topics_explored}/${interviewInfo.total_topics} topics, ${interviewInfo.facts_count} facts`
              : ""}
          </span>
        )}
        <span>{messageCount} turns</span>
      </div>
      <div className="flex items-center gap-3">
        {state.lastTurnTokens > 0 && <span>last: {state.lastTurnTokens.toLocaleString()} tok</span>}
        {state.totalTokens > 0 && <span>total: {state.totalTokens.toLocaleString()} tok</span>}
      </div>
    </div>
  );
}
