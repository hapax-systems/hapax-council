import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { HostStorageSnapshot, SopGateSnapshot } from "../../../api/types";
import { HostStoragePanel, buildStorageMatrix, isBlockedBackupRole } from "../HostStoragePanel";

const storageSnapshot: HostStorageSnapshot = {
  schema_version: 1,
  generated_at: "2026-06-06T12:00:00Z",
  hosts: [
    {
      host_id: "hapax-appendix",
      evidence_host: "hapax-appendix",
      evidence_machine_id: "machine-appendix",
      evidence_class: "recent",
      observed_at: "2026-06-06T12:00:00Z",
      recency_class: "live",
      locality_class: "cross_host_ssh",
      transport: "ssh",
      anchor_verified: true,
      root_disk_serial: "root-appendix",
      warnings: [],
    },
    {
      host_id: "hapax-podium",
      evidence_host: "hapax-podium",
      evidence_machine_id: "machine-podium",
      evidence_class: "recent",
      observed_at: "2026-06-06T12:00:01Z",
      recency_class: "live",
      locality_class: "local",
      transport: "local",
      anchor_verified: true,
      root_disk_serial: "root-podium",
      warnings: [],
    },
  ],
  devices: [
    {
      target_host: "hapax-appendix",
      serial: "SN7100",
      presence: "present",
      model: "WD_BLACK SN7100 1TB",
      kernel_dev: "/dev/nvme1n1",
      size: "931.5G",
      transport: "nvme",
      by_id: ["nvme-WD_BLACK_SN7100_1TB_SN7100"],
      filesystems: [
        {
          target_host: "hapax-appendix",
          device_serial: "SN7100",
          uuid: "fs-uuid",
          fstype: "xfs",
          label: "store",
          mountpoints: ["/store"],
          partition_kernel_dev: "/dev/nvme1n1p1",
          partuuid: "part-uuid",
        },
      ],
    },
  ],
  filesystems: [],
  data_roles: [
    {
      store_id: "b2-restic-offsite",
      surface: "Backblaze restic offsite backup",
      authority_class: "backup",
      retrieval_mode: "restic",
      current_placement: "Backblaze B2",
      target_placement: "retired offsite",
      data_authority_host: null,
      expected_host: "hapax-standby",
      container_running_host: null,
      actual_host_witness: null,
      placement_state: "unknown",
      quality_gate: "ROLE RETIRED 2026-06-06: GDrive is canonical; B2 blocked",
    },
  ],
};

const sopGate: SopGateSnapshot = {
  schema_version: 1,
  generated_at: "2026-06-06T12:00:00Z",
  task_id: "appendix-podium-sop-baseline-proof-20260604",
  title: "SOP baseline proof",
  status: "blocked",
  stage: "S6_IMPLEMENTATION",
  blocked_reason: "waiting_for_closure_valid_dependencies",
  blocked_witness: null,
  dependency_count: 37,
  closed_count: 31,
  blocked_count: 2,
  open_count: 4,
  missing_count: 0,
  non_fulfilling_count: 0,
  normal_dev_ready: false,
  dependencies: [],
};

vi.mock("../../../api/hooks", () => ({
  useHostStorage: () => ({
    data: storageSnapshot,
    dataUpdatedAt: Date.now(),
    isLoading: false,
  }),
  useSopGate: () => ({
    data: sopGate,
    dataUpdatedAt: Date.now(),
    isLoading: false,
  }),
}));

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe("HostStoragePanel", () => {
  it("builds distinct present, absent-on, and not-observed states", () => {
    const row = buildStorageMatrix(storageSnapshot)[0];

    expect(row.cells.map((cell) => [cell.hostId, cell.state])).toEqual([
      ["hapax-podium", "absent_on"],
      ["hapax-appendix", "present"],
      ["hapax-standby", "not_observed"],
    ]);
  });

  it("renders three-state host cells and full citation details", async () => {
    render(withClient(<HostStoragePanel />));

    expect(screen.getByTestId("storage-cell-SN7100-hapax-appendix")).toHaveTextContent("PRESENT");
    expect(screen.getByTestId("storage-cell-SN7100-hapax-podium")).toHaveTextContent("ABSENT_ON");
    expect(screen.getByTestId("storage-cell-SN7100-hapax-standby")).toHaveTextContent("NOT OBS");

    await userEvent.click(screen.getByRole("button", { name: /SN7100/ }));

    expect(screen.getByText("§6.4 citation")).toBeInTheDocument();
    expect(screen.getByText(/present: evidence_host=hapax-appendix/)).toBeInTheDocument();
    expect(screen.getByText(/absent_on: evidence_host=hapax-podium/)).toBeInTheDocument();
    expect(screen.getByText(/not observed: no live receipt for hapax-standby/)).toBeInTheDocument();
  });

  it("renders blocked Backblaze B2 freshness in the red severity lane", () => {
    render(withClient(<HostStoragePanel />));

    const role = storageSnapshot.data_roles[0];
    expect(isBlockedBackupRole(role)).toBe(true);
    expect(screen.getByTestId("backup-role-b2-restic-offsite")).toHaveClass("text-red-400");
    expect(screen.getByText(/31\/37/)).toBeInTheDocument();
  });
});
