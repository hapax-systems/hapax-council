import { createContext, useContext, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useSSE } from "../hooks/useSSE";

export interface PendingAgentRun {
  agent: string;
  flags: Record<string, string>;
}

interface AgentRunContextValue {
  // Legacy: navigate to dashboard + set pending run
  pendingRun: PendingAgentRun | null;
  requestAgentRun: (run: PendingAgentRun) => void;
  clearPendingRun: () => void;
  // Terrain: in-place SSE streaming
  runAgent: (name: string, flags: string[]) => void;
  lines: string[];
  isRunning: boolean;
  agentName: string | null;
  startedAt: number | null;
  cancel: () => void;
  error: string | null;
  clearOutput: () => void;
}

const AgentRunContext = createContext<AgentRunContextValue | null>(null);

export function AgentRunProvider({ children }: { children: React.ReactNode }) {
  const [pendingRun, setPendingRun] = useState<PendingAgentRun | null>(null);
  const [agentName, setAgentName] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const navigate = useNavigate();
  const sse = useSSE();

  const requestAgentRun = useCallback(
    (run: PendingAgentRun) => {
      setPendingRun(run);
      navigate("/");
    },
    [navigate],
  );

  const clearPendingRun = useCallback(() => setPendingRun(null), []);

  const runAgent = useCallback(
    (name: string, flags: string[]) => {
      setAgentName(name);
      setStartedAt(Date.now());
      sse.start(`/api/agents/${name}/run`, { flags });
    },
    [sse],
  );

  const clearOutput = useCallback(() => {
    sse.clear();
    setAgentName(null);
    setStartedAt(null);
  }, [sse]);

  return (
    <AgentRunContext.Provider
      value={{
        pendingRun,
        requestAgentRun,
        clearPendingRun,
        runAgent,
        lines: sse.lines,
        isRunning: sse.isRunning,
        agentName,
        startedAt,
        cancel: sse.cancel,
        error: sse.error,
        clearOutput,
      }}
    >
      {children}
    </AgentRunContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAgentRun() {
  const ctx = useContext(AgentRunContext);
  if (!ctx) throw new Error("useAgentRun must be used within AgentRunProvider");
  return ctx;
}
