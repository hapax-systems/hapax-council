import { useManagement } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

export function ManagementPanel() {
  const { data: mgmt, dataUpdatedAt } = useManagement();

  if (!mgmt) return <SidebarSection title="Management" loading>{null}</SidebarSection>;
  if (mgmt.people.length === 0) return null;

  const stale1on1s = mgmt.people.filter((p) => p.stale_1on1).length;
  const highLoad = mgmt.people.filter(
    (p) => p.cognitive_load !== null && p.cognitive_load >= 4
  ).length;

  return (
    <SidebarSection title="Team" age={mgmt ? formatAge(dataUpdatedAt) : undefined}>
      <p>
        {mgmt.people.length} people
        {stale1on1s > 0 && <span className="text-yellow-400"> · {stale1on1s} stale 1:1s</span>}
        {highLoad > 0 && <span className="text-orange-400"> · {highLoad} high load</span>}
      </p>
      <p className="text-zinc-500">
        {mgmt.coaching.length} coaching · {mgmt.feedback.length} feedback
      </p>
    </SidebarSection>
  );
}
