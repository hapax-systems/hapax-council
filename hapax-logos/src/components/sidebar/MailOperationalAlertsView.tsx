import { useAwareness } from "../../lib/awareness";
import { formatAge } from "../../utils";
import { SidebarSection } from "./SidebarSection";

interface MailAwarenessBlock {
  operational_alerts_total?: unknown;
  operational_alerts?: {
    tls_expiry?: unknown;
    dependabot?: unknown;
    dns?: unknown;
  };
  last_operational_alert_at?: unknown;
  last_operational_alert_kind?: unknown;
}

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

const LABELS: Record<string, string> = {
  tls_expiry: "TLS",
  dependabot: "Dependabot",
  dns: "DNS",
};

export function MailOperationalAlertsView() {
  const { state, stale, lastUpdatedMs } = useAwareness();
  const block = (state?.mail ?? null) as MailAwarenessBlock | null;
  const alerts = block?.operational_alerts ?? {};
  const total = asCount(block?.operational_alerts_total);
  const tls = asCount(alerts.tls_expiry);
  const dependabot = asCount(alerts.dependabot);
  const dns = asCount(alerts.dns);
  const lastKind = asText(block?.last_operational_alert_kind);
  const lastAt = asText(block?.last_operational_alert_at);

  return (
    <SidebarSection
      title="Mail Ops"
      loading={state === null && !stale}
      age={lastUpdatedMs != null ? formatAge(lastUpdatedMs) : undefined}
      severity={total > 0 ? "degraded" : undefined}
    >
      <div className={stale ? "opacity-40" : ""}>
        {block === null ? (
          <div className="text-[11px] text-zinc-600">no awareness state on record</div>
        ) : (
          <div className="space-y-1">
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] text-zinc-500">active 7d</span>
              <span className={total > 0 ? "font-mono text-orange-300" : "font-mono text-zinc-400"}>
                {total}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-1 font-mono text-[10px]">
              <CountPill label="TLS" count={tls} />
              <CountPill label="DEP" count={dependabot} />
              <CountPill label="DNS" count={dns} />
            </div>
            {lastAt ? (
              <div className="truncate text-[10px] text-zinc-600" title={lastAt}>
                last {LABELS[lastKind] ?? lastKind} {shortIso(lastAt)}
              </div>
            ) : (
              <div className="text-[10px] text-zinc-600">no current operational alerts</div>
            )}
          </div>
        )}
      </div>
    </SidebarSection>
  );
}

function CountPill({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between rounded-sm border border-zinc-800/50 px-1 py-0.5">
      <span className="text-zinc-600">{label}</span>
      <span className={count > 0 ? "text-orange-300" : "text-zinc-500"}>{count}</span>
    </div>
  );
}

function shortIso(value: string): string {
  try {
    return new Date(value).toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return value;
  }
}
