import { useMemo } from "react";
import { SignalPip } from "./SignalPip";
import {
  CATEGORY_HEX,
  CATEGORY_LABELS,
  type SignalCategory,
} from "../../../contexts/ClassificationOverlayContext";
import type { SignalEntry, TemporalContext } from "../../../api/types";
import type { Depth } from "../../../contexts/TerrainContext";

export type ClusterDensity = "compact" | "summary" | "full";

interface SignalClusterProps {
  signals: SignalEntry[];
  density: ClusterDensity;
  temporalContext?: TemporalContext | null;
  className?: string;
}

// Category → temporal trend field mapping
const CATEGORY_TREND: Record<string, keyof TemporalContext> = {
  profile_state: "trend_flow",
  ambient_sensor: "trend_audio",
};

/** 32×8 SVG sparkline showing trend direction */
function TrendSparkline({ slope, color }: { slope: number; color: string }) {
  // slope in [-1, 1], map to y offset
  const y1 = 4 - slope * 3;
  const y2 = 4 + slope * 3;
  return (
    <svg width={32} height={8} className="inline-block ml-1">
      <polyline
        points={`0,${y1} 16,4 32,${y2}`}
        fill="none"
        stroke={color}
        strokeWidth={1}
        opacity={0.4}
      />
    </svg>
  );
}

// Note: densityFromDepth is exported alongside components, which triggers
// react-refresh/only-export-components. This is acceptable for a utility
// tightly coupled to this component.
// eslint-disable-next-line react-refresh/only-export-components
export function densityFromDepth(depth: Depth): ClusterDensity {
  if (depth === "surface") return "compact";
  if (depth === "stratum") return "summary";
  return "full";
}

/** Group signals by category, pick highest severity per category */
function groupByCategory(signals: SignalEntry[]): Map<SignalCategory, SignalEntry[]> {
  const map = new Map<SignalCategory, SignalEntry[]>();
  for (const sig of signals) {
    const cat = sig.category as SignalCategory;
    const existing = map.get(cat);
    if (existing) {
      existing.push(sig);
    } else {
      map.set(cat, [sig]);
    }
  }
  // Sort entries within each category by severity descending
  for (const entries of map.values()) {
    entries.sort((a, b) => b.severity - a.severity);
  }
  return map;
}

function CompactCluster({ signals }: { signals: SignalEntry[] }) {
  const grouped = useMemo(() => groupByCategory(signals), [signals]);

  // Show highest-severity pip per category, max 3
  const pips = Array.from(grouped.entries())
    .map(([cat, entries]) => ({ cat, entry: entries[0] }))
    .sort((a, b) => b.entry.severity - a.entry.severity)
    .slice(0, 3);

  if (pips.length === 0) return null;

  return (
    <div className="flex gap-1 items-center pointer-events-none" style={{ maxWidth: 60 }}>
      {pips.map(({ cat, entry }) => (
        <SignalPip
          key={cat}
          category={cat}
          severity={entry.severity}
          title={entry.title}
          detail={entry.detail}
        />
      ))}
    </div>
  );
}

function SummaryCluster({ signals, temporalContext }: { signals: SignalEntry[]; temporalContext?: TemporalContext | null }) {
  const grouped = useMemo(() => groupByCategory(signals), [signals]);

  const items = Array.from(grouped.entries())
    .map(([cat, entries]) => ({ cat, entry: entries[0] }))
    .sort((a, b) => b.entry.severity - a.entry.severity)
    .slice(0, 5);

  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-1" style={{ maxWidth: 180 }}>
      {items.map(({ cat, entry }) => {
        const trendKey = CATEGORY_TREND[cat];
        const slope = trendKey && temporalContext ? temporalContext[trendKey] as number : null;
        return (
          <div key={cat} className="flex items-center gap-1.5">
            <SignalPip category={cat} severity={entry.severity} title={entry.title} />
            <span className="text-[9px] text-zinc-500 truncate">{entry.title}</span>
            {slope !== null && Math.abs(slope) > 0.05 && (
              <TrendSparkline slope={slope} color={CATEGORY_HEX[cat]} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function FullCluster({ signals }: { signals: SignalEntry[] }) {
  const grouped = useMemo(() => groupByCategory(signals), [signals]);

  if (grouped.size === 0) return null;

  return (
    <div className="flex flex-col gap-2" style={{ maxWidth: 260 }}>
      {Array.from(grouped.entries())
        .sort(([, a], [, b]) => b[0].severity - a[0].severity)
        .map(([cat, entries]) => (
          <div key={cat}>
            <div className="text-[8px] uppercase tracking-[0.2em] mb-0.5" style={{ color: CATEGORY_HEX[cat] }}>
              {CATEGORY_LABELS[cat]}
            </div>
            {entries.map((entry, i) => (
              <div key={entry.source_id || i} className="flex items-start gap-1.5 mb-1">
                <div className="mt-0.5">
                  <SignalPip category={cat} severity={entry.severity} title={entry.title} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[10px] text-zinc-400 truncate">{entry.title}</div>
                  {entry.detail && (
                    <div className="text-[9px] text-zinc-600 truncate">{entry.detail}</div>
                  )}
                  {/* Severity bar */}
                  <div className="h-[2px] mt-0.5 rounded-full bg-zinc-800" style={{ width: 40 }}>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${entry.severity * 100}%`,
                        backgroundColor: CATEGORY_HEX[cat],
                        opacity: 0.7,
                      }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}

export function SignalCluster({ signals, density, temporalContext, className = "" }: SignalClusterProps) {
  if (signals.length === 0) return null;

  return (
    <div className={className}>
      {density === "compact" && <CompactCluster signals={signals} />}
      {density === "summary" && <SummaryCluster signals={signals} temporalContext={temporalContext} />}
      {density === "full" && <FullCluster signals={signals} />}
    </div>
  );
}
