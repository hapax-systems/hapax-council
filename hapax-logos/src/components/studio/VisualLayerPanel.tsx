import { useVisualLayer } from "../../api/hooks";

const ZONE_LABELS: Record<string, string> = {
  context_time: "Context",
  governance: "Governance",
  work_tasks: "Tasks",
  health_infra: "Health",
  profile_state: "Profile",
  ambient_sensor: "Ambient",
};

const ZONE_COLORS: Record<string, string> = {
  context_time: "text-blue-400",
  governance: "text-teal-400",
  work_tasks: "text-amber-400",
  health_infra: "text-green-400",
  profile_state: "text-purple-400",
  ambient_sensor: "text-zinc-400",
};

const STATE_BADGES: Record<string, { label: string; color: string }> = {
  ambient: { label: "AMBIENT", color: "bg-zinc-700 text-zinc-300" },
  peripheral: { label: "PERIPHERAL", color: "bg-blue-900 text-blue-300" },
  informational: { label: "INFO", color: "bg-amber-900 text-amber-300" },
  alert: { label: "ALERT", color: "bg-red-900 text-red-300" },
  performative: { label: "PERFORM", color: "bg-purple-900 text-purple-300" },
};

export default function VisualLayerPanel() {
  const { data: vl, isLoading } = useVisualLayer();

  if (isLoading || !vl) {
    return (
      <div className="text-xs text-zinc-500 px-2 py-1">
        Visual layer loading...
      </div>
    );
  }

  const badge = STATE_BADGES[vl.display_state] ?? STATE_BADGES.ambient;
  const offline = vl.aggregator === "offline";
  const hasSignals = Object.values(vl.signals).some((s) => s.length > 0);

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${badge.color}`}>
          {badge.label}
        </span>
        {offline && (
          <span className="text-zinc-500 text-[10px]">aggregator offline</span>
        )}
      </div>

      {hasSignals &&
        Object.entries(vl.signals).map(([zone, signals]) => {
          if (!signals.length) return null;
          const opacity = vl.zone_opacities[zone] ?? 0;
          const color = ZONE_COLORS[zone] ?? "text-zinc-400";
          return (
            <div key={zone} className="space-y-0.5" style={{ opacity: Math.max(0.3, opacity) }}>
              <div className={`font-mono text-[10px] ${color}`}>
                {ZONE_LABELS[zone] ?? zone}
              </div>
              {signals.map((s, i) => (
                <div key={i} className="pl-2 text-zinc-300 truncate" title={s.detail || s.title}>
                  <span
                    className="inline-block w-1.5 h-1.5 rounded-full mr-1"
                    style={{
                      backgroundColor:
                        s.severity >= 0.7
                          ? "#ef4444"
                          : s.severity >= 0.4
                            ? "#f59e0b"
                            : "#6b7280",
                    }}
                  />
                  {s.title}
                </div>
              ))}
            </div>
          );
        })}

      {!hasSignals && !offline && (
        <div className="text-zinc-600 text-[10px]">No active signals</div>
      )}

      {/* Ambient params summary */}
      <div className="flex gap-2 text-[10px] text-zinc-600 font-mono">
        <span>spd:{vl.ambient_params.speed.toFixed(2)}</span>
        <span>wrm:{vl.ambient_params.color_warmth.toFixed(2)}</span>
      </div>
    </div>
  );
}
