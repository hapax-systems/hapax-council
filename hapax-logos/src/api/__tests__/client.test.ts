import { describe, it, expect, vi, beforeEach } from "vitest";

// vi.hoisted runs before imports, so the mock factory can reference it
const { mockInvoke } = vi.hoisted(() => ({
  mockInvoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: mockInvoke,
}));

import { api } from "../client";

describe("api client (invoke-only)", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
    mockInvoke.mockResolvedValue({});
  });

  // --- Tier 1: no-arg commands ---

  const noArgCommands: [string, keyof typeof api, string][] = [
    ["health", "health", "get_health"],
    ["gpu", "gpu", "get_gpu"],
    ["infrastructure", "infrastructure", "get_infrastructure"],
    ["workingMode", "workingMode", "get_working_mode"],
    ["accommodations", "accommodations", "get_accommodations"],
    ["manual", "manual", "get_manual"],
    ["goals", "goals", "get_goals"],
    ["scout", "scout", "get_scout"],
    ["scoutDecisions", "scoutDecisions", "get_scout_decisions"],
    ["drift", "drift", "get_drift"],
    ["management", "management", "get_management"],
    ["nudges", "nudges", "get_nudges"],
    ["readiness", "readiness", "get_readiness"],
    ["agents", "agents", "get_agents"],
    ["briefing", "briefing", "get_briefing"],
    ["studio", "studio", "get_studio"],
    ["studioStreamInfo", "studioStreamInfo", "get_studio_stream_info"],
    ["perception", "perception", "get_perception"],
    ["visualLayer", "visualLayer", "get_visual_layer"],
    ["demos", "demos", "get_demos"],
  ];

  it.each(noArgCommands)("%s invokes %s with no args", async (_, method, cmd) => {
    await (api[method] as () => Promise<unknown>)();
    expect(mockInvoke).toHaveBeenCalledWith(cmd);
  });

  // --- Tier 1: commands with args ---

  it("healthHistory passes days arg", async () => {
    await api.healthHistory(14);
    expect(mockInvoke).toHaveBeenCalledWith("get_health_history", { days: 14 });
  });

  it("healthHistory defaults to 7 days", async () => {
    await api.healthHistory();
    expect(mockInvoke).toHaveBeenCalledWith("get_health_history", { days: 7 });
  });

  it("setWorkingMode passes mode", async () => {
    await api.setWorkingMode("rnd");
    expect(mockInvoke).toHaveBeenCalledWith("set_working_mode", { mode: "rnd" });
  });

  it("selectEffect passes preset", async () => {
    await api.selectEffect("ghost");
    expect(mockInvoke).toHaveBeenCalledWith("select_effect", { preset: "ghost" });
  });

  it("demo passes id", async () => {
    await api.demo("abc123");
    expect(mockInvoke).toHaveBeenCalledWith("get_demo", { id: "abc123" });
  });

  // --- Proxy commands (no-arg) ---

  it("cost uses active FastAPI proxy path", async () => {
    await api.cost();
    expect(mockInvoke).toHaveBeenCalledWith("proxy_get_generic", { path: "/cost" });
  });

  const proxyNoArgCommands: [string, keyof typeof api, string][] = [
    ["compositorLive", "compositorLive", "proxy_compositor_live"],
    ["studioDisk", "studioDisk", "proxy_studio_disk"],
    ["enableRecording", "enableRecording", "proxy_enable_recording"],
    ["disableRecording", "disableRecording", "proxy_disable_recording"],
    ["copilot", "copilot", "proxy_copilot"],
    ["consentContracts", "consentContracts", "proxy_consent_contracts"],
    ["consentCoverage", "consentCoverage", "proxy_consent_coverage"],
    ["consentOverhead", "consentOverhead", "proxy_consent_overhead"],
    ["consentPrecedents", "consentPrecedents", "proxy_consent_precedents"],
    ["governanceHeartbeat", "governanceHeartbeat", "proxy_governance_heartbeat"],
    ["governanceCoverage", "governanceCoverage", "proxy_governance_coverage"],
    ["governanceCarriers", "governanceCarriers", "proxy_governance_carriers"],
    ["engineStatus", "engineStatus", "proxy_engine_status"],
    ["engineRules", "engineRules", "proxy_engine_rules"],
    ["engineHistory", "engineHistory", "proxy_engine_history"],
    ["profile", "profile", "proxy_profile"],
    ["profilePending", "profilePending", "proxy_profile_pending"],
    ["insightQueries", "insightQueries", "proxy_insight_queries"],
    ["fortressState", "fortressState", "proxy_fortress_state"],
    ["fortressGovernance", "fortressGovernance", "proxy_fortress_governance"],
    ["fortressGoals", "fortressGoals", "proxy_fortress_goals"],
    ["fortressEvents", "fortressEvents", "proxy_fortress_events"],
    ["fortressMetrics", "fortressMetrics", "proxy_fortress_metrics"],
    ["fortressSessions", "fortressSessions", "proxy_fortress_sessions"],
    ["fortressChronicle", "fortressChronicle", "proxy_fortress_chronicle"],
  ];

  it.each(proxyNoArgCommands)("%s invokes %s with no args", async (_, method, cmd) => {
    await (api[method] as () => Promise<unknown>)();
    expect(mockInvoke).toHaveBeenCalledWith(cmd);
  });

  // --- Proxy commands with args ---

  it("scoutDecide passes component, decision, notes", async () => {
    await api.scoutDecide("redis", "adopted", "good fit");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_scout_decide", {
      component: "redis",
      decision: "adopted",
      notes: "good fit",
    });
  });

  it("scoutDecide defaults notes to empty string", async () => {
    await api.scoutDecide("redis", "adopted");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_scout_decide", {
      component: "redis",
      decision: "adopted",
      notes: "",
    });
  });

  it("deleteDemo passes id", async () => {
    await api.deleteDemo("demo-1");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_delete_demo", { id: "demo-1" });
  });

  it("consentTrace passes path or null", async () => {
    await api.consentTrace("/some/path");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_consent_trace", { path: "/some/path" });

    mockInvoke.mockReset();
    mockInvoke.mockResolvedValue({});
    await api.consentTrace();
    expect(mockInvoke).toHaveBeenCalledWith("proxy_consent_trace", { path: null });
  });

  it("profileDimension passes dim", async () => {
    await api.profileDimension("openness");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_profile_dimension", { dim: "openness" });
  });

  it("insightQuery passes id", async () => {
    await api.insightQuery("q-1");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_insight_query", { id: "q-1" });
  });

  it("runInsightQuery passes query", async () => {
    await api.runInsightQuery("what is drift?");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_run_insight_query", {
      query: "what is drift?",
    });
  });

  it("refineInsightQuery passes all args", async () => {
    await api.refineInsightQuery("refined?", "parent-1", "prior result", "research");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_refine_insight_query", {
      query: "refined?",
      parentId: "parent-1",
      priorResult: "prior result",
      agentType: "research",
    });
  });

  it("deleteInsightQuery passes id", async () => {
    await api.deleteInsightQuery("q-2");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_delete_insight_query", { id: "q-2" });
  });

  // --- Generic proxy helpers ---

  it("post invokes proxy_post with path and body", async () => {
    await api.post("/nudges/src-1/act", { action: "do" });
    expect(mockInvoke).toHaveBeenCalledWith("proxy_post", {
      path: "/nudges/src-1/act",
      body: { action: "do" },
    });
  });

  it("post defaults body to null", async () => {
    await api.post("/some/path");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_post", {
      path: "/some/path",
      body: null,
    });
  });

  it("put invokes proxy_put with path and body", async () => {
    await api.put("/nudges/src-1", { action: "update" });
    expect(mockInvoke).toHaveBeenCalledWith("proxy_put", {
      path: "/nudges/src-1",
      body: { action: "update" },
    });
  });

  it("get invokes proxy_get_generic with path", async () => {
    await api.get("/chat/sessions/abc");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_get_generic", {
      path: "/chat/sessions/abc",
    });
  });

  it("del invokes proxy_delete with path", async () => {
    await api.del("/agents/runs/current");
    expect(mockInvoke).toHaveBeenCalledWith("proxy_delete", {
      path: "/agents/runs/current",
    });
  });

  // --- No HTTP remnants ---

  it("does not export IS_TAURI, BASE, tauriOrHttp", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mod = api as any;
    expect(mod.IS_TAURI).toBeUndefined();
    expect(mod.BASE).toBeUndefined();
    expect(mod.tauriOrHttp).toBeUndefined();
  });
});
