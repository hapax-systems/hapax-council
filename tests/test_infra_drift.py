from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.host_provenance import LocalityClass, RecencyClass
from shared.host_storage_model import (
    BackupIntendedState,
    BackupObservedState,
    BackupPolicyRecord,
    DeviceIdentityRecord,
    DeviceRef,
    FilesystemMountRecord,
    HostStorageRegistry,
    PresenceState,
)
from shared.infra_drift import (
    BACKUP_STATE_DRIFT_CODE,
    DRIFT_CODE,
    SCHEMA_SKEW_CODE,
    DriftStatus,
    evaluate_infra_drift,
)

HOST = "hapax-appendix"
NOW = datetime(2026, 6, 6, tzinfo=UTC)


def base_fields() -> dict:
    return {
        "recency_class": RecencyClass.LIVE,
        "locality_class": LocalityClass.SAME_HOST,
        "command_host": HOST,
        "observed_at": NOW,
        "next_action": None,
    }


def device(serial: str, by_id: list[str] | None = None) -> DeviceIdentityRecord:
    return DeviceIdentityRecord(
        **base_fields(),
        target_host=HOST,
        serial=serial,
        presence=PresenceState.PRESENT,
        model="WD_BLACK SN7100 1TB",
        by_id=by_id or [f"nvme-WD_BLACK_SN7100_1TB_{serial}"],
        transport="nvme",
    )


def mount(uuid: str = "fs-a", serial: str = "serial-a") -> FilesystemMountRecord:
    return FilesystemMountRecord(
        **base_fields(),
        target_host=HOST,
        uuid=uuid,
        device_ref=DeviceRef(target_host=HOST, serial=serial),
        fstype="xfs",
        label="store",
        mountpoints=["/store"],
        partition_kernel_dev="/dev/nvme0n1p1",
        partuuid="part-a",
    )


def receipt(
    devices: list[dict],
    *,
    schema_version: int = 1,
    observed_at: str = "2026-06-06T11:00:00Z",
) -> dict:
    return {
        "schema_version": schema_version,
        "host_provenance": {
            "intent_host": HOST,
            "exec_host": HOST,
            "evidence_host": HOST,
            "transport": "local",
        },
        "hostname": HOST,
        "observed_at": observed_at,
        "evidence_class": "live",
        "recency_class": "live",
        "locality_class": "same_host",
        "collectors": {"lsblk": {"ran": True, "exit_code": 0, "row_count": len(devices)}},
        "devices": devices,
    }


def receipt_device(
    serial: str,
    *,
    by_id: list[str] | None = None,
    filesystems: list[dict] | None = None,
) -> dict:
    return {
        "presence": "present",
        "model": "WD_BLACK SN7100 1TB",
        "serial": serial,
        "kernel_dev": "/dev/nvme0n1",
        "tran": "nvme",
        "by_id": by_id or [f"nvme-WD_BLACK_SN7100_1TB_{serial}"],
        "filesystems": filesystems or [],
    }


def receipt_fs(uuid: str = "fs-a", serial: str = "serial-a") -> dict:
    return {
        "uuid": uuid,
        "fstype": "xfs",
        "label": "store",
        "mountpoints": ["/store"],
        "partition_kernel_dev": "/dev/nvme0n1p1",
        "partuuid": "part-a",
        "serial": serial,
    }


def find_entry(report, *, status: DriftStatus, key: str, field: str | None = None):
    for entry in report.entries:
        if entry.status == status and entry.key == key and entry.field == field:
            return entry
    raise AssertionError(f"entry not found: {status=} {key=} {field=}")


def test_added_removed_and_changed_field_detection():
    registry = HostStorageRegistry(
        devices=[
            device("serial-a", by_id=["nvme-WD_BLACK_SN7100_1TB_serial-a"]),
            device("serial-registry-only"),
        ],
        mounts=[mount()],
    )
    live = receipt(
        [
            receipt_device(
                "serial-a",
                by_id=["nvme-WD_BLACK_SN7100_1TB_serial-a-new"],
                filesystems=[receipt_fs()],
            ),
            receipt_device("serial-receipt-only"),
        ]
    )

    report = evaluate_infra_drift(registry, [live])

    changed = find_entry(
        report,
        status=DriftStatus.DRIFTED,
        key=f"{HOST}:serial-a",
        field="device.by_id",
    )
    assert changed.code == DRIFT_CODE
    assert changed.invalidates_destructive_preflight is True
    assert find_entry(
        report,
        status=DriftStatus.REGISTRY_ONLY,
        key=f"{HOST}:serial-registry-only",
    )
    assert find_entry(
        report,
        status=DriftStatus.RECEIPT_ONLY,
        key=f"{HOST}:serial-receipt-only",
    )


