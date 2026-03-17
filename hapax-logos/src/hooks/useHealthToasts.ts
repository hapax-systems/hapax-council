import { useRef, useEffect } from "react";
import { useHealth } from "../api/hooks";
import { useToast } from "../components/shared/ToastProvider";

export function useHealthToasts() {
  const { data: health } = useHealth();
  const { addToast } = useToast();
  const prevStatus = useRef<string | null>(null);

  useEffect(() => {
    if (!health) return;
    const current = health.overall_status;
    const prev = prevStatus.current;
    prevStatus.current = current;

    // Don't toast on first load
    if (prev === null) return;

    // Toast on status changes
    if (prev !== current) {
      if (current === "failed") {
        addToast(
          `Health degraded: ${health.failed} checks failing — ${health.failed_checks.slice(0, 3).join(", ")}`,
          "error"
        );
      } else if (current === "degraded") {
        addToast(`Health warning: ${health.degraded} checks degraded`, "warn");
      } else if (current === "healthy" && prev !== "healthy") {
        addToast(`All ${health.healthy} health checks passing`, "success");
      }
    }
  }, [health, addToast]);
}
