import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { WorkstreamHygieneView } from "../WorkstreamHygieneView";

vi.mock("../../../api/hooks", () => ({
  useCcHygieneState: () => ({
    data: {
      state: {
        schema_version: 1,
        sweep_timestamp: "2026-04-26T12:34:00Z",
        sweep_duration_ms: 50,
        killswitch_active: false,
        sessions: [
          { role: "alpha", current_claim: "task-a", in_progress_count: 1, relay_updated: null },
          { role: "beta", current_claim: null, in_progress_count: 0, relay_updated: null },
          { role: "delta", current_claim: "task-d", in_progress_count: 0, relay_updated: null },
        ],
        check_summaries: [
          { check_id: "stale_in_progress", fired: 2 },
          { check_id: "ghost_claimed", fired: 0 },
        ],
        events: [
          {
            timestamp: "2026-04-26T12:30:00Z",
            check_id: "stale_in_progress",
            task_id: "ef7b-99",
            message: "in_progress for >24h",
          },
        ],
      },
      mtime_unix: 1745672040,
    },
    dataUpdatedAt: Date.now(),
    isLoading: false,
  }),
}));

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe("WorkstreamHygieneView", () => {
  it("renders fired check_id summaries", () => {
    render(withClient(<WorkstreamHygieneView />));
    // Pill text + count is in the same node; multiple matches OK
    expect(screen.getAllByText(/stale_in_progress/).length).toBeGreaterThan(0);
  });

  it("hides check_ids that did not fire", () => {
    render(withClient(<WorkstreamHygieneView />));
    expect(screen.queryByText(/ghost_claimed/)).toBeNull();
  });

  it("renders the recent hygiene event row", () => {
    render(withClient(<WorkstreamHygieneView />));
    expect(screen.getByText(/in_progress for >24h/)).toBeInTheDocument();
    expect(screen.getByText(/ef7b-99/)).toBeInTheDocument();
  });

  it("renders one session dot per role (alpha/beta/delta/epsilon)", () => {
    const { container } = render(withClient(<WorkstreamHygieneView />));
    // Each role has a span with title="<role>: ..."; assert all 4 are present
    // even though epsilon is missing from sessions[] (empty-claim fallback).
    const alpha = container.querySelector('[title^="alpha:"]');
    const beta = container.querySelector('[title^="beta:"]');
    const delta = container.querySelector('[title^="delta:"]');
    const epsilon = container.querySelector('[title^="epsilon:"]');
    expect(alpha).not.toBeNull();
    expect(beta).not.toBeNull();
    expect(delta).not.toBeNull();
    expect(epsilon).not.toBeNull();
  });

  // CONSTITUTIONAL CI GUARD — workstream hygiene panel surfaces signals,
  // it does NOT operator-action them. Action wiring is deferred to a
  // follow-on cc-task (hygiene-actions UDS). Assert the rendered tree
  // contains zero buttons matching the action vocabulary so the panel
  // can never silently regress into a dispatch surface.
  it("contains zero acknowledge / clear / revert / dispatch affordances", () => {
    const { container } = render(withClient(<WorkstreamHygieneView />));
    const forbidden = /(ack|acknowledge|dismiss|clear|revert|retry|kill|action|dispatch)/i;
    const buttons = container.querySelectorAll("button");
    for (const btn of buttons) {
      expect(forbidden.test(btn.textContent ?? "")).toBe(false);
    }
  });
});
