import { useState } from "react";
import { NudgeList } from "./dashboard/NudgeList";
import { AgentGrid } from "./dashboard/AgentGrid";
import { OutputPane } from "./dashboard/OutputPane";
import { useSSE } from "../hooks/useSSE";
import type { AgentInfo } from "../api/types";

export function MainPanel() {
  const sse = useSSE();
  const [agentName, setAgentName] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);

  function handleRunAgent(agent: AgentInfo, flags: string[]) {
    setAgentName(agent.name);
    setStartedAt(Date.now());
    sse.start(`/api/agents/${agent.name}/run`, { flags });
  }

  return (
    <main className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <NudgeList />
        <AgentGrid onRun={handleRunAgent} disabled={sse.isRunning} />
      </div>
      <OutputPane
        lines={sse.lines}
        isRunning={sse.isRunning}
        agentName={agentName ?? undefined}
        startedAt={startedAt ?? undefined}
        onCancel={sse.cancel}
      />
      {sse.error && (
        <div className="border-t border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {sse.error}
        </div>
      )}
    </main>
  );
}
