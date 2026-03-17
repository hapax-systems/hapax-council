const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

export function sseUrl(path: string): string {
  return `${BASE}${path}`;
}

export const api = {
  health: () => get<import("./types").HealthSnapshot | null>("/health"),
  gpu: () => get<import("./types").VramSnapshot | null>("/gpu"),
  infrastructure: () => get<import("./types").Infrastructure>("/infrastructure"),
  nudges: () => get<import("./types").Nudge[]>("/nudges"),
  briefing: () => get<import("./types").BriefingData | null>("/briefing"),
  goals: () => get<import("./types").GoalSnapshot>("/goals"),
  readiness: () => get<import("./types").ReadinessSnapshot>("/readiness"),
  agents: () => get<import("./types").AgentInfo[]>("/agents"),
  scout: () => get<import("./types").ScoutData | null>("/scout"),
  cost: () => get<import("./types").CostSnapshot>("/cost"),
  drift: () => get<import("./types").DriftSummary | null>("/drift"),
  management: () => get<import("./types").ManagementSnapshot>("/management"),
  accommodations: () => get<import("./types").AccommodationSet>("/accommodations"),
  healthHistory: (days = 7) => get<import("./types").HealthHistory>(`/health/history?days=${days}`),
  manual: () => get<import("./types").ManualResponse>("/manual"),
  copilot: () => get<import("./types").CopilotResponse>("/copilot"),
  cycleMode: () => get<import("./types").CycleModeResponse>("/cycle-mode"),
  setCycleMode: (mode: "dev" | "prod") => put<import("./types").CycleModeResponse>("/cycle-mode", { mode }),
  scoutDecisions: () => get<import("./types").ScoutDecisionsResponse>("/scout/decisions"),
  scoutDecide: (component: string, decision: string, notes?: string) =>
    post<import("./types").ScoutDecision>(`/scout/${component}/decide`, { decision, notes: notes ?? "" }),
  studio: () => get<import("./types").StudioSnapshot>("/studio"),
  studioStreamInfo: () => get<import("./types").StudioStreamInfo>("/studio/stream/info"),
  perception: () => get<import("./types").PerceptionState>("/studio/perception"),
  visualLayer: () => get<import("./types").VisualLayerState>("/studio/visual-layer"),
  selectEffect: (preset: string) =>
    post<{ status: string; preset: string }>("/studio/effect/select", { preset }),
  demos: () => get<import("./types").Demo[]>("/demos"),
  demo: (id: string) => get<import("./types").Demo>(`/demos/${id}`),
  deleteDemo: (id: string) => del<{ deleted: string }>(`/demos/${id}`),
  // POST/DELETE helpers exposed for Phase 2+
  post,
  del,
};

