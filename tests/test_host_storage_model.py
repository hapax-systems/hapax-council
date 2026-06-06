from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.host_provenance import LocalityClass, RecencyClass
from shared.host_storage_model import (
    DeviceIdentityRecord,
    DeviceRef,
    FilesystemMountRecord,
    HostRecord,
    HostStorageRegistry,
    NetworkFabricRecord,
    PresenceState,
)
from shared.resource_model import ContentionGroup, ResourceType

PODIUM = "hapax-podium"
APPENDIX = "hapax-appendix"
NOW = datetime(2026, 6, 6, tzinfo=UTC)


def base_fields(host: str = PODIUM) -> dict:
    return {
        "recency_class": RecencyClass.LIVE,
        "locality_class": LocalityClass.SAME_HOST,
        "command_host": host,
        "observed_at": NOW,
        "next_action": None,
    }


def device(
    host: str = APPENDIX,
    serial: str = "24511K802589",
    presence: PresenceState = PresenceState.PRESENT,
) -> DeviceIdentityRecord:
    return DeviceIdentityRecord(
        **base_fields(PODIUM),
        target_host=host,
        serial=serial,
        presence=presence,
        model="WD_BLACK SN7100 1TB",
        by_id=[f"nvme-WD_BLACK_SN7100_1TB_{serial}"],
    )


def mount(host: str = APPENDIX, serial: str = "24511K802589") -> FilesystemMountRecord:
    return FilesystemMountRecord(
        **base_fields(PODIUM),
        target_host=host,
        uuid="1e70ec1f-00db-4734-8885-3ecbdfa400e5",
        device_ref=DeviceRef(target_host=host, serial=serial),
        fstype="xfs",
        label="store",
        mountpoints=["/store"],
        partition_kernel_dev="/dev/nvme1n1p1",
    )


def test_filesystem_key_is_host_uuid_not_label_mountpoint_or_kernel_name():
    fs = mount()

    assert fs.registry_key == (APPENDIX, "1e70ec1f-00db-4734-8885-3ecbdfa400e5")
    assert fs.label == "store"
    assert fs.mountpoints == ["/store"]
    assert fs.partition_kernel_dev == "/dev/nvme1n1p1"


def test_cross_host_mount_device_reference_rejected():
    with pytest.raises(ValidationError, match="cross-host"):
        FilesystemMountRecord(
            **base_fields(PODIUM),
            target_host=APPENDIX,
            uuid="1e70ec1f-00db-4734-8885-3ecbdfa400e5",
            device_ref=DeviceRef(target_host=PODIUM, serial="24511K802589"),
            fstype="xfs",
        )


def test_registry_rejects_mount_referencing_absent_device():
    with pytest.raises(ValidationError, match="non-present device"):
        HostStorageRegistry(
            devices=[device(presence=PresenceState.ABSENT)],
            mounts=[mount()],
        )


def test_registry_accepts_mount_referencing_present_same_host_device():
    registry = HostStorageRegistry(devices=[device()], mounts=[mount()])

    assert registry.mounts[0].device_ref.key == registry.devices[0].registry_key


def test_missing_next_action_rejected_on_every_record_type():
    with pytest.raises(ValidationError):
        HostRecord(
            recency_class=RecencyClass.LIVE,
            locality_class=LocalityClass.SAME_HOST,
            command_host=PODIUM,
            observed_at=NOW,
            host_id=PODIUM,
            hostname=PODIUM,
            machine_anchor="S6WSNS0W406658B",
        )


def test_network_fabric_uses_ssh_reachable_from_not_capability_language():
    row = NetworkFabricRecord(
        **base_fields(PODIUM),
        node_id="hapax-appendix",
        host_id=APPENDIX,
        tailscale_ip="100.85.131.41",
        lan_ip_hint="192.168.68.50",
        ssh_reachable_from=[PODIUM],
    )

    assert row.ssh_reachable_from == [PODIUM]
    assert "is_command_host_capable" not in NetworkFabricRecord.model_fields


def test_axiom_clean_fields_have_no_principal_or_permission_semantics():
    forbidden = {"user", "principal", "permission", "account", "auth"}
    for model in (
        HostRecord,
        DeviceIdentityRecord,
        FilesystemMountRecord,
        NetworkFabricRecord,
    ):
        field_names = set(model.model_fields)
        assert field_names.isdisjoint(forbidden)


def test_gpu_contention_group_known_host_capacity_mismatch_rejected():
    with pytest.raises(ValidationError, match="host GPU set"):
        ContentionGroup(
            name="CG-GPU0",
            host_id=PODIUM,
            resource_type=ResourceType.GPU_VRAM,
            total_capacity=24576.0,
            unit="MiB",
            members=["tabbyapi"],
            headroom_min=2048.0,
            notes="stale RTX 3090 assumption",
        )
