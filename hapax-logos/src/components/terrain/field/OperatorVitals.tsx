import type { BiometricState } from "../../../hooks/useVisualLayer";

interface OperatorVitalsProps {
  biometrics: BiometricState;
  freshness?: number; // 0.0 stale → 1.0 fresh
}

export function OperatorVitals({ biometrics, freshness = 1.0 }: OperatorVitalsProps) {
  const { heart_rate_bpm, stress_elevated, physiological_load, sleep_quality, phone_connected, phone_battery_pct } = biometrics;
  const opacity = Math.max(0.15, freshness * 0.5);

  return (
    <div className="flex items-center gap-1.5" style={{ opacity }}>
      {/* Heart rate — pulses at actual HR tempo */}
      {heart_rate_bpm > 0 && (
        <span
          className="text-[14px] text-zinc-500 tabular-nums"
          style={{
            animation: `signal-breathe-mod ${60 / heart_rate_bpm}s ease-in-out infinite`,
          }}
        >
          {Math.round(heart_rate_bpm)}
        </span>
      )}

      {/* Stress pip */}
      {stress_elevated && (
        <div
          className="w-1 h-1 rounded-full"
          style={{
            backgroundColor: "#fb4934",
            animation: "signal-breathe-fast 1s ease-in-out infinite",
          }}
        />
      )}

      {/* Physiological load bar */}
      {physiological_load > 0 && (
        <div className="h-[1px] rounded-full bg-zinc-800" style={{ width: 24 }}>
          <div
            className="h-full rounded-full"
            style={{
              width: `${physiological_load * 100}%`,
              background:
                physiological_load < 0.4
                  ? "#b8bb26"
                  : physiological_load < 0.7
                    ? "#fabd2f"
                    : "#fb4934",
            }}
          />
        </div>
      )}

      {/* Sleep deficit indicator */}
      {sleep_quality < 0.6 && sleep_quality > 0 && (
        <span className="text-[8px] text-zinc-600" title={`Sleep quality: ${(sleep_quality * 100).toFixed(0)}%`}>
          ☾
        </span>
      )}

      {/* Phone connectivity dot */}
      {phone_connected !== undefined && (
        <div
          className="w-1 h-1 rounded-full"
          style={{
            backgroundColor: phone_connected ? "#b8bb26" : "#504945",
          }}
          title={phone_connected ? "Phone connected" : "Phone disconnected"}
        />
      )}

      {/* Phone battery bar */}
      {phone_connected && phone_battery_pct > 0 && (
        <div className="h-[1px] rounded-full bg-zinc-800" style={{ width: 16 }}>
          <div
            className="h-full rounded-full"
            style={{
              width: `${phone_battery_pct}%`,
              background:
                phone_battery_pct > 30
                  ? "#b8bb26"
                  : phone_battery_pct > 15
                    ? "#fabd2f"
                    : "#fb4934",
            }}
          />
        </div>
      )}
    </div>
  );
}
