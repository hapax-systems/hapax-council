"""Host-qualified storage data for Logos API routes.

This collector is read-only. It projects the machine-rooted host-storage
receipts into API cache objects and keeps service/storage placement claims
explicit about which host supplied the witness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from logos.data.infrastructure import INFRA_SNAPSHOT
from shared.host_storage_inventory import CACHE_DIR

DATA_ROLE_REGISTRY = (
    Path.home()
    / "Documents"
    / "Personal"
    / "30-areas"
    / "hapax"
    / "data-role-registry-2026-06-05.md"
)
SCHEMA_VERSION = 1
MAX_WITNESS_AGE_S = 300


@dataclass
class ActualHostWitness:
    source: str
    evidence_host: str | None
    evidence_machine_id: str | None
    observed_at: str | None
    witness_age_s: int | None
    max_witness_age_s: int = MAX_WITNESS_AGE_S


@dataclass
class HostStorageHost:
    host_id: str
    evidence_host: str | None
    evidence_machine_id: str | None
    evidence_class: str
    observed_at: str
    recency_class: str
    locality_class: str
    transport: str | None
    anchor_verified: bool
    root_disk_serial: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class HostStorageFilesystem:
    target_host: str
    device_serial: str | None
    uuid: str | None
    fstype: str | None
    label: str | None
    mountpoints: list[str]
    partition_kernel_dev: str | None
    partuuid: str | None


@dataclass
class HostStorageDevice:
    target_host: str
    serial: str | None
    presence: str
    model: str | None
    kernel_dev: str | None
    size: str | None
    transport: str | None
    by_id: list[str]
    filesystems: list[HostStorageFilesystem] = field(default_factory=list)


@dataclass
class StorageDataRole:
    store_id: str
    surface: str
    authority_class: str
    retrieval_mode: str
    current_placement: str
    target_placement: str
    data_authority_host: str | None
    expected_host: str | None
    container_running_host: str | None
    actual_host_witness: ActualHostWitness | None
    placement_state: str
    quality_gate: str


@dataclass
class HostStorageSnapshot:
    schema_version: int
    generated_at: str
    hosts: list[HostStorageHost] = field(default_factory=list)
    devices: list[HostStorageDevice] = field(default_factory=list)
    filesystems: list[HostStorageFilesystem] = field(default_factory=list)
    data_roles: list[StorageDataRole] = field(default_factory=list)


def collect_hosts() -> list[HostStorageHost]:
    """Collect host witness rows from latest host-storage receipts."""
    return collect_host_storage().hosts


def collect_host_storage() -> HostStorageSnapshot:
    """Project latest host-storage receipts and data-role rows into API data."""
    receipts = _latest_receipts()
    hosts: list[HostStorageHost] = []
    devices: list[HostStorageDevice] = []
    filesystems: list[HostStorageFilesystem] = []

    for receipt in receipts:
        host = _receipt_host(receipt)
        if not host:
            continue
        host_row = _host_row(receipt, host)
        hosts.append(host_row)
        for raw_device in receipt.get("devices", []):
            device_filesystems = [
                _filesystem_row(host, raw_device, raw_fs)
                for raw_fs in raw_device.get("filesystems", [])
            ]
            filesystems.extend(device_filesystems)
            devices.append(_device_row(host, raw_device, device_filesystems))

    infra_snapshot = _load_infra_snapshot()
    witness = _infra_witness(infra_snapshot)
    data_roles = _data_roles(witness, infra_snapshot)
    return HostStorageSnapshot(
        schema_version=SCHEMA_VERSION,
        generated_at=_now_iso(),
        hosts=sorted(hosts, key=lambda h: h.host_id),
        devices=sorted(devices, key=lambda d: (d.target_host, d.serial or "")),
        filesystems=sorted(filesystems, key=lambda f: (f.target_host, f.uuid or "")),
        data_roles=data_roles,
    )


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _latest_receipts(cache_dir: Path | None = None) -> list[dict[str, Any]]:
    cache_dir = cache_dir or CACHE_DIR
    receipts: dict[str, dict[str, Any]] = {}
    for path in sorted(cache_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        host = _receipt_host(receipt)
        if not host:
            continue
        current = receipts.get(host)
        if current is None or str(receipt.get("observed_at", "")) > str(
            current.get("observed_at", "")
        ):
            receipts[host] = receipt
    return list(receipts.values())


def _receipt_host(receipt: dict[str, Any]) -> str | None:
    provenance = receipt.get("host_provenance") or {}
    return provenance.get("intent_host") or receipt.get("hostname")


def _host_row(receipt: dict[str, Any], host: str) -> HostStorageHost:
    witness = receipt.get("evidence_witness") or {}
    provenance = receipt.get("host_provenance") or {}
    return HostStorageHost(
        host_id=host,
        evidence_host=provenance.get("evidence_host") or receipt.get("hostname"),
        evidence_machine_id=witness.get("machine_id"),
        evidence_class=str(receipt.get("evidence_class") or "unknown"),
        observed_at=str(receipt.get("observed_at") or ""),
        recency_class=str(receipt.get("recency_class") or "unknown"),
        locality_class=str(receipt.get("locality_class") or "unknown"),
        transport=provenance.get("transport"),
        anchor_verified=bool(witness.get("anchor_verified")),
        root_disk_serial=witness.get("root_disk_serial"),
        warnings=[str(w) for w in receipt.get("warnings", [])],
    )


def _device_row(
    host: str,
    raw_device: dict[str, Any],
    filesystems: list[HostStorageFilesystem],
) -> HostStorageDevice:
    return HostStorageDevice(
        target_host=host,
        serial=raw_device.get("serial"),
        presence=str(raw_device.get("presence") or "not_witnessed"),
        model=raw_device.get("model"),
        kernel_dev=raw_device.get("kernel_dev"),
        size=raw_device.get("size"),
        transport=raw_device.get("tran"),
        by_id=[str(v) for v in raw_device.get("by_id", [])],
        filesystems=filesystems,
    )


def _filesystem_row(
    host: str,
    raw_device: dict[str, Any],
    raw_fs: dict[str, Any],
) -> HostStorageFilesystem:
    return HostStorageFilesystem(
        target_host=host,
        device_serial=raw_device.get("serial"),
        uuid=raw_fs.get("uuid"),
        fstype=raw_fs.get("fstype"),
        label=raw_fs.get("label"),
        mountpoints=[str(v) for v in raw_fs.get("mountpoints", [])],
        partition_kernel_dev=raw_fs.get("partition_kernel_dev"),
        partuuid=raw_fs.get("partuuid"),
    )


def _load_infra_snapshot() -> dict[str, Any]:
    try:
        data = json.loads(INFRA_SNAPSHOT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _infra_witness(snapshot: dict[str, Any]) -> ActualHostWitness | None:
    if not snapshot:
        return None
    observed_at = _snapshot_observed_at(snapshot)
    return ActualHostWitness(
        source="logos_infra",
        evidence_host=_snapshot_host(snapshot),
        evidence_machine_id=_snapshot_machine_id(snapshot),
        observed_at=observed_at,
        witness_age_s=_age_s(observed_at),
    )


def _snapshot_observed_at(snapshot: dict[str, Any]) -> str | None:
    value = snapshot.get("observed_at") or snapshot.get("timestamp") or snapshot.get("updated_at")
    if isinstance(value, str) and value:
        return value
    try:
        return datetime.fromtimestamp(INFRA_SNAPSHOT.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return None


def _snapshot_host(snapshot: dict[str, Any]) -> str | None:
    value = snapshot.get("evidence_host") or snapshot.get("hostname") or snapshot.get("host")
    return str(value) if value else None


def _snapshot_machine_id(snapshot: dict[str, Any]) -> str | None:
    value = snapshot.get("evidence_machine_id") or snapshot.get("machine_id")
    return str(value) if value else None


def _age_s(observed_at: str | None) -> int | None:
    if not observed_at:
        return None
    try:
        normalized = observed_at.replace("Z", "+00:00")
        observed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - observed).total_seconds()))


def _data_roles(
    witness: ActualHostWitness | None,
    infra_snapshot: dict[str, Any],
    registry_path: Path | None = None,
) -> list[StorageDataRole]:
    registry_path = registry_path or DATA_ROLE_REGISTRY
    rows = _parse_data_role_registry(registry_path)
    containers = infra_snapshot.get("containers", []) if isinstance(infra_snapshot, dict) else []
    return [_data_role(row, witness, containers) for row in rows]


def _parse_data_role_registry(path: Path) -> list[dict[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if cells[0] == "store_id":
            header = cells
            continue
        if header is None or cells[0].startswith("---"):
            continue
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def _clean_cell(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _data_role(
    row: dict[str, str],
    witness: ActualHostWitness | None,
    containers: Any,
) -> StorageDataRole:
    store_id = row.get("store_id", "")
    surface = row.get("surface", "")
    current_placement = row.get("current_placement", "")
    target_placement = row.get("target_placement", "")
    data_authority_host = _single_host_ref(current_placement)
    expected_host = _single_host_ref(target_placement)
    running_host = _container_running_host(store_id, surface, containers, witness)
    return StorageDataRole(
        store_id=store_id,
        surface=surface,
        authority_class=row.get("authority_class", ""),
        retrieval_mode=row.get("retrieval_mode", ""),
        current_placement=current_placement,
        target_placement=target_placement,
        data_authority_host=data_authority_host,
        expected_host=expected_host,
        container_running_host=running_host,
        actual_host_witness=witness,
        placement_state=_placement_state(data_authority_host, expected_host, running_host, witness),
        quality_gate=row.get("quality_gate", ""),
    )


def _single_host_ref(text: str) -> str | None:
    lower = text.lower()
    hits: set[str] = set()
    if "hapax-appendix" in lower or "appendix" in lower:
        hits.add("hapax-appendix")
    if "hapax-podium" in lower or "podium" in lower:
        hits.add("hapax-podium")
    return next(iter(hits)) if len(hits) == 1 else None


def _container_running_host(
    store_id: str,
    surface: str,
    containers: Any,
    witness: ActualHostWitness | None,
) -> str | None:
    if witness is None or witness.evidence_host is None:
        return None
    tokens = _service_tokens(store_id, surface)
    if not tokens or not isinstance(containers, list):
        return None
    for container in containers:
        if not isinstance(container, dict):
            continue
        haystack = " ".join(
            str(container.get(key, "")) for key in ("name", "service", "image")
        ).lower()
        if any(token and token in haystack for token in tokens):
            return witness.evidence_host
    return None


def _service_tokens(store_id: str, surface: str) -> set[str]:
    raw = f"{store_id} {surface}".lower()
    tokens = {
        "minio",
        "langfuse",
        "postgres",
        "clickhouse",
        "redis",
        "prometheus",
        "grafana",
        "qdrant",
        "ntfy",
    }
    return {token for token in tokens if token in raw}


def _placement_state(
    data_authority_host: str | None,
    expected_host: str | None,
    running_host: str | None,
    witness: ActualHostWitness | None,
) -> str:
    if (
        witness is None
        or witness.witness_age_s is None
        or witness.witness_age_s >= witness.max_witness_age_s
    ):
        return "unknown"
    if not (data_authority_host and expected_host and running_host):
        return "unknown"
    if data_authority_host == expected_host == running_host:
        return "aligned"
    return "drifted"


__all__ = [
    "ActualHostWitness",
    "HostStorageDevice",
    "HostStorageFilesystem",
    "HostStorageHost",
    "HostStorageSnapshot",
    "StorageDataRole",
    "collect_host_storage",
    "collect_hosts",
]
