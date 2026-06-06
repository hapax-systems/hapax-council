"""Host-qualified infrastructure registry drift reporting.

This module compares typed host-storage registry rows against live storage
receipts. It is a witness/report layer only: it never edits registry files,
changes runtime state, or touches devices.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from shared.host_storage_inventory import CACHE_DIR
from shared.host_storage_model import (
    BackupIntendedState,
    BackupObservedState,
    HostStorageRegistry,
    PresenceState,
)

SCHEMA_VERSION = 1
DRIFT_CODE = "infra-registry-drift"
SCHEMA_SKEW_CODE = "infra-schema-version-skew"
BACKUP_STATE_DRIFT_CODE = "backup-state-drift"
DEFAULT_REGISTRY_SEED = (
    Path(__file__).resolve().parents[1] / "config" / "infrastructure" / "host-storage-registry.json"
)
DEFAULT_RUNTIME_REGISTRY = Path.home() / "hapax-state" / "storage" / "host-storage-registry.json"
DEFAULT_REPORT_PATH = Path.home() / "hapax-state" / "storage" / "infra-drift-report.json"

_DESTRUCTIVE_FIELDS = {
    "device.presence",
    "device.by_id",
    "filesystem.uuid",
    "filesystem.device_ref.serial",
    "filesystem.partuuid",
    "filesystem.mountpoints",
}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class DriftStatus(StrEnum):
    IN_SYNC = "in_sync"
    DRIFTED = "drifted"
    REGISTRY_ONLY = "registry_only"
    RECEIPT_ONLY = "receipt_only"


class DriftEntry(BaseModel):
    status: DriftStatus
    code: str
    fact_class: str
    target_host: str
    key: str
    field: str | None = None
    registry_value: Any = None
    receipt_value: Any = None
    observed_value: Any = None
    invalidates_destructive_preflight: bool = False
    next_action: str | None = None


class DriftReport(BaseModel):
    schema_version: int = SCHEMA_VERSION
    generated_at: str = Field(default_factory=_now_iso)
    entries: list[DriftEntry] = Field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return any(entry.status != DriftStatus.IN_SYNC for entry in self.entries)

    @property
    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in DriftStatus}
        for entry in self.entries:
            counts[entry.status.value] += 1
        return counts


def evaluate_infra_drift(
    registry: HostStorageRegistry,
    receipts: list[dict[str, Any]],
    backup_observations: dict[str, BackupObservedState] | None = None,
) -> DriftReport:
    """Compare registry authority rows to host-qualified receipt witnesses."""

    report = DriftReport()
    receipt_by_host = _latest_receipt_by_host(receipts)
    _compare_schema_versions(report, registry, receipt_by_host.values())
    _compare_devices(report, registry, receipt_by_host)
    _compare_mounts(report, registry, receipt_by_host)
    _compare_backup_policies(report, registry, backup_observations or {})
    return report


def load_latest_receipts(cache_dir: Path = CACHE_DIR) -> list[dict[str, Any]]:
    return [receipt for _, receipt in load_latest_receipts_with_paths(cache_dir)]


def load_latest_receipts_with_paths(
    cache_dir: Path = CACHE_DIR,
) -> list[tuple[Path, dict[str, Any]]]:
    receipts: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
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
            paths[host] = path
    return [(paths[host], receipt) for host, receipt in sorted(receipts.items())]


def ensure_runtime_registry(seed_path: Path, registry_path: Path) -> Path:
    """Create the mutable runtime registry from the source seed if needed."""

    if registry_path.exists():
        return registry_path
    payload = _load_json(str(seed_path))
    HostStorageRegistry.model_validate(payload)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return registry_path


def stamp_registry_payload(
    payload: dict[str, Any],
    receipts_with_paths: list[tuple[Path, dict[str, Any]]],
    *,
    reconciled_at: str | None = None,
) -> dict[str, Any]:
    """Stamp registry rows with the receipt witness used for reconciliation."""

    stamped = json.loads(json.dumps(payload))
    stamp = reconciled_at or _now_iso()
    receipt_by_host = {
        _receipt_host(receipt): path.name
        for path, receipt in receipts_with_paths
        if _receipt_host(receipt)
    }
    all_receipts = ",".join(sorted(receipt_by_host.values())) or None
    for section in (
        "hosts",
        "devices",
        "mounts",
        "network_nodes",
        "secret_pointers",
        "backup_policies",
    ):
        rows = stamped.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            host = row.get("target_host") or row.get("host_id") or row.get("custody_host")
            row["reconciled_at"] = stamp
            row["reconciled_against_receipt"] = receipt_by_host.get(host) or all_receipts
    return stamped


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def collect_backup_observations(
    registry: HostStorageRegistry,
    runner: Runner | None = None,
) -> dict[str, BackupObservedState]:
    """Collect read-only systemd state for backup policies with ``unit_name``."""

    runner = runner or _run_systemctl_show
    observations: dict[str, BackupObservedState] = {}
    for policy in registry.backup_policies:
        if not policy.unit_name:
            continue
        proc = runner([policy.unit_name])
        values = (proc.stdout or "").splitlines()
        load_state = values[0].strip() if values else "unknown"
        active_state = values[1].strip() if len(values) > 1 else "unknown"
        observations[policy.store_id] = BackupObservedState(
            load_state=load_state or "unknown",
            active_state=active_state or "unknown",
            witnessed_at=datetime.now(UTC),
        )
    return observations


def _run_systemctl_show(args: list[str]) -> subprocess.CompletedProcess[str]:
    unit_name = args[0]
    return subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            unit_name,
            "--property=LoadState",
            "--property=ActiveState",
            "--value",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _compare_schema_versions(
    report: DriftReport,
    registry: HostStorageRegistry,
    receipts: Any,
) -> None:
    for receipt in receipts:
        receipt_version = receipt.get("schema_version")
        if receipt_version != registry.schema_version:
            host = _receipt_host(receipt) or "unknown-host"
            _add(
                report,
                status=DriftStatus.DRIFTED,
                code=SCHEMA_SKEW_CODE,
                fact_class="schema",
                target_host=host,
                key=f"{host}:schema_version",
                field="schema_version",
                registry_value=registry.schema_version,
                receipt_value=receipt_version,
                next_action="align receipt and registry schema versions before reconciling fields",
            )


def _compare_devices(
    report: DriftReport,
    registry: HostStorageRegistry,
    receipts_by_host: dict[str, dict[str, Any]],
) -> None:
    receipt_devices = _receipt_device_index(receipts_by_host)
    registry_keys = {device.registry_key for device in registry.devices}

    for device in registry.devices:
        key = device.registry_key
        receipt_device = receipt_devices.get(key)
        if receipt_device is None:
            if device.presence == PresenceState.ABSENT and _host_witnessed(
                receipts_by_host, device.target_host
            ):
                _add(
                    report,
                    status=DriftStatus.IN_SYNC,
                    code=DRIFT_CODE,
                    fact_class="device",
                    target_host=device.target_host,
                    key=_key(*key),
                    field="device.presence",
                    registry_value=device.presence.value,
                    receipt_value=PresenceState.ABSENT.value,
                )
            else:
                _add(
                    report,
                    status=DriftStatus.REGISTRY_ONLY,
                    code=DRIFT_CODE,
                    fact_class="device",
                    target_host=device.target_host,
                    key=_key(*key),
                    registry_value=device.model_dump(mode="json"),
                    next_action=device.next_action
                    or "refresh host-storage receipt and reconcile registry device row",
                )
            continue

        _compare_field(
            report,
            fact_class="device",
            target_host=device.target_host,
            key=_key(*key),
            field="device.presence",
            registry_value=device.presence.value,
            receipt_value=PresenceState.PRESENT.value,
        )
        _compare_field(
            report,
            fact_class="device",
            target_host=device.target_host,
            key=_key(*key),
            field="device.model",
            registry_value=device.model,
            receipt_value=receipt_device.get("model"),
        )
        _compare_field(
            report,
            fact_class="device",
            target_host=device.target_host,
            key=_key(*key),
            field="device.by_id",
            registry_value=sorted(device.by_id),
            receipt_value=sorted(receipt_device.get("by_id") or []),
        )

    for key, receipt_device in sorted(receipt_devices.items()):
        if key in registry_keys:
            continue
        host, serial = key
        _add(
            report,
            status=DriftStatus.RECEIPT_ONLY,
            code=DRIFT_CODE,
            fact_class="device",
            target_host=host,
            key=_key(host, serial),
            receipt_value=receipt_device,
            invalidates_destructive_preflight=True,
            next_action="add a host-qualified registry row or mark the device intentionally untracked",
        )


def _compare_mounts(
    report: DriftReport,
    registry: HostStorageRegistry,
    receipts_by_host: dict[str, dict[str, Any]],
) -> None:
    receipt_mounts = _receipt_mount_index(receipts_by_host)
    registry_keys = {mount.registry_key for mount in registry.mounts}

    for mount in registry.mounts:
        key = mount.registry_key
        receipt_mount = receipt_mounts.get(key)
        if receipt_mount is None:
            _add(
                report,
                status=DriftStatus.REGISTRY_ONLY,
                code=DRIFT_CODE,
                fact_class="filesystem",
                target_host=mount.target_host,
                key=_key(*key),
                registry_value=mount.model_dump(mode="json"),
                invalidates_destructive_preflight=True,
                next_action=mount.next_action
                or "refresh host-storage receipt and reconcile filesystem row",
            )
            continue
        _compare_field(
            report,
            fact_class="filesystem",
            target_host=mount.target_host,
            key=_key(*key),
            field="filesystem.device_ref.serial",
            registry_value=mount.device_ref.serial,
            receipt_value=receipt_mount.get("serial"),
        )
        _compare_field(
            report,
            fact_class="filesystem",
            target_host=mount.target_host,
            key=_key(*key),
            field="filesystem.fstype",
            registry_value=mount.fstype,
            receipt_value=receipt_mount.get("fstype"),
        )
        _compare_field(
            report,
            fact_class="filesystem",
            target_host=mount.target_host,
            key=_key(*key),
            field="filesystem.label",
            registry_value=mount.label,
            receipt_value=receipt_mount.get("label"),
        )
        _compare_field(
            report,
            fact_class="filesystem",
            target_host=mount.target_host,
            key=_key(*key),
            field="filesystem.mountpoints",
            registry_value=sorted(mount.mountpoints),
            receipt_value=sorted(receipt_mount.get("mountpoints") or []),
        )
        _compare_field(
            report,
            fact_class="filesystem",
            target_host=mount.target_host,
            key=_key(*key),
            field="filesystem.partuuid",
            registry_value=mount.partuuid,
            receipt_value=receipt_mount.get("partuuid"),
        )

    for key, receipt_mount in sorted(receipt_mounts.items()):
        if key in registry_keys:
            continue
        host, uuid = key
        _add(
            report,
            status=DriftStatus.RECEIPT_ONLY,
            code=DRIFT_CODE,
            fact_class="filesystem",
            target_host=host,
            key=_key(host, uuid),
            receipt_value=receipt_mount,
            invalidates_destructive_preflight=True,
            next_action="add a host-qualified filesystem registry row or mark it intentionally untracked",
        )


def _compare_backup_policies(
    report: DriftReport,
    registry: HostStorageRegistry,
    backup_observations: dict[str, BackupObservedState],
) -> None:
    for policy in registry.backup_policies:
        observed = backup_observations.get(policy.store_id) or policy.observed_state
        if observed is None:
            _add(
                report,
                status=DriftStatus.REGISTRY_ONLY,
                code=BACKUP_STATE_DRIFT_CODE,
                fact_class="backup",
                target_host=policy.target_host or "unknown-host",
                key=policy.store_id,
                field="backup.observed_state",
                registry_value=policy.intended_state.value,
                next_action=policy.next_action
                or "collect systemctl observed state for backup unit",
            )
            continue
        ok = _backup_state_matches(policy.intended_state, observed)
        _add(
            report,
            status=DriftStatus.IN_SYNC if ok else DriftStatus.DRIFTED,
            code=BACKUP_STATE_DRIFT_CODE,
            fact_class="backup",
            target_host=policy.target_host or "unknown-host",
            key=policy.store_id,
            field="backup.intended_state",
            registry_value=policy.intended_state.value,
            observed_value=observed.model_dump(mode="json"),
            next_action=None if ok else policy.next_action or "align backup unit state with policy",
        )


def _backup_state_matches(
    intended: BackupIntendedState,
    observed: BackupObservedState,
) -> bool:
    active = observed.active_state
    loaded = observed.load_state
    if intended == BackupIntendedState.ENABLED:
        return loaded == "loaded" and active == "active"
    if intended == BackupIntendedState.PAUSED:
        return active in {"inactive", "failed"} and loaded in {"loaded", "not-found"}
    if intended == BackupIntendedState.RETIRED:
        return active != "active"
    return False


def _latest_receipt_by_host(receipts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        host = _receipt_host(receipt)
        if not host:
            continue
        current = out.get(host)
        if current is None or str(receipt.get("observed_at", "")) > str(
            current.get("observed_at", "")
        ):
            out[host] = receipt
    return out


def _receipt_host(receipt: dict[str, Any]) -> str | None:
    hp = receipt.get("host_provenance") or {}
    return hp.get("evidence_host") or receipt.get("hostname") or hp.get("intent_host")


def _host_witnessed(receipts_by_host: dict[str, dict[str, Any]], host: str) -> bool:
    receipt = receipts_by_host.get(host)
    if not receipt:
        return False
    collectors = receipt.get("collectors") or {}
    return bool(collectors.get("lsblk", {}).get("ran")) and bool(receipt.get("devices") is not None)


def _receipt_device_index(
    receipts_by_host: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for host, receipt in receipts_by_host.items():
        if not _host_witnessed(receipts_by_host, host):
            continue
        for device in receipt.get("devices") or []:
            serial = device.get("serial")
            if serial:
                out[(host, serial)] = device
    return out


def _receipt_mount_index(
    receipts_by_host: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for host, receipt in receipts_by_host.items():
        if not _host_witnessed(receipts_by_host, host):
            continue
        for device in receipt.get("devices") or []:
            serial = device.get("serial")
            for fs in device.get("filesystems") or []:
                uuid = fs.get("uuid")
                if not uuid:
                    continue
                row = dict(fs)
                row["serial"] = serial
                out[(host, uuid)] = row
    return out


def _compare_field(
    report: DriftReport,
    *,
    fact_class: str,
    target_host: str,
    key: str,
    field: str,
    registry_value: Any,
    receipt_value: Any,
) -> None:
    _add(
        report,
        status=DriftStatus.IN_SYNC if registry_value == receipt_value else DriftStatus.DRIFTED,
        code=DRIFT_CODE,
        fact_class=fact_class,
        target_host=target_host,
        key=key,
        field=field,
        registry_value=registry_value,
        receipt_value=receipt_value,
        invalidates_destructive_preflight=field in _DESTRUCTIVE_FIELDS
        and registry_value != receipt_value,
        next_action=None
        if registry_value == receipt_value
        else f"reconcile {field} for {key} against the latest host-qualified receipt",
    )


def _add(report: DriftReport, **kwargs: Any) -> None:
    report.entries.append(DriftEntry(**kwargs))


def _key(host: str, identifier: str) -> str:
    return f"{host}:{identifier}"


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _notify_drift(report: DriftReport, report_path: Path = DEFAULT_REPORT_PATH) -> None:
    drift_entries = [entry for entry in report.entries if entry.status != DriftStatus.IN_SYNC]
    if not drift_entries:
        return
    codes = sorted({entry.code for entry in drift_entries})
    body = f"{len(drift_entries)} drift item(s): {', '.join(codes)}. Report: {report_path}"
    try:
        from shared.notify import send_notification

        send_notification(
            "Infra Registry Drift",
            body,
            priority="high",
            tags=["warning"],
        )
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host storage registry drift reporter")
    parser.add_argument("--registry-json", required=True)
    parser.add_argument("--receipt-json", action="append", default=[])
    parser.add_argument("--cache-dir", default=str(CACHE_DIR))
    parser.add_argument("--backup-observations-json")
    parser.add_argument("--observe-backups", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    registry = HostStorageRegistry.model_validate(_load_json(args.registry_json))
    receipts = (
        [_load_json(path) for path in args.receipt_json]
        if args.receipt_json
        else load_latest_receipts(Path(args.cache_dir))
    )
    backup_observations: dict[str, BackupObservedState] = {}
    if args.backup_observations_json:
        raw = _load_json(args.backup_observations_json)
        backup_observations = {
            key: BackupObservedState.model_validate(value) for key, value in raw.items()
        }
    if args.observe_backups:
        backup_observations.update(collect_backup_observations(registry))

    report = evaluate_infra_drift(registry, receipts, backup_observations)
    payload = report.model_dump(mode="json")
    payload["summary"] = report.summary
    print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
    return 1 if report.has_drift else 0


def reconcile_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stamp host-storage registry reconciliation")
    parser.add_argument("--seed-json", default=str(DEFAULT_REGISTRY_SEED))
    parser.add_argument("--registry-json", default=str(DEFAULT_RUNTIME_REGISTRY))
    parser.add_argument("--cache-dir", default=str(CACHE_DIR))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--observe-backups", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--notify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exit-on-drift", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    seed_path = Path(args.seed_json)
    registry_path = Path(args.registry_json)
    if registry_path.exists() or not args.dry_run:
        registry_path = ensure_runtime_registry(seed_path, registry_path)
        registry_payload = _load_json(str(registry_path))
    else:
        registry_payload = _load_json(str(seed_path))
    registry = HostStorageRegistry.model_validate(registry_payload)
    receipts_with_paths = load_latest_receipts_with_paths(Path(args.cache_dir))
    receipts = [receipt for _, receipt in receipts_with_paths]
    backup_observations = collect_backup_observations(registry) if args.observe_backups else {}
    report = evaluate_infra_drift(registry, receipts, backup_observations)
    report_payload = report.model_dump(mode="json")
    report_payload["summary"] = report.summary
    report_payload["receipt_sources"] = [path.name for path, _ in receipts_with_paths]

    if not args.dry_run:
        report_path = Path(args.report_json)
        _write_json(report_path, report_payload)
        stamped_payload = stamp_registry_payload(registry_payload, receipts_with_paths)
        HostStorageRegistry.model_validate(stamped_payload)
        _write_json(registry_path, stamped_payload)
    if args.notify:
        _notify_drift(report, Path(args.report_json))

    print(json.dumps(report_payload, indent=2 if args.pretty else None, sort_keys=True))
    return 1 if args.exit_on_drift and report.has_drift else 0


__all__ = [
    "BACKUP_STATE_DRIFT_CODE",
    "DEFAULT_REGISTRY_SEED",
    "DEFAULT_REPORT_PATH",
    "DEFAULT_RUNTIME_REGISTRY",
    "DRIFT_CODE",
    "SCHEMA_SKEW_CODE",
    "DriftEntry",
    "DriftReport",
    "DriftStatus",
    "collect_backup_observations",
    "ensure_runtime_registry",
    "evaluate_infra_drift",
    "load_latest_receipts",
    "load_latest_receipts_with_paths",
    "main",
    "reconcile_main",
    "stamp_registry_payload",
]
