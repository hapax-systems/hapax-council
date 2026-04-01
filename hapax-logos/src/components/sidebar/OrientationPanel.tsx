import { useState, useEffect } from "react";
import { useOrientation, useBriefing } from "../../api/hooks";
import { useAgentRun } from "../../contexts/AgentRunContext";
import { SidebarSection } from "./SidebarSection";
import { DetailModal } from "../shared/DetailModal";
import { MarkdownContent } from "../shared/MarkdownContent";
import { formatAge, parseAgentCommand } from "../../utils";
import type { DomainState } from "../../api/types";
import { invoke } from "@tauri-apps/api/core";
import { Play } from "lucide-react";

function formatRecency(hours: number): string {
  if (!isFinite(hours)) return "";
  if (hours < 1) return `${Math.round(hours * 60)}m ago`;
  if (hours < 48) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

const HEALTH_BORDER: Record<string, string> = {
  active: "border-l-green-400/15",
  stale: "border-l-yellow-400/15",
  dormant: "border-l-zinc-600/30",
  blocked: "border-l-orange-400/25",
};

const HEALTH_BADGE: Record<string, { label: string; color: string }> = {
  active: { label: "active", color: "text-green-400" },
  stale: { label: "stale", color: "text-yellow-400" },
  dormant: { label: "dormant", color: "text-zinc-500" },
  blocked: { label: "blocked", color: "text-orange-400" },
};

function DomainStrip({
  ds,
  expanded,
  onToggle,
  stimmungStance,
}: {
  ds: DomainState;
  expanded: boolean;
  onToggle: () => void;
  stimmungStance: string;
}) {
  // Dormant domains compressed to single line in non-nominal stances
  if (ds.health === "dormant" && stimmungStance !== "nominal") {
    return (
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 text-[10px] text-zinc-600 hover:text-zinc-400"
      >
        <span className="truncate">{ds.domain}</span>
        <span>{formatRecency(ds.recency_hours)}</span>
      </button>
    );
  }

  const border = HEALTH_BORDER[ds.health] ?? "border-l-zinc-600/30";
  const badge = HEALTH_BADGE[ds.health] ?? HEALTH_BADGE.dormant;

  const openGoal = (uri: string) => {
    invoke("plugin:opener|open_url", { url: uri }).catch(() => {
      // Fallback: try window.open for Obsidian URI
    });
  };

  return (
    <div className={`border-l-2 ${border} pl-2`}>
      {/* Header */}
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-1.5 text-[11px] hover:text-zinc-300"
      >
        <span className="font-medium text-zinc-300 capitalize">{ds.domain}</span>
        <span className="text-zinc-600">{formatRecency(ds.recency_hours)}</span>
        <span className={`ml-auto text-[10px] ${badge.color}`}>{badge.label}</span>
      </button>

      {/* Top goal */}
      {ds.top_goal && (
        <div className="mt-0.5">
          <button
            onClick={() => openGoal(ds.top_goal!.obsidian_uri)}
            className="text-left text-zinc-400 hover:text-zinc-200 hover:underline truncate block max-w-full"
            title={ds.top_goal.title}
          >
            {ds.top_goal.title}
          </button>
          {ds.top_goal.progress != null && (
            <div className="mt-0.5 flex items-center gap-1.5">
              <div className="h-1 flex-1 rounded-full bg-zinc-800">
                <div
                  className="h-1 rounded-full bg-green-400/40"
                  style={{ width: `${Math.min(100, Math.round(ds.top_goal.progress * 100))}%` }}
                />
              </div>
              <span className="text-[10px] text-zinc-600">{Math.round(ds.top_goal.progress * 100)}%</span>
            </div>
          )}
        </div>
      )}

      {/* Sprint info (research domain) */}
      {ds.sprint_progress && (
        <p className="mt-0.5 text-[10px] text-zinc-500">
          Sprint {ds.sprint_progress.current_sprint}: {ds.sprint_progress.measures_completed}/{ds.sprint_progress.measures_total} measures
        </p>
      )}

      {/* Next action */}
      {ds.next_action && (
        <p className="mt-0.5 text-[10px] text-zinc-500">
          {ds.sprint_progress?.blocking_gate ? (
            <span className="text-orange-400">Gate: {ds.sprint_progress.blocking_gate}</span>
          ) : (
            <span>Next: {ds.next_action}</span>
          )}
        </p>
      )}

      {/* Expanded: additional info */}
      {expanded && (
        <p className="mt-0.5 text-[10px] text-zinc-600">
          {ds.goal_count} goal{ds.goal_count !== 1 ? "s" : ""}
          {ds.stale_count > 0 && <span className="text-yellow-400"> · {ds.stale_count} stale</span>}
        </p>
      )}
    </div>
  );
}

export function OrientationPanel() {
  const { data: orientation, dataUpdatedAt } = useOrientation();
  const { data: briefing } = useBriefing();
  const { requestAgentRun } = useAgentRun();
  const [expandedDomain, setExpandedDomain] = useState<string | null>(null);
  const [briefingOpen, setBriefingOpen] = useState(false);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  if (!orientation) {
    return <SidebarSection title="ORIENTATION" loading>{null}</SidebarSection>;
  }

  const stance = orientation.stimmung_stance ?? "nominal";

  // Stimmung modulation: filter visible domains
  let visibleDomains: DomainState[];
  if (stance === "critical") {
    // Single line: most urgent action item only
    visibleDomains = orientation.domains.slice(0, 1);
  } else if (stance === "degraded") {
    // Only top domain + system health, no narrative
    visibleDomains = orientation.domains.slice(0, 1);
  } else if (stance === "cautious") {
    // All domains, but dormant ones compressed
    visibleDomains = orientation.domains;
  } else {
    // Nominal: all domains + narrative
    visibleDomains = orientation.domains;
  }

  const briefingAgeH = (() => {
    if (!orientation.briefing_generated_at) return null;
    try {
      return Math.round((now - new Date(orientation.briefing_generated_at).getTime()) / 3_600_000);
    } catch {
      return null;
    }
  })();

  return (
    <>
      <SidebarSection title="ORIENTATION" age={orientation ? formatAge(dataUpdatedAt) : undefined}>
        {/* Narrative block — nominal/cautious only, suppressed in degraded/critical */}
        {(stance === "nominal" || stance === "cautious") && orientation.narrative && (
          <p className="text-zinc-400 text-xs leading-relaxed mb-2">{orientation.narrative}</p>
        )}

        {/* Domain strips */}
        <div className="space-y-1.5">
          {visibleDomains.map((ds) => (
            <DomainStrip
              key={ds.domain}
              ds={ds}
              expanded={expandedDomain === ds.domain}
              onToggle={() =>
                setExpandedDomain((prev) => (prev === ds.domain ? null : ds.domain))
              }
              stimmungStance={stance}
            />
          ))}
        </div>

        {/* System health line — always visible in degraded/critical */}
        {(stance === "degraded" || stance === "critical") && (
          <p className="mt-1 text-[10px] text-zinc-500">
            System: {orientation.system_health} · {orientation.drift_high_count} high drift
          </p>
        )}

        {/* Briefing summary line */}
        {orientation.briefing_headline && stance !== "critical" && (
          <button
            onClick={() => setBriefingOpen(true)}
            className="mt-2 w-full text-left text-[10px] text-zinc-500 hover:text-zinc-300 truncate"
          >
            {orientation.briefing_headline}
            {briefingAgeH != null && <span className="ml-1 text-zinc-600">{briefingAgeH}h ago</span>}
          </button>
        )}
      </SidebarSection>

      {/* Briefing detail modal (preserved from old BriefingPanel) */}
      {briefing && (
        <DetailModal title="Daily Briefing" open={briefingOpen} onClose={() => setBriefingOpen(false)}>
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
                              setBriefingOpen(false);
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
      )}
    </>
  );
}
