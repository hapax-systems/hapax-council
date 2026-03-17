import { invoke } from "@tauri-apps/api/core";

const BASE = "/api";

// Detect if running inside Tauri webview
const IS_TAURI = "__TAURI_INTERNALS__" in window;

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

/** Invoke a Tauri command if running in Tauri, otherwise fall back to HTTP. */
async function tauriOrHttp<T>(command: string, httpPath: string, args?: Record<string, unknown>): Promise<T> {
  if (IS_TAURI) {
    return invoke<T>(command, args);
  }
  return get<T>(httpPath);
}

export function sseUrl(path: string): string {
  return `${BASE}${path}`;
}

export const api = {
  // --- Tier 1: Tauri commands (file I/O) ---
  health: () => tauriOrHttp<import("./types").HealthSnapshot | null>("get_health", "/health"),
  gpu: () => tauriOrHttp<import("./types").VramSnapshot | null>("get_gpu", "/gpu"),
  infrastructure: () => tauriOrHttp<import("./types").Infrastructure>("get_infrastructure", "/infrastructure"),
  healthHistory: (days = 7) =>
    IS_TAURI
      ? invoke<import("./types").HealthHistory>("get_health_history", { days })
      : get<import("./types").HealthHistory>(`/health/history?days=${days}`),
  cycleMode: () => tauriOrHttp<import("./types").CycleModeResponse>("get_cycle_mode", "/cycle-mode"),
  setCycleMode: (mode: "dev" | "prod") =>
    IS_TAURI
      ? invoke<import("./types").CycleModeResponse>("set_cycle_mode", { mode })
      : put<import("./types").CycleModeResponse>("/cycle-mode", { mode }),
  accommodations: () => tauriOrHttp<import("./types").AccommodationSet>("get_accommodations", "/accommodations"),
  manual: () => tauriOrHttp<import("./types").ManualResponse>("get_manual", "/manual"),
  goals: () => tauriOrHttp<import("./types").GoalSnapshot>("get_goals", "/goals"),
  scout: () => tauriOrHttp<import("./types").ScoutData | null>("get_scout", "/scout"),
  scoutDecisions: () => tauriOrHttp<import("./types").ScoutDecisionsResponse>("get_scout_decisions", "/scout/decisions"),
  drift: () => tauriOrHttp<import("./types").DriftSummary | null>("get_drift", "/drift"),
  management: () => tauriOrHttp<import("./types").ManagementSnapshot>("get_management", "/management"),
  nudges: () => tauriOrHttp<import("./types").Nudge[]>("get_nudges", "/nudges"),
  readiness: () => tauriOrHttp<import("./types").ReadinessSnapshot>("get_readiness", "/readiness"),
  agents: () => tauriOrHttp<import("./types").AgentInfo[]>("get_agents", "/agents"),
  briefing: () => tauriOrHttp<import("./types").BriefingData | null>("get_briefing", "/briefing"),
  studio: () => tauriOrHttp<import("./types").StudioSnapshot>("get_studio", "/studio"),
  studioStreamInfo: () => tauriOrHttp<import("./types").StudioStreamInfo>("get_studio_stream_info", "/studio/stream/info"),
  perception: () => tauriOrHttp<import("./types").PerceptionState>("get_perception", "/studio/perception"),
  visualLayer: () => tauriOrHttp<import("./types").VisualLayerState>("get_visual_layer", "/studio/visual-layer"),
  selectEffect: (preset: string) =>
    IS_TAURI
      ? invoke<{ status: string; preset: string }>("select_effect", { preset })
      : post<{ status: string; preset: string }>("/studio/effect/select", { preset }),
  demos: () => tauriOrHttp<import("./types").Demo[]>("get_demos", "/demos"),
  demo: (id: string) =>
    IS_TAURI
      ? invoke<import("./types").Demo>("get_demo", { id })
      : get<import("./types").Demo>(`/demos/${id}`),

  // --- Tier 2: Tauri commands (Qdrant/Langfuse direct) ---
  cost: () => tauriOrHttp<import("./types").CostSnapshot>("get_cost", "/cost"),

  // --- Tier 3: Always HTTP (LLM orchestration) ---
  copilot: () => get<import("./types").CopilotResponse>("/copilot"),
  scoutDecide: (component: string, decision: string, notes?: string) =>
    post<import("./types").ScoutDecision>(`/scout/${component}/decide`, { decision, notes: notes ?? "" }),
  deleteDemo: (id: string) => del<{ deleted: string }>(`/demos/${id}`),

  // POST/DELETE helpers for mutations
  post,
  del,
};
