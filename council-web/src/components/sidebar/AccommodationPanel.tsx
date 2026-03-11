import { useAccommodations } from "../../api/hooks";
import { useAccommodationAction } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { useToast } from "../shared/ToastProvider";

export function AccommodationPanel() {
  const { data: accommodations } = useAccommodations();
  const action = useAccommodationAction();
  const { addToast } = useToast();

  const active = accommodations?.accommodations.filter((a) => a.active) ?? [];

  function handleAction(id: string, type: "confirm" | "disable") {
    action.mutate(
      { id, action: type },
      { onError: () => addToast(`Failed to ${type} accommodation`, "error") },
    );
  }

  return (
    <SidebarSection title="Accommodations" loading={!accommodations}>
      {accommodations && (
        <>
          <p>{active.length} active</p>
          {active.map((a) => (
            <div key={a.id} className="flex items-start justify-between gap-1">
              <p className="text-zinc-400">
                <span className="text-zinc-500">{a.pattern_category}:</span> {a.description}
              </p>
              <div className="flex shrink-0 gap-1">
                {!a.confirmed_at && (
                  <button
                    onClick={() => handleAction(a.id, "confirm")}
                    className="text-[10px] text-green-400 hover:underline"
                  >
                    confirm
                  </button>
                )}
                <button
                  onClick={() => handleAction(a.id, "disable")}
                  className="text-[10px] text-zinc-500 hover:underline"
                >
                  disable
                </button>
              </div>
            </div>
          ))}
          {active.length === 0 && <p className="text-zinc-500">None active.</p>}
        </>
      )}
    </SidebarSection>
  );
}