def test_schema_version_skew_emits_dedicated_code():
    registry = HostStorageRegistry()
    report = evaluate_infra_drift(registry, [receipt([], schema_version=99)])

    entry = find_entry(
        report,
        status=DriftStatus.DRIFTED,
        key=f"{HOST}:schema_version",
        field="schema_version",
    )
    assert entry.code == SCHEMA_SKEW_CODE
    assert entry.registry_value == 1
    assert entry.receipt_value == 99


def test_absent_registry_row_matches_live_absence():
    registry = HostStorageRegistry(
        devices=[
            DeviceIdentityRecord(
                **base_fields(),
                target_host=HOST,
                serial="absent-serial",
                presence=PresenceState.ABSENT,
                model="removed drive",
            )
        ]
    )

    report = evaluate_infra_drift(registry, [receipt([])])

    entry = find_entry(
        report,
        status=DriftStatus.IN_SYNC,
        key=f"{HOST}:absent-serial",
        field="device.presence",
    )
    assert entry.receipt_value == "absent"


def test_mount_partuuid_drift_invalidates_destructive_preflight_freshness():
    registry = HostStorageRegistry(devices=[device("serial-a")], mounts=[mount()])
    live_fs = receipt_fs()
    live_fs["partuuid"] = "part-new"
    live = receipt([receipt_device("serial-a", filesystems=[live_fs])])

    report = evaluate_infra_drift(registry, [live])

    entry = find_entry(
        report,
        status=DriftStatus.DRIFTED,
        key=f"{HOST}:fs-a",
        field="filesystem.partuuid",
    )
    assert entry.invalidates_destructive_preflight is True


def test_backup_intended_state_vs_systemctl_observed_state_drift():
    policy = BackupPolicyRecord(
        **base_fields(),
        store_id="gdrive-critical",
        method="restic",
        cadence="daily",
        offsite=True,
        target_host=HOST,
        unit_name="hapax-backup-gdrive-critical.timer",
        intended_state=BackupIntendedState.ENABLED,
    )
    registry = HostStorageRegistry(backup_policies=[policy])
    observed = {
        "gdrive-critical": BackupObservedState(
            load_state="loaded",
            active_state="inactive",
            witnessed_at=NOW,
        )
    }

    report = evaluate_infra_drift(registry, [], observed)

    entry = find_entry(
        report,
        status=DriftStatus.DRIFTED,
        key="gdrive-critical",
        field="backup.intended_state",
    )
    assert entry.code == BACKUP_STATE_DRIFT_CODE
    assert entry.registry_value == "enabled"
    assert entry.observed_value["active_state"] == "inactive"


def test_backup_policy_intent_is_required():
    with pytest.raises(ValidationError, match="intended_state"):
        BackupPolicyRecord(
            **base_fields(),
            store_id="missing-intent",
            method="restic",
            cadence="daily",
            offsite=True,
            target_host=HOST,
        )


def test_retired_backup_active_is_drifted():
    policy = BackupPolicyRecord(
        **base_fields(),
        store_id="b2-remote",
        method="restic",
        cadence="daily",
        offsite=True,
        target_host=HOST,
        unit_name="hapax-backup-remote.timer",
        intended_state=BackupIntendedState.RETIRED,
    )
    registry = HostStorageRegistry(backup_policies=[policy])
    observed = {
        "b2-remote": BackupObservedState(
            load_state="loaded",
            active_state="active",
            witnessed_at=NOW,
        )
    }

    report = evaluate_infra_drift(registry, [], observed)

    assert find_entry(
        report,
        status=DriftStatus.DRIFTED,
        key="b2-remote",
        field="backup.intended_state",
    )
