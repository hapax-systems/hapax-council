/**
 * FlowSummary — compact stance + active node/flow counts for Watershed surface.
 */

interface FlowSummaryProps {
  stance: string;
  activeCount: number;
  totalCount: number;
  activeFlows: number;
  totalFlows: number;
}

const STANCE_COLORS: Record<string, string> = {
  nominal: "#b8bb26",
  cautious: "#fabd2f",
  degraded: "#fe8019",
  critical: "#fb4934",
};

export function FlowSummary({
  stance,
  activeCount,
  totalCount,
  activeFlows,
  totalFlows,
}: FlowSummaryProps) {
  const color = STANCE_COLORS[stance] ?? "#504945";

  return (
    <div className="flex flex-col gap-1 px-4 py-2">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full" style={{ background: color }} />
        <span className="text-[10px] uppercase tracking-[0.3em]" style={{ color }}>
          {stance}
        </span>
      </div>
      <div className="text-[10px] text-zinc-600">
        {activeCount}/{totalCount} nodes &middot; {activeFlows}/{totalFlows} flows
      </div>
    </div>
  );
}
