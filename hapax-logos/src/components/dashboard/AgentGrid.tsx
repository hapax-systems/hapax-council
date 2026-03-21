import { useState, useEffect } from "react";
import { useAgents } from "../../api/hooks";
import type { AgentInfo } from "../../api/types";
import { AgentConfigModal } from "./AgentConfigModal";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { Play } from "lucide-react";

interface AgentGridProps {
  onRun: (agent: AgentInfo, flags: string[]) => void;
  disabled?: boolean;
}

export function AgentGrid({ onRun, disabled }: AgentGridProps) {
  const { data: agents } = useAgents();
  const [configAgent, setConfigAgent] = useState<AgentInfo | null>(null);
  const { pendingRun, clearPendingRun } = useAgentRun();
  const [prefilledFlags, setPrefilledFlags] = useState<Record<string, string> | undefined>();

   
  useEffect(() => {
    if (pendingRun && agents) {
      const needle = pendingRun.agent.replace(/_/g, "-");
      const match = agents.find((a) => a.name === needle || a.name === pendingRun.agent);
      if (match) {
        setPrefilledFlags(pendingRun.flags);
        setConfigAgent(match);
      }
      clearPendingRun();
    }
  }, [pendingRun, agents, clearPendingRun]);
   

  function handleRun(agent: AgentInfo, flags: string[]) {
    setConfigAgent(null);
    setPrefilledFlags(undefined);
    onRun(agent, flags);
  }

  function handleCloseConfig() {
    setConfigAgent(null);
    setPrefilledFlags(undefined);
  }

  const items = agents ?? [];

  return (
    <section>
      <h2 className="mb-2 text-sm font-medium tracking-wide uppercase text-zinc-300">
        Agents ({items.length})
      </h2>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {items.map((a) => (
          <div
            key={a.name}
            className="group relative rounded border border-zinc-700 p-2 text-xs transition-all duration-150 hover:border-zinc-500 hover:bg-zinc-800/50 hover:shadow-sm hover:shadow-black/20"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${a.uses_llm ? "bg-blue-400" : "bg-green-400"}`} />
                <span className="font-medium text-zinc-200">{a.name}</span>
              </div>
              <button
                onClick={() => {
                  if (a.flags.length > 0) {
                    setConfigAgent(a);
                  } else {
                    onRun(a, []);
                  }
                }}
                disabled={disabled}
                className="rounded p-1 text-zinc-500 opacity-0 transition-opacity hover:bg-zinc-700 hover:text-zinc-200 group-hover:opacity-100 disabled:opacity-30 focus-visible:opacity-100 focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none"
                title="Run agent"
              >
                <Play className="h-3 w-3" />
              </button>
            </div>
            <p className="mt-1 text-zinc-500">{a.description}</p>
          </div>
        ))}
      </div>

      {configAgent && (
        <AgentConfigModal
          agent={configAgent}
          initialFlags={prefilledFlags}
          onRun={handleRun}
          onClose={handleCloseConfig}
        />
      )}
    </section>
  );
}
