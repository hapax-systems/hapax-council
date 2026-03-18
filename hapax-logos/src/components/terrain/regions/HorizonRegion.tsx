import { Region } from "../Region";
import { useBriefing, useNudges } from "../../../api/hooks";
import { GoalsPanel } from "../../sidebar/GoalsPanel";
import { NudgeList } from "../../dashboard/NudgeList";
import { CopilotBanner } from "../../dashboard/CopilotBanner";
import { EnginePanel } from "../../sidebar/EnginePanel";

function HorizonSurface() {
  const { data: briefing } = useBriefing();
  const { data: nudges } = useNudges();

  const oneLiner = (briefing as any)?.one_liner ?? "";
  const nudgeItems = (nudges as any)?.nudges ?? [];
  const topNudges = nudgeItems.slice(0, 3);

  return (
    <div className="h-full flex items-center gap-6 px-6">
      {/* Briefing one-liner */}
      <div className="text-xs text-zinc-400 flex-1 truncate">{oneLiner || "—"}</div>

      {/* Top nudges as compact pills */}
      <div className="flex gap-2">
        {topNudges.map((n: any, i: number) => (
          <div
            key={n.source_id ?? i}
            className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800/60 text-zinc-500 truncate max-w-[200px]"
          >
            {n.title ?? n.message ?? "nudge"}
          </div>
        ))}
        {nudgeItems.length > 3 && (
          <div className="text-[10px] text-zinc-600">+{nudgeItems.length - 3}</div>
        )}
      </div>
    </div>
  );
}

export function HorizonRegion() {
  return (
    <Region name="horizon" className="col-span-3">
      {(depth) => (
        <div className="h-full">
          {depth === "surface" && <HorizonSurface />}
          {depth !== "surface" && (
            <div className="h-full overflow-y-auto p-3">
              <div className="grid grid-cols-3 gap-3">
                <GoalsPanel />
                <div>
                  <CopilotBanner />
                  <NudgeList />
                </div>
                <EnginePanel />
              </div>
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
