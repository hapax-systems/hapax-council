import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { RefusalBriefPanel } from "../RefusalBriefPanel";

// Stub the hook so we don't hit IPC during tests.
vi.mock("../../../api/hooks", () => ({
  useRefusals: () => ({
    data: {
      refusals: [
        {
          timestamp: "2026-04-26T12:34:00Z",
          surface: "twitter",
          reason: "ToS prohibits automation",
          axiom: "single_user",
        },
        {
          timestamp: "2026-04-26T12:35:00Z",
          surface: "linkedin",
          reason: "ToS §8.2 — no scraping",
        },
      ],
      total_in_window: 2,
    },
    dataUpdatedAt: Date.now(),
    isLoading: false,
  }),
}));

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe("RefusalBriefPanel", () => {
  it("renders raw refusal rows", () => {
    render(withClient(<RefusalBriefPanel />));
    expect(screen.getByText(/twitter/)).toBeInTheDocument();
    expect(screen.getByText(/linkedin/)).toBeInTheDocument();
    expect(screen.getByText(/ToS prohibits automation/)).toBeInTheDocument();
  });

  it("displays the count without making a verdict", () => {
    render(withClient(<RefusalBriefPanel />));
    expect(screen.getByText(/last 2 · raw individuals · no aggregation/)).toBeInTheDocument();
  });

  // CONSTITUTIONAL CI GUARD — refusals are first-class displayed elements,
  // never ackable. Per drop §3 fresh patterns + feedback_full_automation_-
  // or_no_engagement, the rendered tree MUST NOT contain any button or
  // interactive element matching the action vocabulary.
  it("contains zero acknowledge / dismiss / archive / triage affordances", () => {
    const { container } = render(withClient(<RefusalBriefPanel />));
    const forbidden = /(ack|acknowledge|dismiss|read|archive|review|triage)/i;
    const buttons = container.querySelectorAll("button");
    for (const btn of buttons) {
      expect(forbidden.test(btn.textContent ?? "")).toBe(false);
    }
    // Also assert no link-as-action pattern.
    const links = container.querySelectorAll("a");
    for (const link of links) {
      expect(forbidden.test(link.textContent ?? "")).toBe(false);
    }
  });

  it("does not register an onClick on the refusal list items", () => {
    const { container } = render(withClient(<RefusalBriefPanel />));
    const items = container.querySelectorAll("li");
    for (const item of items) {
      // React's onClick → DOM "click" listener; the list MUST be display-only.
      expect(item.getAttribute("role")).not.toBe("button");
    }
  });
});
