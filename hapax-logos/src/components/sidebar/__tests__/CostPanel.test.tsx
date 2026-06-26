import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CostSnapshot } from "../../../api/types";
import { CostPanel } from "../CostPanel";

type UseCostMock = {
  data: CostSnapshot | null;
  dataUpdatedAt: number;
};

const { costResult } = vi.hoisted(() => ({
  costResult: {
    data: null,
    dataUpdatedAt: 0,
  } as UseCostMock,
}));

vi.mock("../../../api/hooks", () => ({
  useCost: () => costResult,
}));

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe("CostPanel", () => {
  it("renders local capacity when dollar cost is unavailable", () => {
    costResult.data = {
      today_cost: 0,
      period_cost: 0,
      daily_average: 0,
      top_models: [],
      available: false,
      local_capacity: {
        pressure: 0.82,
        inflight: 8,
        ceiling: 10,
        ttft_ratio: 1.4,
        age_s: 2,
        alert_active: true,
        available: true,
      },
    };
    costResult.dataUpdatedAt = Date.now();

    render(withClient(<CostPanel />));

    expect(screen.getByText("Local capacity (non-$)")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText("8/10 inflight")).toBeInTheDocument();
    expect(screen.getByText("1.40x TTFT")).toBeInTheDocument();
  });
});
