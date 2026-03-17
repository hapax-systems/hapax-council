/* eslint-disable react-refresh/only-export-components */
import type { SignalEntry } from "../../api/types";
import { ZoneCard } from "./ZoneCard";
import {
  CATEGORY_BORDER,
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  CATEGORY_ZONE_BG,
  type SignalCategory,
} from "../../contexts/ClassificationOverlayContext";

interface ZoneSpec {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const ZONE_LAYOUT: Record<string, ZoneSpec> = {
  context_time: { x: 0.01, y: 0.03, w: 0.25, h: 0.14 },
  governance: { x: 0.74, y: 0.03, w: 0.25, h: 0.14 },
  work_tasks: { x: 0.01, y: 0.20, w: 0.18, h: 0.45 },
  health_infra: { x: 0.78, y: 0.76, w: 0.21, h: 0.20 },
  profile_state: { x: 0.30, y: 0.01, w: 0.34, h: 0.10 },
  ambient_sensor: { x: 0.01, y: 0.90, w: 0.76, h: 0.09 },
};

interface ZoneOverlayProps {
  category: SignalCategory;
  signals: SignalEntry[];
  opacity: number;
  onClick?: () => void;
  active?: boolean;
}

export function ZoneOverlay({ category, signals, opacity, onClick, active }: ZoneOverlayProps) {
  const zone = ZONE_LAYOUT[category];
  if (!zone) return null;

  const hasSignals = signals.length > 0;
  const effectiveOpacity = Math.max(0, Math.min(1, opacity));
  const zoneBg = CATEGORY_ZONE_BG[category];
  const zoneBorder = CATEGORY_BORDER[category];
  const zoneColor = CATEGORY_COLORS[category];

  return (
    <div
      onClick={onClick}
      className={`absolute overflow-hidden rounded-md border-l-2 transition-all duration-500 ${zoneBorder} ${
        active ? "ring-1 ring-white/20" : ""
      } ${hasSignals ? "cursor-pointer" : ""}`}
      style={{
        left: `${zone.x * 100}%`,
        top: `${zone.y * 100}%`,
        width: `${zone.w * 100}%`,
        height: `${zone.h * 100}%`,
        opacity: hasSignals ? Math.max(effectiveOpacity, 0.6) : 0.15,
      }}
    >
      <div
        className={`flex h-full flex-col gap-0.5 rounded-r-md p-1.5 backdrop-blur-md ${
          hasSignals ? zoneBg : "bg-transparent"
        }`}
      >
        {/* Zone label — always visible, color-coded */}
        <div className={`flex items-center gap-1 text-[8px] font-bold uppercase tracking-widest ${zoneColor}`}>
          <span className="opacity-70">{CATEGORY_LABELS[category]}</span>
          {hasSignals && (
            <span className="rounded-full bg-white/10 px-1 text-[7px] font-semibold tabular-nums">
              {signals.length}
            </span>
          )}
        </div>
        {/* Signal cards */}
        {hasSignals && (
          <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-hidden">
            {signals.map((s, i) => (
              <ZoneCard key={`${s.source_id}-${i}`} signal={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
