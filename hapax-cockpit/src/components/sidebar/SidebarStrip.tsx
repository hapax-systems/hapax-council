import {
  Heart, Cpu, Server, FileText, Clock, Target,
  DollarSign, Compass, GitBranch, Users, Accessibility, Timer,
} from "lucide-react";
import type { ComponentType } from "react";

interface StripItem {
  id: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
}

const stripItems: StripItem[] = [
  { id: "health", icon: Heart, label: "Health" },
  { id: "vram", icon: Cpu, label: "VRAM" },
  { id: "containers", icon: Server, label: "Containers" },
  { id: "briefing", icon: FileText, label: "Briefing" },
  { id: "readiness", icon: Clock, label: "Readiness" },
  { id: "goals", icon: Target, label: "Goals" },
  { id: "cost", icon: DollarSign, label: "Cost" },
  { id: "scout", icon: Compass, label: "Scout" },
  { id: "drift", icon: GitBranch, label: "Drift" },
  { id: "management", icon: Users, label: "Management" },
  { id: "accommodations", icon: Accessibility, label: "Accommodations" },
  { id: "timers", icon: Timer, label: "Timers" },
];

interface SidebarStripProps {
  statusDots: Record<string, "green" | "yellow" | "red" | "zinc">;
  summaries: Record<string, string>;
  onPanelClick: (id: string) => void;
}

export function SidebarStrip({ statusDots, summaries, onPanelClick }: SidebarStripProps) {
  return (
    <div className="flex flex-col items-center gap-1 py-3">
      {stripItems.map((item) => {
        const dotColor = statusDots[item.id] ?? "zinc";
        const dotClass = {
          green: "bg-green-400",
          yellow: "bg-yellow-400",
          red: "bg-red-400",
          zinc: "bg-zinc-600",
        }[dotColor];

        return (
          <button
            key={item.id}
            onClick={() => onPanelClick(item.id)}
            className="group relative flex h-9 w-9 items-center justify-center rounded text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-zinc-300"
            title={summaries[item.id] ?? item.label}
          >
            <item.icon className="h-4 w-4" />
            <span className={`absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full ${dotClass}`} />
          </button>
        );
      })}
    </div>
  );
}
