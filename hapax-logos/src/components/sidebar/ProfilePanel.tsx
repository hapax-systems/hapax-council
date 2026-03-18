import { useProfile, useProfilePending } from "../../api/hooks";

export function ProfilePanel() {
  const { data: profile } = useProfile();
  const { data: pending } = useProfilePending();

  const dims = profile as any;
  const pendingFacts = pending as any;
  const pendingCount = pendingFacts?.count ?? pendingFacts?.pending ?? (Array.isArray(pendingFacts) ? pendingFacts.length : 0);

  // Profile response may be a dict of dimension names → fact counts or a structured object
  const dimensions = dims && typeof dims === "object" && !Array.isArray(dims)
    ? Object.entries(dims.dimensions ?? dims).filter(([k]) => k !== "version" && k !== "operator")
    : [];

  return (
    <div className="space-y-2 text-xs">
      {dimensions.length > 0 ? (
        dimensions.map(([name, val]: [string, any]) => {
          const count = typeof val === "number" ? val : (val?.fact_count ?? val?.count ?? "—");
          const kind = val?.kind ?? "";
          return (
            <div key={name} className="flex justify-between">
              <span className="text-zinc-500 truncate max-w-[65%]">{name.replace(/_/g, " ")}</span>
              <span className="text-zinc-400">
                {count}
                {kind && <span className="text-zinc-600 ml-1 text-[9px]">{kind}</span>}
              </span>
            </div>
          );
        })
      ) : (
        <div className="text-zinc-600 text-[10px]">No profile data available</div>
      )}

      {pendingCount > 0 && (
        <div className="flex justify-between pt-1 border-t border-zinc-800">
          <span className="text-zinc-500">pending facts</span>
          <span className="text-amber-400">{pendingCount}</span>
        </div>
      )}
    </div>
  );
}
