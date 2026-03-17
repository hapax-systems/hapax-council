import { useState, useEffect } from "react";
import { useCopilot, useHealth, useInfrastructure, useGpu, useBriefing } from "../../api/hooks";
import { AlertTriangle, Info, MessageCircle } from "lucide-react";

export function CopilotBanner() {
  const { data: copilot } = useCopilot();
  const { data: health } = useHealth();
  const { data: infra } = useInfrastructure();
  const { data: gpu } = useGpu();
  const { data: briefing } = useBriefing();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  let message = "System operational.";
  if (copilot?.message) {
    message = copilot.message;
  } else if (health) {
    if (health.overall_status === "healthy") {
      message = `All systems nominal — ${health.healthy} checks passing.`;
    } else if (health.overall_status === "degraded") {
      message = `${health.degraded} degraded checks detected. Review health panel for details.`;
    } else if (health.overall_status === "failed") {
      message = `${health.failed} checks failing. Immediate attention recommended.`;
    }
  }

  const severity = health?.overall_status === "failed"
    ? "critical"
    : health?.overall_status === "degraded"
      ? "warn"
      : "info";

  const styles = {
    critical: "border-red-500/50 bg-red-500/10 text-red-300",
    warn: "border-yellow-500/50 bg-yellow-500/10 text-yellow-300",
    info: "border-zinc-700/50 bg-zinc-800/50 text-zinc-400",
  };

  const Icon = severity === "critical" ? AlertTriangle : severity === "warn" ? Info : MessageCircle;

  // Metrics line
  const containers = infra?.containers.filter((c) => c.state === "running").length ?? 0;
  const freeGb = gpu ? (gpu.free_mb / 1024).toFixed(1) : null;
  let briefingAge: string | null = null;
  if (briefing?.generated_at) {
    const hours = Math.floor((now - new Date(briefing.generated_at).getTime()) / 3_600_000);
    briefingAge = `${hours}h`;
  }

  return (
    <div className={`rounded border px-3 py-2 transition-colors ${styles[severity]}`}>
      <div className="flex items-center gap-2 text-sm">
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span>{message}</span>
      </div>
      {health && (
        <div className="mt-1 flex items-center gap-3 pl-5.5 text-xs opacity-70">
          <span>{health.healthy}/{health.total_checks} checks</span>
          <span className="text-zinc-600">·</span>
          <span>{containers} containers</span>
          {freeGb && (
            <>
              <span className="text-zinc-600">·</span>
              <span>{freeGb}GB VRAM free</span>
            </>
          )}
          {briefingAge && (
            <>
              <span className="text-zinc-600">·</span>
              <span>Briefing {briefingAge} ago</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
