import { LoadingSkeleton } from "../shared/LoadingSkeleton";

type Severity = "nominal" | "degraded" | "critical";

interface SidebarSectionProps {
  title: string;
  children: React.ReactNode;
  clickable?: boolean;
  onClick?: () => void;
  loading?: boolean;
  age?: string;
  severity?: Severity;
}

function severityStyle(severity?: Severity): string {
  if (severity === "critical")
    return "border border-red-500/20 shadow-[inset_0_0_8px_rgba(251,73,52,0.04)] animate-[stimmung-breathe-critical_2s_ease-in-out_infinite]";
  if (severity === "degraded")
    return "border border-orange-500/15 shadow-[inset_0_0_8px_rgba(254,128,25,0.03)] animate-[stimmung-breathe-degraded_6s_ease-in-out_infinite]";
  return "border border-zinc-800/30 shadow-[inset_0_0_12px_rgba(180,160,120,0.02)]";
}

export function SidebarSection({ title, children, clickable, onClick, loading, age, severity }: SidebarSectionProps) {
  return (
    <div
      className={`rounded-sm p-2 ${severityStyle(severity)} ${clickable ? "cursor-pointer hover:bg-zinc-800/30 focus-visible:ring-1 focus-visible:ring-zinc-500 focus-visible:outline-none" : ""}`}
      onClick={clickable ? onClick : undefined}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick?.(); } } : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <h3 className="mb-1 flex items-center gap-2 text-[11px] font-semibold tracking-[0.15em] uppercase text-zinc-500">
        {title}
        {age && <span className="text-[10px] font-normal normal-case tracking-normal text-zinc-600">{age}</span>}
      </h3>
      <div className="space-y-1 text-zinc-400 text-xs">
        {loading ? <LoadingSkeleton lines={2} /> : children}
      </div>
    </div>
  );
}
