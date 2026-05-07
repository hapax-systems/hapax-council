import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FreshnessPanel } from "../FreshnessPanel";

vi.mock("../../../api/hooks", () => ({
  useReadiness: () => ({
    data: {
      level: "developing",
      interview_conducted: true,
      interview_fact_count: 12,
      priorities_known: false,
      neurocognitive_mapped: true,
      profile_coverage_pct: 72.4,
      total_facts: 144,
      populated_dimensions: 8,
      total_dimensions: 11,
      missing_dimensions: ["identity", "workflow"],
      sparse_dimensions: ["management"],
      top_gap: "priorities not validated",
      gaps: ["priorities not validated", "2 profile dimensions missing (identity, workflow)"],
    },
    dataUpdatedAt: Date.now(),
    isLoading: false,
  }),
}));

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe("FreshnessPanel", () => {
  it("surfaces the readiness gate signals read-only", () => {
    render(withClient(<FreshnessPanel />));

    expect(screen.getByText(/developing/)).toBeInTheDocument();
    expect(screen.getByText(/8\/11 dimensions · 144 facts/)).toBeInTheDocument();
    expect(screen.getByText(/Interview conducted · 12 interview facts/)).toBeInTheDocument();
    expect(screen.getByText(/Priorities not validated · Neurocognitive mapped/)).toBeInTheDocument();
    expect(screen.getByText(/Gap: priorities not validated/)).toBeInTheDocument();
  });
});
