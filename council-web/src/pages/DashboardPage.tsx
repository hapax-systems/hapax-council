import { Sidebar } from "../components/Sidebar";
import { MainPanel } from "../components/MainPanel";
import { CopilotBanner } from "../components/dashboard/CopilotBanner";

export function DashboardPage() {
  return (
    <>
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b border-zinc-800 px-4 py-3">
          <CopilotBanner />
        </div>
        <MainPanel />
      </div>
      <Sidebar />
    </>
  );
}
