interface PresenceIndicatorProps {
  presenceScore: number;
  operatorPresent: boolean;
  interruptibility: number;
  guestPresent: boolean;
}

export function PresenceIndicator({
  presenceScore,
  operatorPresent,
  interruptibility,
  guestPresent,
}: PresenceIndicatorProps) {
  // Presence dot color (§3.7 severity ladder)
  const presenceColor = operatorPresent
    ? "var(--color-green-400)"
    : presenceScore > 0.3
      ? "var(--color-yellow-400)"
      : "var(--color-zinc-700)";

  // Interruptibility bar: always at stratum+, but breaks through at surface when < 0.3
  const showInterruptibility = interruptibility < 0.3 || interruptibility > 0;
  const interruptColor =
    interruptibility > 0.6
      ? "var(--color-green-400)"
      : interruptibility > 0.3
        ? "var(--color-yellow-400)"
        : "var(--color-red-400)";

  return (
    <div className="flex items-center gap-1.5">
      {/* Presence dot */}
      <div
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: presenceColor }}
        title={`Presence: ${(presenceScore * 100).toFixed(0)}%`}
      />

      {/* Interruptibility bar */}
      {showInterruptibility && (
        <div className="h-[2px] rounded-full bg-zinc-800" style={{ width: 40 }}>
          <div
            className="h-full rounded-full transition-all duration-1000"
            style={{
              width: `${interruptibility * 100}%`,
              backgroundColor: interruptColor,
            }}
          />
        </div>
      )}

      {/* Guest present pip */}
      {guestPresent && (
        <div className="flex items-center gap-0.5">
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: "var(--color-fuchsia-400)" }}
          />
          <span className="text-[8px] text-fuchsia-400">guest</span>
        </div>
      )}
    </div>
  );
}
