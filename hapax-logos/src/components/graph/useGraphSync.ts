import { useEffect } from "react";
import { useStudioGraph } from "../../stores/studioGraphStore";
import { useCompositorLive } from "../../api/hooks";
import { api } from "../../api/client";

/**
 * Sync graph canvas state with backend:
 * - Poll camera statuses from compositor
 */
export function useGraphSync() {
  const setCameraStatuses = useStudioGraph((s) => s.setCameraStatuses);
  const { data: compositor } = useCompositorLive();

  useEffect(() => {
    if (!compositor?.cameras) return;
    const statuses: Record<string, "active" | "offline" | "starting"> = {};
    for (const [role, status] of Object.entries(compositor.cameras)) {
      statuses[role] = status as "active" | "offline" | "starting";
    }
    setCameraStatuses(statuses);
  }, [compositor?.cameras, setCameraStatuses]);
}

/** Activate a preset on the backend. */
export async function activatePreset(presetName: string): Promise<void> {
  await api.post("/studio/effect/select", { preset: presetName });
}
