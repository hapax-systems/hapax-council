import { Activity, BookOpen, Loader2 } from "lucide-react";
import { NavLink } from "react-router-dom";
import { useHealth, useCycleMode, useSetCycleMode } from "../api/hooks";

interface HeaderProps {
  onManualToggle?: () => void;
}

export function Header({ onManualToggle }: HeaderProps) {
  const { data: health } = useHealth();
  const { data: cycleMode } = useCycleMode();
  const setCycleMode = useSetCycleMode();

  const isDev = cycleMode?.mode === "dev";

  const statusColor =
    health?.overall_status === "healthy"
      ? "text-green-400"
      : health?.overall_status === "degraded"
        ? "text-yellow-400"
        : health?.overall_status === "failed"
          ? "text-red-400"
          : "text-zinc-500";

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1 rounded text-xs font-medium transition-colors ${
      isActive
        ? "bg-zinc-700 text-zinc-100"
        : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
    }`;

  return (
    <header className="flex items-center justify-between border-b border-zinc-700 bg-zinc-900 px-4 py-2">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-zinc-400" />
          <span className="text-sm font-medium text-zinc-200">cockpit</span>
        </div>
        <nav className="flex items-center gap-1" aria-label="Main navigation">
          <NavLink to="/" end className={navLinkClass}>
            Dashboard
          </NavLink>
          <NavLink to="/chat" className={navLinkClass}>
            Chat
          </NavLink>
          <NavLink to="/insight" className={navLinkClass}>
            Insight
          </NavLink>
          <NavLink to="/demos" className={navLinkClass}>
            Demos
          </NavLink>
          <NavLink to="/studio" className={navLinkClass}>
            Studio
          </NavLink>
        </nav>
      </div>
      <div className="flex items-center gap-3 text-xs">
        <span className={statusColor}>
          {health ? `${health.healthy}/${health.total_checks} checks` : "loading..."}
        </span>
        <button
          onClick={() => setCycleMode.mutate(isDev ? "prod" : "dev")}
          disabled={setCycleMode.isPending}
          className={`flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium transition-colors ${
            isDev
              ? "bg-amber-900/50 text-amber-400 hover:bg-amber-900/70"
              : "text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
          }`}
          title={`Cycle mode: ${cycleMode?.mode ?? "prod"} — click to switch`}
        >
          {setCycleMode.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${isDev ? "bg-amber-400" : "bg-zinc-600"}`} />
          )}
          {isDev ? "dev" : "prod"}
        </button>
        <div className="hidden items-center gap-2 text-[10px] text-zinc-600 sm:flex">
          <span><kbd className="rounded border border-zinc-700 px-1 py-0.5">?</kbd> help</span>
          <span><kbd className="rounded border border-zinc-700 px-1 py-0.5">⌘P</kbd> commands</span>
        </div>
        <button
          onClick={onManualToggle}
          className="flex items-center gap-1 rounded px-2 py-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
          title="Operations Manual (?)"
          aria-label="Toggle operations manual"
        >
          <BookOpen className="h-3.5 w-3.5" />
          <kbd className="text-[10px] text-zinc-600">?</kbd>
        </button>
      </div>
    </header>
  );
}
