"""Typed host-storage registry models.

These models are the source twin of the host-storage identity contract. They
keep device, filesystem, host, network-fabric, and secret-custody facts
host-qualified so labels, mountpoints, kernel names, and prose cannot become
join keys. Host fields describe machine topology only.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from shared.host_provenance import LocalityClass, RecencyClass

SCHEMA_VERSION = 1
HostId = str


class PresenceState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_WITNESSED = "not_witnessed"


class RegistryRecord(BaseModel):
    """Universal fields shared by every typed infrastructure registry row."""

    schema_version: int = SCHEMA_VERSION
    record_version: int = 1
    recency_class: RecencyClass
    locality_class: LocalityClass
    command_host: HostId
    observed_at: datetime
    reconciled_at: datetime | None = None
    reconciled_against_receipt: str | None = None
    next_action: str | None = Field(...)


class HostRecord(RegistryRecord):
    host_id: HostId
    hostname: str
    machine_anchor: str
    tailscale_name: str | None = None
    tailscale_ip: str | None = None
    lan_ip_hint: str | None = None
    ssh_alias: str | None = None
    ssh_reachable_from: list[HostId] = Field(default_factory=list)
    function_class: list[str] = Field(default_factory=list)


class DeviceIdentityRecord(RegistryRecord):
    """Authoritative physical device identity keyed by ``(target_host, serial)``."""

    target_host: HostId
    serial: str
    presence: PresenceState
    model: str | None = None
    by_id: list[str] = Field(default_factory=list)
    kernel_names: list[str] = Field(default_factory=list)
    transport: str | None = None

    @property
    def registry_key(self) -> tuple[HostId, str]:
        return (self.target_host, self.serial)

    @model_validator(mode="after")
    def _serial_required(self) -> DeviceIdentityRecord:
        if not self.serial.strip():
            raise ValueError("device identity requires a serial; kernel names are not keys")
        return self


class DeviceRef(BaseModel):
    """Foreign key to a physical device: never label, mountpoint, or kernel name."""

    target_host: HostId
    serial: str

    @property
    def key(self) -> tuple[HostId, str]:
        return (self.target_host, self.serial)


class FilesystemMountRecord(RegistryRecord):
    """Filesystem/mount authority keyed by ``(target_host, uuid)``."""

    target_host: HostId
    uuid: str
    device_ref: DeviceRef
    device_presence: PresenceState = PresenceState.PRESENT
    fstype: str
    label: str | None = None
    mountpoints: list[str] = Field(default_factory=list)
    partition_kernel_dev: str | None = None
    partuuid: str | None = None

    @property
    def registry_key(self) -> tuple[HostId, str]:
        return (self.target_host, self.uuid)

    @model_validator(mode="after")
    def _device_fk_is_host_scoped_and_present(self) -> FilesystemMountRecord:
        if not self.uuid.strip():
            raise ValueError("(target_host, uuid) is the filesystem primary key")
        if self.device_ref.target_host != self.target_host:
            raise ValueError(
                "mount device_ref target_host must equal mount target_host; "
                "cross-host mount/device joins are invalid"
            )
        if self.device_presence != PresenceState.PRESENT:
            raise ValueError("mount device_ref must point at a present device")
        return self


class NetworkFabricRecord(RegistryRecord):
    """Network-fabric row keyed by stable node identity, not mutable IP."""

    node_id: str
    host_id: HostId | None = None
    mac_address: str | None = None
    tailscale_ip: str | None = None
    lan_ip_hint: str | None = None
    ssh_reachable_from: list[HostId] = Field(default_factory=list)


class SecretCustodyPointerRecord(RegistryRecord):
    """Secret custody pointers only. Values remain in pass/hapax-secrets."""

    secret_id: str
    pass_path: str
    custody_host: HostId | None = None
    consumer_services: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _pointer_only(self) -> SecretCustodyPointerRecord:
        if "\n" in self.pass_path:
            raise ValueError("secret custody pointer must be a pass path, not secret material")
        return self


class BackupPolicyRecord(RegistryRecord):
    store_id: str
    method: str
    cadence: str
    offsite: bool
    target_host: HostId | None = None


class HostStorageRegistry(BaseModel):
    """Typed registry bundle with cross-record invariants."""

    schema_version: int = SCHEMA_VERSION
    hosts: list[HostRecord] = Field(default_factory=list)
    devices: list[DeviceIdentityRecord] = Field(default_factory=list)
    mounts: list[FilesystemMountRecord] = Field(default_factory=list)
    network_nodes: list[NetworkFabricRecord] = Field(default_factory=list)
    secret_pointers: list[SecretCustodyPointerRecord] = Field(default_factory=list)
    backup_policies: list[BackupPolicyRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cross_record_invariants(self) -> HostStorageRegistry:
        device_keys: set[tuple[HostId, str]] = set()
        present_device_keys: set[tuple[HostId, str]] = set()
        for device in self.devices:
            if device.registry_key in device_keys:
                raise ValueError(f"duplicate device registry key {device.registry_key}")
            device_keys.add(device.registry_key)
            if device.presence == PresenceState.PRESENT:
                present_device_keys.add(device.registry_key)

        mount_keys: set[tuple[HostId, str]] = set()
        for mount in self.mounts:
            if mount.registry_key in mount_keys:
                raise ValueError(f"duplicate filesystem registry key {mount.registry_key}")
            mount_keys.add(mount.registry_key)
            if mount.device_ref.key not in present_device_keys:
                raise ValueError(
                    f"mount {mount.registry_key} references non-present device "
                    f"{mount.device_ref.key}"
                )
        return self


# Pydantic calls these validators dynamically; the diff-only unused-function
# hook needs static references without expanding the task into the global
# vulture whitelist.
_PYDANTIC_VALIDATORS = (
    DeviceIdentityRecord._serial_required,
    FilesystemMountRecord._device_fk_is_host_scoped_and_present,
    SecretCustodyPointerRecord._pointer_only,
    HostStorageRegistry._cross_record_invariants,
)

__all__ = [
    "BackupPolicyRecord",
    "DeviceIdentityRecord",
    "DeviceRef",
    "FilesystemMountRecord",
    "HostRecord",
    "HostStorageRegistry",
    "NetworkFabricRecord",
    "PresenceState",
    "RegistryRecord",
    "SecretCustodyPointerRecord",
]
