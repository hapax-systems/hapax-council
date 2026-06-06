import { ChevronDown, ChevronRight, Database, HardDrive } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  HostStorageDevice,
  HostStorageHost,
  HostStorageSnapshot,
  SopGateSnapshot,
  StorageDataRole,
} from "../../api/types";
import { useHostStorage, useSopGate } from "../../api/hooks";
import { formatAge } from "../../utils";
import { SidebarSection } from "./SidebarSection";

const CANONICAL_HOSTS = ["hapax-podium", "hapax-appendix"];

type StorageCellState = "present" | "absent_on" | "not_observed";

interface StorageCell {
  hostId: string;
  state: StorageCellState;
  host: HostStorageHost | null;
  device: HostStorageDevice | null;
  citation: string;
}

interface StorageMatrixRow {
  serial: string;
  label: string;
  cells: StorageCell[];
}

const cellTone: Record<StorageCellState, string> = {
  present: "border-green-500/30 bg-green-500/5 text-green-400",
  absent_on: "border-yellow-500/30 bg-yellow-500/5 text-yellow-400",
  not_observed: "border-zinc-700/60 bg-zinc-800/20 text-zinc-500",
};

const stateLabel: Record<StorageCellState, string> = {
  present: "PRESENT",
  absent_on: "ABSENT_ON",
  not_observed: "NOT OBS",
};

export function hostStorageColumns(snapshot: HostStorageSnapshot | null | undefined): string[] {
  const hosts = new Set<string>(CANONICAL_HOSTS);
  for (const host of snapshot?.hosts ?? []) hosts.add(host.host_id);
  for (const role of snapshot?.data_roles ?? []) {
    if (role.data_authority_host) hosts.add(role.data_authority_host);
    if (role.expected_host) hosts.add(role.expected_host);
    if (role.container_running_host) hosts.add(role.container_running_host);
  }
  return [...hosts].sort((a, b) => hostSortKey(a).localeCompare(hostSortKey(b)));
}

export function buildStorageMatrix(
  snapshot: HostStorageSnapshot | null | undefined,
): StorageMatrixRow[] {
  if (!snapshot) return [];
  const columns = hostStorageColumns(snapshot);
  const hostsById = new Map(snapshot.hosts.map((host) => [host.host_id, host]));
  const devicesByHostSerial = new Map<string, HostStorageDevice>();
  const serials = new Set<string>();

  for (const device of snapshot.devices ?? []) {
    if (!device.serial) continue;
    serials.add(device.serial);
    devicesByHostSerial.set(`${device.target_host}::${device.serial}`, device);
  }

  return [...serials].sort().map((serial) => {
    const firstDevice = snapshot.devices.find((device) => device.serial === serial) ?? null;
    const cells = columns.map((hostId) => {
      const host = hostsById.get(hostId) ?? null;
      const device = devicesByHostSerial.get(`${hostId}::${serial}`) ?? null;
      const state: StorageCellState = device ? "present" : host ? "absent_on" : "not_observed";
      return {
        hostId,
        state,
        host,
        device,
        citation: cellCitation(serial, hostId, host, device, state),
      };
    });
    return {
      serial,
      label: firstDevice?.model ?? serial,
      cells,
    };
  });
}

export function isBlockedBackupRole(role: StorageDataRole): boolean {
  const haystack = [
    role.store_id,
    role.surface,
    role.current_placement,
    role.target_placement,
    role.quality_gate,
  ]
    .join(" ")
    .toLowerCase();
  const backblazeRole = haystack.includes("backblaze") || /\bb2\b/.test(haystack);
  const blockedState =
    haystack.includes("blocked") ||
    haystack.includes("retired") ||
    haystack.includes("disabled") ||
    haystack.includes("capacity");
  return backblazeRole && blockedState;
}

export function HostStoragePanel() {
  const { data: storage, dataUpdatedAt: storageUpdatedAt } = useHostStorage();
  const { data: sopGate } = useSopGate();
  const [expandedSerial, setExpandedSerial] = useState<string | null>(null);
  const rows = useMemo(() => buildStorageMatrix(storage), [storage]);
  const hosts = useMemo(() => hostStorageColumns(storage), [storage]);
  const blockedBackupRoles = useMemo(
    () => (storage?.data_roles ?? []).filter(isBlockedBackupRole),
    [storage],
  );
  const severity = blockedBackupRoles.length > 0 || (sopGate?.blocked_count ?? 0) > 0 ? "critical" : undefined;

  if (!storage) return <SidebarSection title="Storage Identity" loading>{null}</SidebarSection>;

  return (
    <SidebarSection
      title="Storage Identity"
      age={formatAge(storageUpdatedAt)}
      severity={severity}
    >
      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2 text-[11px]">
          <span className="text-zinc-500">
            {rows.length} serials / {hosts.length} hosts
          </span>
          <span className="text-zinc-600">{storage.generated_at}</span>
        </div>

        <div className="overflow-x-auto">
          <div
            className="grid min-w-max gap-1 text-[10px]"
            style={{ gridTemplateColumns: `minmax(9rem, 1fr) repeat(${hosts.length}, minmax(5.5rem, 1fr))` }}
          >
            <div className="text-zinc-600">serial</div>
            {hosts.map((host) => (
              <div key={host} className="truncate text-zinc-600" title={host}>
                {shortHost(host)}
              </div>
            ))}
            {rows.slice(0, 5).map((row) => (
              <StorageMatrixCells
                key={row.serial}
                row={row}
                expanded={expandedSerial === row.serial}
                onToggle={() =>
                  setExpandedSerial(expandedSerial === row.serial ? null : row.serial)
                }
              />
            ))}
          </div>
        </div>

        {expandedSerial && (
          <CitationBlock row={rows.find((row) => row.serial === expandedSerial) ?? null} />
        )}

        <BackupFreshness roles={blockedBackupRoles} />
        {sopGate && <SopGateBoard snapshot={sopGate} />}
      </div>
    </SidebarSection>
  );
}

