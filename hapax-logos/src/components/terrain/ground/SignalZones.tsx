/**
 * SignalZones — layered signal display extracted from HapaxPage.
 * Renders signal categories in positioned zones with severity coloring.
 */

import { memo } from "react";

interface SignalEntry {
  category: string;
  severity: number;
  title: string;
  detail: string;
  source_id: string;
}

const ZONE_COLORS: Record<string, string> = {
  context_time: "rgba(102, 153, 217, VAR)",
  governance: "rgba(77, 179, 179, VAR)",
  work_tasks: "rgba(217, 166, 77, VAR)",
  health_infra: "rgba(77, 204, 77, VAR)",
  profile_state: "rgba(230, 230, 230, VAR)",
  ambient_sensor: "rgba(153, 153, 179, VAR)",
  voice_session: "rgba(77, 217, 153, VAR)",
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "rgba(218, 54, 51, VAR)",
  high: "rgba(212, 123, 60, VAR)",
  medium: "rgba(210, 160, 68, VAR)",
  low: "rgba(102, 153, 217, VAR)",
};

const ZONE_POSITIONS: Record<string, React.CSSProperties> = {
  context_time: { top: "8%", left: "4%", maxWidth: "28%" },
  governance: { top: "8%", right: "4%", maxWidth: "28%" },
  work_tasks: { top: "30%", left: "4%", maxWidth: "22%" },
  health_infra: { bottom: "8%", right: "4%", maxWidth: "24%" },
  ambient_sensor: { bottom: "8%", left: "4%", maxWidth: "40%" },
  voice_session: { bottom: "15%", left: "25%", maxWidth: "50%" },
};

function sevLabel(sev: number): string {
  if (sev >= 0.85) return "critical";
  if (sev >= 0.7) return "high";
  if (sev >= 0.4) return "medium";
  return "low";
}

function zoneColor(cat: string, a: number): string {
  return (ZONE_COLORS[cat] ?? "rgba(128,128,128,VAR)").replace("VAR", String(a));
}

function sevColor(sev: number, a: number): string {
  return (SEVERITY_COLORS[sevLabel(sev)] ?? SEVERITY_COLORS.low).replace("VAR", String(a));
}

interface SignalZonesProps {
  signals: Record<string, SignalEntry[]>;
  opacities: Record<string, number>;
}

export const SignalZones = memo(function SignalZones({ signals, opacities }: SignalZonesProps) {
  const allSignals = Object.values(signals).flat();
  if (allSignals.length === 0) return null;

  return (
    <div className="absolute inset-0 pointer-events-none">
      {Object.entries(signals).map(([category, entries]) => {
        const opacity = opacities[category] ?? 0;
        if (opacity < 0.05 || !entries.length) return null;

        const pos = ZONE_POSITIONS[category];
        if (!pos) return null;

        return (
          <div
            key={category}
            className="absolute"
            style={{
              ...pos,
              opacity: Math.min(opacity * 1.2, 1),
              transition: "opacity 1.5s ease",
            }}
          >
            <div
              className="backdrop-blur-md rounded-xl p-4"
              style={{ background: "rgba(0,0,0,0.65)" }}
            >
              <div
                className="text-[9px] uppercase tracking-[0.3em] mb-2"
                style={{ color: zoneColor(category, 0.5) }}
              >
                {category.replace(/_/g, " ")}
              </div>
              {entries.slice(0, 3).map((sig, i) => (
                <div key={sig.source_id || i} className="mb-2">
                  <div
                    className="text-sm leading-relaxed font-medium"
                    style={{ color: sevColor(sig.severity, 1.0) }}
                  >
                    {sig.title.slice(0, 60)}
                  </div>
                  {sig.detail && (
                    <div className="text-xs text-white/50 mt-0.5">{sig.detail.slice(0, 80)}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
});
