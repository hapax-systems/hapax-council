import { useState, useMemo, useCallback, useEffect, type ComponentType } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useHealth, useGpu, useInfrastructure, useBriefing, useDrift, useManagement, useNudges } from "../api/hooks";
import { HealthPanel } from "./sidebar/HealthPanel";
import { VramPanel } from "./sidebar/VramPanel";
import { ContainersPanel } from "./sidebar/ContainersPanel";
import { BriefingPanel } from "./sidebar/BriefingPanel";
import { GoalsPanel } from "./sidebar/GoalsPanel";
import { FreshnessPanel } from "./sidebar/FreshnessPanel";
import { CostPanel } from "./sidebar/CostPanel";
import { ScoutPanel } from "./sidebar/ScoutPanel";
import { DriftPanel } from "./sidebar/DriftPanel";
import { ManagementPanel } from "./sidebar/ManagementPanel";
import { AccommodationPanel } from "./sidebar/AccommodationPanel";
import { TimersPanel } from "./sidebar/TimersPanel";
import { ConsentPanel } from "./sidebar/ConsentPanel";
import { GovernancePanel } from "./sidebar/GovernancePanel";
import { EnginePanel } from "./sidebar/EnginePanel";
import { ProfilePanel } from "./sidebar/ProfilePanel";
import { OverheadPanel } from "./sidebar/OverheadPanel";
import { PrecedentPanel } from "./sidebar/PrecedentPanel";
import { SidebarStrip } from "./sidebar/SidebarStrip";

interface PanelEntry {
  id: string;
  component: ComponentType;
  defaultOrder: number;
}

const panels: PanelEntry[] = [
  { id: "health", component: HealthPanel, defaultOrder: 0 },
  { id: "vram", component: VramPanel, defaultOrder: 1 },
  { id: "consent", component: ConsentPanel, defaultOrder: 2 },
  { id: "governance", component: GovernancePanel, defaultOrder: 3 },
  { id: "containers", component: ContainersPanel, defaultOrder: 4 },
  { id: "briefing", component: BriefingPanel, defaultOrder: 5 },
  { id: "readiness", component: FreshnessPanel, defaultOrder: 6 },
  { id: "goals", component: GoalsPanel, defaultOrder: 7 },
  { id: "cost", component: CostPanel, defaultOrder: 8 },
  { id: "overhead", component: OverheadPanel, defaultOrder: 9 },
  { id: "engine", component: EnginePanel, defaultOrder: 10 },
  { id: "profile", component: ProfilePanel, defaultOrder: 11 },
  { id: "precedents", component: PrecedentPanel, defaultOrder: 12 },
  { id: "scout", component: ScoutPanel, defaultOrder: 13 },
  { id: "drift", component: DriftPanel, defaultOrder: 14 },
  { id: "management", component: ManagementPanel, defaultOrder: 15 },
  { id: "accommodations", component: AccommodationPanel, defaultOrder: 16 },
  { id: "timers", component: TimersPanel, defaultOrder: 17 },
];

