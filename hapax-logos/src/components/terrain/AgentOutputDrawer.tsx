import { useAgentRun } from "../../contexts/AgentRunContext";
import { OutputPane } from "../dashboard/OutputPane";

export function AgentOutputDrawer() {
  const { lines, isRunning, agentName, startedAt, cancel, error, clearOutput } = useAgentRun();

  const visible = lines.length > 0 || isRunning;

  return (
    <div
      className="absolute bottom-0 left-0 right-0 transition-transform duration-300 ease-out"
      style={{
        zIndex: 20,
        maxHeight: "40vh",
        transform: visible ? "translateY(0)" : "translateY(100%)",
      }}
    >
      <div className="bg-zinc-950/95 backdrop-blur-sm border-t border-zinc-800 overflow-hidden max-h-[40vh]">
        {visible && (
          <>
            <div className="flex items-center justify-end px-2 py-0.5">
              {!isRunning && lines.length > 0 && (
                <button
                  onClick={clearOutput}
                  className="text-[10px] text-zinc-600 hover:text-zinc-400 px-2 py-0.5"
                >
                  Clear
                </button>
              )}
            </div>
            <OutputPane
              lines={lines}
              isRunning={isRunning}
              agentName={agentName ?? undefined}
              startedAt={startedAt ?? undefined}
              onCancel={cancel}
            />
          </>
        )}
        {error && (
          <div className="border-t border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
