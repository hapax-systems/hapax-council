import { useReadiness } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

export function FreshnessPanel() {
  const { data: readiness, dataUpdatedAt } = useReadiness();

  return (
    <SidebarSection title="Readiness" loading={!readiness} age={readiness ? formatAge(dataUpdatedAt) : undefined}>
      {readiness && (
        <div className="space-y-0.5">
          <p className="capitalize">{readiness.level}</p>
          <p className="text-zinc-500">
            {readiness.populated_dimensions}/{readiness.total_dimensions} dimensions ·{" "}
            {readiness.total_facts} facts
          </p>
          <p className="text-zinc-500">
            {readiness.interview_conducted ? "Interview conducted" : "No interview"} ·{" "}
            {readiness.interview_fact_count} interview facts
          </p>
          <p className="text-zinc-500">
            Priorities {readiness.priorities_known ? "known" : "not validated"} · Neurocognitive{" "}
            {readiness.neurocognitive_mapped ? "mapped" : "undiscovered"}
          </p>
          {readiness.top_gap && <p className="text-yellow-400">Gap: {readiness.top_gap}</p>}
        </div>
      )}
    </SidebarSection>
  );
}
