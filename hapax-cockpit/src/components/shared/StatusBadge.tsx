interface StatusBadgeProps {
  status: string;
  className?: string;
}

const statusColors: Record<string, string> = {
  healthy: "bg-green-500/20 text-green-400 border-green-500/30",
  degraded: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  failed: "bg-red-500/20 text-red-400 border-red-500/30",
  critical: "bg-red-500/20 text-red-400 border-red-500/30",
  high: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  medium: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  low: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
  adopt: "bg-green-500/20 text-green-400 border-green-500/30",
  evaluate: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  monitor: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
  "current-best": "bg-zinc-700/20 text-zinc-500 border-zinc-600/30",
};

export function StatusBadge({ status, className = "" }: StatusBadgeProps) {
  const colors = statusColors[status.toLowerCase()] ?? statusColors.low;
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${colors} ${className}`}>
      {status}
    </span>
  );
}