export function Sidebar() {
  const [manualOverride, setManualOverride] = useState<"expanded" | "collapsed" | null>(null);

  const { data: health } = useHealth();
  const { data: gpu } = useGpu();
  const { data: infra } = useInfrastructure();
  const { data: briefing } = useBriefing();
  const { data: drift } = useDrift();
  const { data: mgmt } = useManagement();
  const { data: nudges } = useNudges();

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  // Alert triggers
  const needsAttention = useMemo(() => {
    if (health?.overall_status === "degraded" || health?.overall_status === "failed") return true;
    if (nudges?.some((n) => n.priority_label === "critical" || n.priority_label === "high" || n.priority_label === "medium")) return true;
    if (gpu && gpu.usage_pct >= 80) return true;
    if (drift && drift.drift_count > 0) return true;
    if (briefing?.generated_at) {
      const hours = (now - new Date(briefing.generated_at).getTime()) / 3_600_000;
      if (hours > 24) return true;
    }
    return false;
  }, [health, gpu, drift, briefing, nudges, now]);

  const isExpanded = manualOverride === "expanded" || (manualOverride === null && needsAttention);

  // Status dots for strip mode
  const statusDots = useMemo(() => {
    const dots: Record<string, "green" | "yellow" | "red" | "zinc"> = {};
    dots.health = health?.overall_status === "failed" ? "red" : health?.overall_status === "degraded" ? "yellow" : health ? "green" : "zinc";
    dots.vram = gpu && gpu.usage_pct >= 90 ? "red" : gpu && gpu.usage_pct >= 80 ? "yellow" : gpu ? "green" : "zinc";
    dots.containers = infra?.containers.some((c) => c.health !== "healthy") ? "yellow" : infra ? "green" : "zinc";
    dots.briefing = (() => {
      if (!briefing?.generated_at) return "zinc" as const;
      const h = (now - new Date(briefing.generated_at).getTime()) / 3_600_000;
      return h > 24 ? "yellow" as const : "green" as const;
    })();
    dots.drift = drift && drift.drift_count > 0 ? "yellow" : drift ? "green" : "zinc";
    dots.management = mgmt?.people.some((p) => p.stale_1on1) ? "yellow" : mgmt ? "green" : "zinc";
    return dots;
  }, [health, gpu, infra, briefing, drift, mgmt, now]);

  const summaries = useMemo(() => {
    const s: Record<string, string> = {};
    if (health) s.health = `Health: ${health.healthy}/${health.total_checks} passing`;
    if (gpu) s.vram = `VRAM: ${(gpu.free_mb / 1024).toFixed(1)}GB free`;
    if (infra) s.containers = `${infra.containers.filter((c) => c.state === "running").length} containers running`;
    return s;
  }, [health, gpu, infra]);

  // Priority sorting
  const sorted = useMemo(() => {
    function priority(id: string): number {
      switch (id) {
        case "health":
          if (health?.overall_status === "failed") return 100;
          if (health?.overall_status === "degraded") return 50;
          return 0;
        case "vram":
          if (gpu && gpu.usage_pct >= 90) return 60;
          if (gpu && gpu.usage_pct >= 80) return 30;
          return 0;
        case "containers": {
          const unhealthy = infra?.containers.filter((c) => c.health !== "healthy").length ?? 0;
          return unhealthy > 0 ? 40 : 0;
        }
        case "briefing": {
          if (!briefing?.generated_at) return 0;
          const hours = (now - new Date(briefing.generated_at).getTime()) / 3_600_000;
          return hours > 24 ? 30 : 0;
        }
        case "drift":
          return drift && drift.drift_count > 0 ? 20 : 0;
        case "management": {
          const stale = mgmt?.people.filter((p) => p.stale_1on1).length ?? 0;
          return stale > 0 ? 25 : 0;
        }
        default:
          return 0;
      }
    }

    return [...panels].sort((a, b) => {
      const pa = priority(a.id);
      const pb = priority(b.id);
      if (pa !== pb) return pb - pa;
      return a.defaultOrder - b.defaultOrder;
    });
  }, [health, gpu, infra, briefing, drift, mgmt, now]);

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleStripClick = useCallback((_id: string) => {
    setManualOverride("expanded");
  }, []);

  const toggleSidebar = useCallback(() => {
    if (isExpanded) {
      setManualOverride("collapsed");
    } else {
      setManualOverride("expanded");
    }
  }, [isExpanded]);

  return (
    <aside className={`relative shrink-0 border-l border-zinc-700 bg-zinc-900/50 text-xs transition-[width] duration-200 ease-in-out ${isExpanded ? "w-72" : "w-12"}`}>
      {isExpanded ? (
        <div className="h-full divide-y divide-zinc-800 overflow-y-auto">
          <div className="flex justify-end p-2">
            <button
              onClick={toggleSidebar}
              className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
              title="Collapse sidebar"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
          {sorted.map((panel) => (
            <div key={panel.id} className="p-4" id={`sidebar-${panel.id}`}>
              <panel.component />
            </div>
          ))}
        </div>
      ) : (
        <div className="h-full overflow-y-auto">
          <div className="flex justify-center py-2">
            <button
              onClick={toggleSidebar}
              className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
              title="Expand sidebar"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
          </div>
          <SidebarStrip
            statusDots={statusDots}
            summaries={summaries}
            onPanelClick={handleStripClick}
          />
        </div>
      )}
    </aside>
  );
}
