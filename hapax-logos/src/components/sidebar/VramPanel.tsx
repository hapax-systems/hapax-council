import { useGpu } from "../../api/hooks";
import { SidebarSection } from "./SidebarSection";
import { formatAge } from "../../utils";

export function VramPanel() {
  const { data: gpu, dataUpdatedAt } = useGpu();

  const barColor =
    gpu && gpu.usage_pct >= 90
      ? "bg-red-500"
      : gpu && gpu.usage_pct >= 80
        ? "bg-orange-500"
        : "bg-blue-500";

  const pctColor =
    gpu && gpu.usage_pct >= 90
      ? "text-red-400"
      : gpu && gpu.usage_pct >= 80
        ? "text-orange-400"
        : "";

  return (
    <SidebarSection title="VRAM" age={gpu ? formatAge(dataUpdatedAt) : undefined}>
      {gpu ? (
        <>
          <div className="mb-1 flex justify-between">
            <span>{gpu.name}</span>
            <span className={pctColor}>{gpu.usage_pct.toFixed(0)}%</span>
          </div>
          <div className="h-2 rounded-full bg-zinc-700">
            <div
              className={`h-2 rounded-full ${barColor} transition-all`}
              style={{ width: `${gpu.usage_pct}%` }}
            />
          </div>
          <p className="mt-1 text-zinc-500">
            {gpu.used_mb}MB / {gpu.total_mb}MB — {gpu.temperature_c}°C
          </p>
          {gpu.loaded_models.length > 0 && (
            <p className="text-zinc-400">{gpu.loaded_models.join(", ")}</p>
          )}
        </>
      ) : (
        <p className="text-zinc-500">unavailable</p>
      )}
    </SidebarSection>
  );
}
