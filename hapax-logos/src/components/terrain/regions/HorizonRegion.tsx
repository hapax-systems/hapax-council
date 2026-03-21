import { memo } from "react";
import { Region } from "../Region";
import { useBriefing, useNudges } from "../../../api/hooks";
import { GoalsPanel } from "../../sidebar/GoalsPanel";
import { NudgeList } from "../../dashboard/NudgeList";
import { CopilotBanner } from "../../dashboard/CopilotBanner";
import { EnginePanel } from "../../sidebar/EnginePanel";
import { BriefingPanel } from "../../sidebar/BriefingPanel";
import { SignalCluster, densityFromDepth } from "../signals/SignalCluster";
import { useSignals } from "../../../contexts/ClassificationOverlayContext";

function HorizonSurface() {
  const { data: briefing } = useBriefing();
  const { data: nudges } = useNudges();

  const oneLiner = briefing?.one_liner ?? "";
  const nudgeItems = nudges ?? [];
  const topNudges = nudgeItems.slice(0, 3);

  return (
    <div className="h-full flex items-center gap-6 px-6">
      {/* Briefing one-liner */}
      <div className="text-xs text-zinc-400 flex-1 truncate">{oneLiner || "—"}</div>

      {/* Top nudges as compact pills */}
      <div className="flex gap-2">
        {topNudges.map((n, i) => (
          <div
            key={n.source_id ?? i}
            className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800/60 text-zinc-500 truncate max-w-[200px]"
          >
            {n.title ?? "nudge"}
          </div>
        ))}
        {nudgeItems.length > 3 && (
          <div className="text-[10px] text-zinc-600">+{nudgeItems.length - 3}</div>
        )}
      </div>
    </div>
  );
}

export const HorizonRegion = memo(function HorizonRegion() {
  const { signalsByRegion, stimmungStance } = useSignals();
  const horizonSignals = signalsByRegion.horizon;

  return (
    <Region name="horizon" className="col-span-3" style={{ zIndex: 0 }} stimmungStance={stimmungStance}>
      {(depth) => (
        <div className="h-full relative">
          {depth === "surface" && <HorizonSurface />}
          {depth === "stratum" && (
            <div className="h-full overflow-y-auto p-3">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <GoalsPanel />
                <div>
                  <CopilotBanner />
                  <NudgeList />
                </div>
                <EnginePanel />
              </div>
            </div>
          )}
          {depth === "core" && (
            <div className="h-full overflow-y-auto p-3">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <GoalsPanel />
                <div>
                  <CopilotBanner />
                  <NudgeList />
                </div>
                <EnginePanel />
                <div className="col-span-1 md:col-span-3">
                  <BriefingPanel />
                </div>
              </div>
            </div>
          )}

          {/* Signal pips — bottom-right at surface, inline at deeper depths */}
          {horizonSignals.length > 0 && (
            <SignalCluster
              signals={horizonSignals}
              density={densityFromDepth(depth)}
              className={
                depth === "surface"
                  ? "absolute bottom-1.5 right-8 pointer-events-none"
                  : depth === "core"
                    ? "absolute bottom-2 right-8"
                    : "absolute top-2 right-8"
              }
            />
          )}
        </div>
      )}
    </Region>
  );
});
