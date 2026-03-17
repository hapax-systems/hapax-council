import { useState, useEffect } from "react";
import { useBriefing } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { SidebarSection } from "./SidebarSection";
import { DetailModal } from "../shared/DetailModal";
import { MarkdownContent } from "../shared/MarkdownContent";
import { formatAge, parseAgentCommand } from "../../utils";
import { Play } from "lucide-react";

export function BriefingPanel() {
  const { data: briefing, dataUpdatedAt } = useBriefing();
  const { requestAgentRun } = useAgentRun();
  const [detailOpen, setDetailOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (!briefing) return null;

  const ageH = (() => {
    try {
      const gen = new Date(briefing.generated_at);
      return ((now - gen.getTime()) / 3600000).toFixed(0);
    } catch {
      return "?";
    }
  })();

  return (
    <>
      <SidebarSection title="Briefing" clickable onClick={() => setDetailOpen(true)} age={formatAge(dataUpdatedAt)}>
        <p className="text-sm text-zinc-300 line-clamp-2">{briefing.headline}</p>
        <p className="text-zinc-500">{ageH}h ago · {briefing.action_items.length} action items</p>
      </SidebarSection>

      <DetailModal title="Daily Briefing" open={detailOpen} onClose={() => setDetailOpen(false)}>
        <div className="space-y-3 text-xs">
          <p className="text-zinc-500">{briefing.generated_at}</p>
          <MarkdownContent content={briefing.body} className="text-sm" />
          {briefing.action_items.length > 0 && (
            <div>
              <h3 className="mb-1 font-medium text-zinc-300">Action Items</h3>
              <ul className="space-y-1">
                {briefing.action_items.map((a, i) => (
                  <li key={i} className="flex items-center justify-between text-zinc-400">
                    <span>
                      <span className="font-medium text-zinc-300">[{a.priority}]</span> {a.action}
                      {a.command && <code className="ml-1 text-zinc-500">{a.command}</code>}
                    </span>
                    {a.command && parseAgentCommand(a.command) && (
                      <button
                        onClick={() => {
                          const parsed = parseAgentCommand(a.command!);
                          if (parsed) {
                            setDetailOpen(false);
                            requestAgentRun(parsed);
                          }
                        }}
                        className="ml-2 shrink-0 rounded border border-green-500/30 bg-green-500/10 p-1.5 text-green-400 hover:bg-green-500/20 active:scale-[0.97]"
                        title="Run this command"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </DetailModal>
    </>
  );
}
