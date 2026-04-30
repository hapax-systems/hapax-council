import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MailOperationalAlertsView } from "../MailOperationalAlertsView";

type MockMailState = {
  mail: {
    operational_alerts_total: number;
    operational_alerts: {
      tls_expiry: number;
      dependabot: number;
      dns: number;
    };
    last_operational_alert_kind: string | null;
    last_operational_alert_at: string | null;
  };
};

type MockAwarenessResult = {
  state: MockMailState | null;
  stale: boolean;
  lastUpdatedMs: number | null;
};

const awareness = vi.hoisted((): { current: MockAwarenessResult } => ({
  current: {
    state: {
      mail: {
        operational_alerts_total: 3,
        operational_alerts: {
          tls_expiry: 1,
          dependabot: 2,
          dns: 0,
        },
        last_operational_alert_kind: "dependabot",
        last_operational_alert_at: "2026-04-30T12:00:00+00:00",
      },
    },
    stale: false,
    lastUpdatedMs: Date.now(),
  },
}));

vi.mock("../../../lib/awareness", () => ({
  useAwareness: () => awareness.current,
}));

beforeEach(() => {
  awareness.current = {
    state: {
      mail: {
        operational_alerts_total: 3,
        operational_alerts: {
          tls_expiry: 1,
          dependabot: 2,
          dns: 0,
        },
        last_operational_alert_kind: "dependabot",
        last_operational_alert_at: "2026-04-30T12:00:00+00:00",
      },
    },
    stale: false,
    lastUpdatedMs: Date.now(),
  };
});

describe("MailOperationalAlertsView", () => {
  it("renders seven-day operational mail counters", () => {
    render(<MailOperationalAlertsView />);
    expect(screen.getByText("Mail Ops")).toBeInTheDocument();
    expect(screen.getByText("active 7d")).toBeInTheDocument();
    expect(screen.getByText("TLS")).toBeInTheDocument();
    expect(screen.getByText("DEP")).toBeInTheDocument();
    expect(screen.getByText("DNS")).toBeInTheDocument();
    expect(screen.getByText(/last Dependabot/)).toBeInTheDocument();
  });

  it("does not render mail-control affordances", () => {
    const { container } = render(<MailOperationalAlertsView />);
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("renders empty state without message content", () => {
    awareness.current = {
      state: {
        mail: {
          operational_alerts_total: 0,
          operational_alerts: {
            tls_expiry: 0,
            dependabot: 0,
            dns: 0,
          },
          last_operational_alert_kind: null,
          last_operational_alert_at: null,
        },
      },
      stale: false,
      lastUpdatedMs: Date.now(),
    };

    render(<MailOperationalAlertsView />);
    expect(screen.getByText("no current operational alerts")).toBeInTheDocument();
  });
});
