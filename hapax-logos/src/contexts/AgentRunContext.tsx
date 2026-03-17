import { createContext, useContext, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";

export interface PendingAgentRun {
  agent: string;
  flags: Record<string, string>;
}

interface AgentRunContextValue {
  pendingRun: PendingAgentRun | null;
  requestAgentRun: (run: PendingAgentRun) => void;
  clearPendingRun: () => void;
}

const AgentRunContext = createContext<AgentRunContextValue | null>(null);

export function AgentRunProvider({ children }: { children: React.ReactNode }) {
  const [pendingRun, setPendingRun] = useState<PendingAgentRun | null>(null);
  const navigate = useNavigate();

  const requestAgentRun = useCallback(
    (run: PendingAgentRun) => {
      setPendingRun(run);
      navigate("/");
    },
    [navigate],
  );

  const clearPendingRun = useCallback(() => setPendingRun(null), []);

  return (
    <AgentRunContext.Provider value={{ pendingRun, requestAgentRun, clearPendingRun }}>
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
