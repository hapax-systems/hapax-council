/**
 * InvestigationTabs — Chat / Insight / Demos tabs inside the investigation overlay.
 */

import { Suspense, lazy } from "react";
import { useTerrain, type InvestigationTab } from "../../../contexts/TerrainContext";

const ChatPage = lazy(() =>
  import("../../../pages/ChatPage").then((m) => ({ default: m.ChatPage }))
);
const InsightPage = lazy(() =>
  import("../../../pages/InsightPage").then((m) => ({ default: m.InsightPage }))
);
const DemosPage = lazy(() =>
  import("../../../pages/DemosPage").then((m) => ({ default: m.DemosPage }))
);

const TABS: { id: InvestigationTab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "insight", label: "Insight" },
  { id: "demos", label: "Demos" },
];

export function InvestigationTabs() {
  const { investigationTab, setInvestigationTab } = useTerrain();

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex gap-1 px-4 pt-3 pb-2 border-b border-zinc-800/50">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setInvestigationTab(tab.id)}
            className={`px-3 py-1.5 text-[11px] uppercase tracking-[0.2em] rounded-md transition-colors ${
              investigationTab === tab.id
                ? "bg-zinc-800 text-zinc-200"
                : "text-zinc-600 hover:text-zinc-400"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-full text-zinc-600 text-xs">
              Loading...
            </div>
          }
        >
          {investigationTab === "chat" && <ChatPage />}
          {investigationTab === "insight" && <InsightPage />}
          {investigationTab === "demos" && <DemosPage />}
        </Suspense>
      </div>
    </div>
  );
}
