import { useInfrastructure } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

const stateColor: Record<string, string> = {
  running: "text-green-400",
  exited: "text-red-400",
  restarting: "text-yellow-400",
};

const healthColor: Record<string, string> = {
  healthy: "bg-green-500",
  unhealthy: "bg-red-500",
  starting: "bg-yellow-500",
};

export function ContainersPanel() {
  const { data: infra, dataUpdatedAt } = useInfrastructure();

  const containers = infra?.containers ?? [];
  if (containers.length === 0) return null;

  const healthy = containers.filter((c) => c.health === "healthy").length;
  const total = containers.length;

  return (
    <SidebarSection title="Containers" age={infra ? formatAge(dataUpdatedAt) : undefined}>
      <p className={healthy === total ? "text-green-400" : "text-yellow-400"}>
        {healthy}/{total} healthy
      </p>
      {containers
        .filter((c) => c.health !== "healthy" || c.state !== "running")
        .slice(0, 4)
        .map((c) => (
          <div key={c.name} className="flex items-center gap-1.5">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${healthColor[c.health] ?? "bg-zinc-500"}`} />
            <span className="truncate text-zinc-400">{c.service}</span>
            <span className={`text-zinc-500 ${stateColor[c.state] ?? ""}`}>{c.state}</span>
          </div>
        ))}
    </SidebarSection>
  );
}
