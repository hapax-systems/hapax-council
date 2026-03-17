import { Eye, EyeOff } from "lucide-react";
import type { SignalEntry } from "../../api/types";
import {
  CATEGORY_BG,
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  type SignalCategory,
} from "../../contexts/ClassificationOverlayContext";

interface ChannelStripProps {
  category: SignalCategory;
  visible: boolean;
  onToggle: () => void;
  signals: SignalEntry[];
  expanded: boolean;
  onExpand: () => void;
  active?: boolean;
  onClick?: () => void;
}

function maxSeverity(signals: SignalEntry[]): number {
  return signals.reduce((max, s) => Math.max(max, s.severity), 0);
}

function severityBarColor(sev: number): string {
  if (sev >= 0.85) return "bg-red-400";
  if (sev >= 0.7) return "bg-orange-400";
  if (sev >= 0.4) return "bg-amber-400";
  if (sev >= 0.2) return "bg-zinc-400";
  return "bg-zinc-700";
}

function severityDotColor(sev: number): string {
  if (sev >= 0.85) return "bg-red-400";
  if (sev >= 0.7) return "bg-orange-400";
  if (sev >= 0.4) return "bg-amber-400";
  if (sev >= 0.2) return "bg-zinc-400";
  return "bg-zinc-600";
}

export function ChannelStrip({
  category,
  visible,
  onToggle,
  signals,
  expanded,
  onExpand,
  active,
  onClick,
}: ChannelStripProps) {
  const sev = maxSeverity(signals);
  const color = CATEGORY_COLORS[category];
  const bg = CATEGORY_BG[category];

  return (
    <div
      className={`border-b border-zinc-800/50 transition-colors ${active ? "bg-zinc-800/40" : ""}`}
    >
      <div className="flex items-center gap-1.5 px-3 py-2">
        {/* Visibility toggle */}
        <button
          onClick={onToggle}
          className={`shrink-0 transition-colors ${visible ? color : "text-zinc-600 hover:text-zinc-400"}`}
          title={visible ? "Hide channel" : "Show channel"}
        >
          {visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
        </button>

        {/* Category label */}
        <button
          onClick={onClick ?? onExpand}
          className={`min-w-0 flex-1 text-left text-[11px] font-semibold ${color}`}
        >
          {CATEGORY_LABELS[category]}
        </button>

        {/* Severity meter — taller for readability */}
        <div className="h-2 w-14 shrink-0 overflow-hidden rounded-full bg-zinc-800">
          <div
            className={`h-full rounded-full transition-all duration-500 ${severityBarColor(sev)}`}
            style={{ width: `${Math.min(100, sev * 100)}%` }}
          />
        </div>

        {/* Signal count badge */}
        {signals.length > 0 && (
          <span
            className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold text-black ${bg}`}
          >
            {signals.length}
          </span>
        )}
      </div>

      {/* Expanded: individual signals with severity dots */}
      {expanded && signals.length > 0 && (
        <div className="flex flex-col gap-0.5 px-3 pb-2">
          {signals.map((s, i) => (
            <div
              key={`${s.source_id}-${i}`}
              className="flex items-center gap-1.5 rounded bg-zinc-800/60 px-2 py-1 text-[10px]"
            >
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${severityDotColor(s.severity)}`}
              />
              <span className="min-w-0 flex-1 truncate text-zinc-200">{s.title}</span>
              {s.detail && (
                <span className="shrink-0 truncate text-[9px] text-zinc-500">{s.detail}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
