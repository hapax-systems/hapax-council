import { invoke } from "@tauri-apps/api/core";

export const api = {
  // --- Tier 1: Tauri commands (file I/O) ---
  health: () => invoke<import("./types").HealthSnapshot | null>("get_health"),
  gpu: () => invoke<import("./types").VramSnapshot | null>("get_gpu"),
  infrastructure: () => invoke<import("./types").Infrastructure>("get_infrastructure"),
  healthHistory: (days = 7) => invoke<import("./types").HealthHistory>("get_health_history", { days }),
  workingMode: () => invoke<import("./types").WorkingModeResponse>("get_working_mode"),
  setWorkingMode: (mode: "research" | "rnd") =>
    invoke<import("./types").WorkingModeResponse>("set_working_mode", { mode }),
  accommodations: () => invoke<import("./types").AccommodationSet>("get_accommodations"),
  manual: () => invoke<import("./types").ManualResponse>("get_manual"),
  goals: () => invoke<import("./types").GoalSnapshot>("get_goals"),
  scout: () => invoke<import("./types").ScoutData | null>("get_scout"),
  scoutDecisions: () => invoke<import("./types").ScoutDecisionsResponse>("get_scout_decisions"),
  drift: () => invoke<import("./types").DriftSummary | null>("get_drift"),
  management: () => invoke<import("./types").ManagementSnapshot>("get_management"),
  nudges: () => invoke<import("./types").Nudge[]>("get_nudges"),
  readiness: () => invoke<import("./types").ReadinessSnapshot>("get_readiness"),
  agents: () => invoke<import("./types").AgentInfo[]>("get_agents"),
  briefing: () => invoke<import("./types").BriefingData | null>("get_briefing"),
  studio: () => invoke<import("./types").StudioSnapshot>("get_studio"),
  studioStreamInfo: () => invoke<import("./types").StudioStreamInfo>("get_studio_stream_info"),
  perception: () => invoke<import("./types").PerceptionState>("get_perception"),
  visualLayer: () => invoke<import("./types").VisualLayerState>("get_visual_layer"),
  selectEffect: (preset: string) =>
    invoke<{ status: string; preset: string }>("select_effect", { preset }),
  demos: () => invoke<import("./types").Demo[]>("get_demos"),
  demo: (id: string) => invoke<import("./types").Demo>("get_demo", { id }),

  // --- Tier 2: Tauri commands (Qdrant/Langfuse direct) ---
  cost: () => invoke<import("./types").CostSnapshot>("get_cost"),

  // --- Proxy commands (Rust → FastAPI at :8051) ---

  // Studio
  compositorLive: () => invoke<import("./types").LiveCompositorStatus>("proxy_compositor_live"),
  studioDisk: () => invoke<import("./types").StudioDisk>("proxy_studio_disk"),
  enableRecording: () => invoke<{ status: string }>("proxy_enable_recording"),
  disableRecording: () => invoke<{ status: string }>("proxy_disable_recording"),

  // Copilot
  copilot: () => invoke<import("./types").CopilotResponse>("proxy_copilot"),

  // Scout mutations
  scoutDecide: (component: string, decision: string, notes?: string) =>
    invoke<import("./types").ScoutDecision>("proxy_scout_decide", {
      component,
      decision,
      notes: notes ?? "",
    }),

  // Demo mutations
  deleteDemo: (id: string) => invoke<{ deleted: string }>("proxy_delete_demo", { id }),

  // Governance & Consent
  consentContracts: () => invoke<unknown[]>("proxy_consent_contracts"),
  consentTrace: (path?: string) => invoke<unknown>("proxy_consent_trace", { path: path ?? null }),
  consentCoverage: () => invoke<unknown>("proxy_consent_coverage"),
  consentOverhead: () => invoke<unknown>("proxy_consent_overhead"),
  consentPrecedents: () => invoke<unknown[]>("proxy_consent_precedents"),
  governanceHeartbeat: () =>
    invoke<import("./types").GovernanceHeartbeat>("proxy_governance_heartbeat"),
  governanceCoverage: () => invoke<unknown>("proxy_governance_coverage"),
  governanceCarriers: () => invoke<unknown>("proxy_governance_carriers"),

  // Engine
  engineStatus: () => invoke<unknown>("proxy_engine_status"),
  engineRules: () => invoke<unknown[]>("proxy_engine_rules"),
  engineHistory: () => invoke<unknown[]>("proxy_engine_history"),

  // Profile
  profile: () => invoke<unknown>("proxy_profile"),
  profileDimension: (dim: string) => invoke<unknown>("proxy_profile_dimension", { dim }),
  profilePending: () => invoke<unknown>("proxy_profile_pending"),

  // Insight Queries
  insightQueries: () => invoke<import("./types").InsightQueryList>("proxy_insight_queries"),
  insightQuery: (id: string) =>
    invoke<import("./types").InsightQuery>("proxy_insight_query", { id }),
  runInsightQuery: (query: string) =>
    invoke<{ id: string; status: string }>("proxy_run_insight_query", { query }),
  refineInsightQuery: (query: string, parentId: string, priorResult: string, agentType: string) =>
    invoke<{ id: string; status: string }>("proxy_refine_insight_query", {
      query,
      parentId,
      priorResult,
      agentType,
    }),
  deleteInsightQuery: (id: string) =>
    invoke<{ deleted: string }>("proxy_delete_insight_query", { id }),

  // Orientation
  orientation: () => invoke<import("./types").OrientationState>("get_orientation"),

  // Refusals — first-class display surface for the refusal-as-data
  // substrate. Polls the awareness API every 30s; SSE-driven refresh
  // arrives via the awareness-tauri-sse-bridge cc-task (separate ship).
  refusals: (limit = 50) =>
    invoke<import("./types").RefusalsResponse>("proxy_get_generic", {
      path: `/refusals?limit=${limit}`,
    }),

  // CC-hygiene state — Tauri-direct file read (Rust commands::cc_hygiene)
  ccHygieneState: () =>
    invoke<import("./types").CcHygieneStateResponse>("get_cc_hygiene_state"),

  // Fortress
  fortressState: () => invoke<import("./types").FortressState>("proxy_fortress_state"),
  fortressGovernance: () =>
    invoke<import("./types").FortressGovernance>("proxy_fortress_governance"),
  fortressGoals: () => invoke<import("./types").FortressGoals>("proxy_fortress_goals"),
  fortressEvents: () => invoke<import("./types").FortressEvents>("proxy_fortress_events"),
  fortressMetrics: () => invoke<import("./types").FortressMetrics>("proxy_fortress_metrics"),
  fortressSessions: () => invoke<import("./types").FortressSessions>("proxy_fortress_sessions"),
  fortressChronicle: () => invoke<import("./types").FortressChronicle>("proxy_fortress_chronicle"),

  // Generic proxy helpers (used by ChatProvider and hooks for dynamic paths)
  get: <T>(path: string) => invoke<T>("proxy_get_generic", { path }),
  post: <T>(path: string, body?: unknown) =>
    invoke<T>("proxy_post", { path, body: body ?? null }),
  put: <T>(path: string, body?: unknown) =>
    invoke<T>("proxy_put", { path, body: body ?? null }),
  patch: <T>(path: string, body?: unknown) =>
    invoke<T>("proxy_patch", { path, body: body ?? null }),
  del: <T>(path: string) => invoke<T>("proxy_delete", { path }),
};
