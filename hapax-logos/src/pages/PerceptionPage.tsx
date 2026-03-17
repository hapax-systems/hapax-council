import { useState } from "react";
import { PerceptionCanvas } from "../components/perception/PerceptionCanvas";
import { PerceptionSidebar } from "../components/perception/PerceptionSidebar";
import { PerceptionMeter } from "../components/perception/PerceptionMeter";
import type { SignalCategory } from "../contexts/ClassificationOverlayContext";
import { useOverlay } from "../contexts/ClassificationOverlayContext";

export function PerceptionPage() {
  const { perception } = useOverlay();
  const [activeZone, setActiveZone] = useState<SignalCategory | null>(null);

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Main content */}
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between">
          <h1 className="text-sm font-semibold text-zinc-100">Perception</h1>
          <span className="text-[10px] text-zinc-500">
            Classification overlay
          </span>
        </div>

        {/* Center canvas */}
        <div className="relative min-h-0 flex-1">
          <PerceptionCanvas activeZone={activeZone} onZoneClick={setActiveZone} />
        </div>

        {/* Bottom meters */}
        <div className="shrink-0 rounded-lg border border-zinc-800 bg-zinc-900/50">
          <PerceptionMeter perception={perception} />
        </div>
      </div>

      {/* Right sidebar — channel strip mixer */}
      <PerceptionSidebar activeZone={activeZone} onZoneSelect={setActiveZone} />
    </div>
  );
}
