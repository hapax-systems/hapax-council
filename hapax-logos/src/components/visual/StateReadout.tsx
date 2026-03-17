interface StateReadoutProps {
  stance: string;
  speed: number;
  turbulence: number;
  colorWarmth: number;
  brightness: number;
  fps: number;
  frameTimeMs: number;
}

export function StateReadout({
  stance,
  speed,
  turbulence,
  colorWarmth,
  brightness,
  fps,
  frameTimeMs,
}: StateReadoutProps) {
  const stanceColor =
    stance === "nominal"
      ? "text-green-400"
      : stance === "cautious"
        ? "text-yellow-400"
        : stance === "degraded"
          ? "text-orange-400"
          : stance === "critical"
            ? "text-red-400"
            : "text-zinc-400";

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
        Surface State
      </h3>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
        <div className="flex justify-between">
          <span className="text-zinc-500">Stance</span>
          <span className={stanceColor}>{stance}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">FPS</span>
          <span className="text-zinc-300">{fps > 0 ? fps.toFixed(1) : "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Speed</span>
          <span className="text-zinc-300">{speed.toFixed(3)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Frame</span>
          <span className="text-zinc-300">
            {frameTimeMs > 0 ? `${frameTimeMs.toFixed(1)}ms` : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Turbulence</span>
          <span className="text-zinc-300">{turbulence.toFixed(3)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Warmth</span>
          <span className="text-zinc-300">{colorWarmth.toFixed(2)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Brightness</span>
          <span className="text-zinc-300">{brightness.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}