function StorageMatrixCells({
  row,
  expanded,
  onToggle,
}: {
  row: StorageMatrixRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <button
        type="button"
        onClick={onToggle}
        className="flex min-w-0 items-center gap-1 text-left text-zinc-400 hover:text-zinc-200"
        title={row.label}
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <HardDrive className="h-3 w-3 text-zinc-500" />
        <span className="truncate">{row.serial}</span>
      </button>
      {row.cells.map((cell) => (
        <div
          key={`${row.serial}-${cell.hostId}`}
          data-testid={cellTestId(row.serial, cell.hostId)}
          className={`rounded-sm border px-1 py-0.5 text-center font-semibold ${cellTone[cell.state]}`}
          title={cell.citation}
        >
          {stateLabel[cell.state]}
        </div>
      ))}
    </>
  );
}

function CitationBlock({ row }: { row: StorageMatrixRow | null }) {
  if (!row) return null;
  return (
    <div className="rounded-sm border border-zinc-800 bg-zinc-900/40 p-1.5 text-[10px] text-zinc-500">
      <div className="mb-1 flex items-center gap-1 text-zinc-400">
        <Database className="h-3 w-3" />
        <span className="font-semibold">§6.4 citation</span>
      </div>
      <div className="space-y-0.5">
        {row.cells.map((cell) => (
          <p key={cell.hostId}>
            <span className="text-zinc-400">{shortHost(cell.hostId)}</span>: {cell.citation}
          </p>
        ))}
      </div>
    </div>
  );
}

function BackupFreshness({ roles }: { roles: StorageDataRole[] }) {
  if (roles.length === 0) {
    return (
      <div className="rounded-sm border border-green-500/20 px-1.5 py-1 text-[10px] text-green-400">
        Backups: no blocked B2 role
      </div>
    );
  }
  return (
    <div className="space-y-1">
      {roles.map((role) => (
        <div
          key={role.store_id}
          data-testid={`backup-role-${role.store_id}`}
          className="rounded-sm border border-red-500/30 bg-red-500/5 px-1.5 py-1 text-[10px] text-red-400"
        >
          <div className="font-semibold uppercase tracking-wider">{role.store_id}</div>
          <div className="text-red-300">{role.quality_gate || role.placement_state}</div>
        </div>
      ))}
    </div>
  );
}

function SopGateBoard({ snapshot }: { snapshot: SopGateSnapshot }) {
  const waiting =
    snapshot.blocked_count +
    snapshot.open_count +
    snapshot.missing_count +
    snapshot.non_fulfilling_count;
  const tone =
    snapshot.normal_dev_ready || waiting === 0
      ? "border-green-500/20 text-green-400"
      : "border-yellow-500/20 text-yellow-400";
  return (
    <div className={`rounded-sm border px-1.5 py-1 text-[10px] ${tone}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold uppercase tracking-wider">SOP gate</span>
        <span>
          {snapshot.closed_count}/{snapshot.dependency_count}
        </span>
      </div>
      <div className="mt-0.5 text-zinc-500">
        {snapshot.blocked_count} blocked / {snapshot.open_count} open / {snapshot.missing_count} missing
      </div>
    </div>
  );
}

function cellCitation(
  serial: string,
  hostId: string,
  host: HostStorageHost | null,
  device: HostStorageDevice | null,
  state: StorageCellState,
): string {
  if (!host) return `not observed: no live receipt for ${hostId}; ${serial} not claimed absent`;
  const witness = [
    `evidence_host=${host.evidence_host ?? host.host_id}`,
    `observed_at=${host.observed_at}`,
    `anchor_verified=${String(host.anchor_verified)}`,
    `root_serial=${host.root_disk_serial ?? "unknown"}`,
  ].join("; ");
  if (state === "present" && device) {
    const fs = device.filesystems[0];
    const mount = fs?.mountpoints?.join(",") || "unmounted";
    return `present: ${witness}; device=${device.kernel_dev ?? "unknown"}; fs=${fs?.fstype ?? "unknown"}:${mount}`;
  }
  return `absent_on: ${witness}; serial=${serial} absent from witnessed device set`;
}

function hostSortKey(host: string): string {
  const canonicalIndex = CANONICAL_HOSTS.indexOf(host);
  return canonicalIndex >= 0 ? `${canonicalIndex}-${host}` : `9-${host}`;
}

function shortHost(host: string): string {
  return host.replace(/^hapax-/, "");
}

function cellTestId(serial: string, hostId: string): string {
  return `storage-cell-${serial.replace(/[^a-zA-Z0-9_-]/g, "_")}-${hostId}`;
}
