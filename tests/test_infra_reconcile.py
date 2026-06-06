from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.host_storage_model import HostStorageRegistry
from shared.infra_drift import (
    DEFAULT_REGISTRY_SEED,
    reconcile_main,
    stamp_registry_payload,
)

NOW = "2026-06-06T15:30:00Z"


def _base_fields() -> dict:
    return {
        "command_host": "hapax-podium",
        "locality_class": "same_host",
        "next_action": None,
        "observed_at": NOW,
        "recency_class": "live",
    }


def _registry_payload() -> dict:
    return {
        "schema_version": 1,
        "hosts": [
            {
                **_base_fields(),
                "host_id": "hapax-podium",
                "hostname": "hapax-podium",
                "machine_anchor": "root-serial",
            }
        ],
        "devices": [
            {
                **_base_fields(),
                "target_host": "hapax-podium",
                "serial": "serial-a",
                "presence": "present",
                "model": "Test SSD",
                "by_id": ["ata-Test_SSD_serial-a"],
                "kernel_names": ["/dev/sda"],
                "transport": "sata",
            }
        ],
        "mounts": [],
        "network_nodes": [],
        "secret_pointers": [],
        "backup_policies": [],
    }


def _receipt(host: str = "hapax-podium") -> dict:
    return {
        "schema_version": 1,
        "host_provenance": {
            "intent_host": host,
            "exec_host": host,
            "evidence_host": host,
            "transport": "local",
        },
        "hostname": host,
        "observed_at": NOW,
        "evidence_class": "live",
        "recency_class": "live",
        "locality_class": "same_host",
        "collectors": {"lsblk": {"ran": True, "exit_code": 0, "row_count": 1}},
        "devices": [
            {
                "presence": "present",
                "model": "Test SSD",
                "serial": "serial-a",
                "kernel_dev": "/dev/sda",
                "tran": "sata",
                "by_id": ["ata-Test_SSD_serial-a"],
                "filesystems": [],
            }
        ],
    }


def test_host_storage_registry_seed_validates():
    payload = json.loads(DEFAULT_REGISTRY_SEED.read_text(encoding="utf-8"))

    registry = HostStorageRegistry.model_validate(payload)

    assert registry.schema_version == 1
    assert {device.serial for device in registry.devices} >= {
        "24511K802589",
        "S7YCNJ0L100668Y",
    }


def test_stamp_registry_payload_uses_host_receipt_names():
    payload = _registry_payload()
    receipts = [(Path("hapax-podium-20260606T153000Z.json"), _receipt())]

    stamped = stamp_registry_payload(
        payload,
        receipts,
        reconciled_at="2026-06-06T15:31:00Z",
    )

    assert stamped["devices"][0]["reconciled_at"] == "2026-06-06T15:31:00Z"
    assert (
        stamped["devices"][0]["reconciled_against_receipt"] == "hapax-podium-20260606T153000Z.json"
    )
    assert "reconciled_at" not in payload["devices"][0]
    HostStorageRegistry.model_validate(stamped)


def test_reconcile_main_writes_report_and_stamps_runtime_state(tmp_path):
    seed = tmp_path / "seed.json"
    runtime_registry = tmp_path / "runtime-registry.json"
    report = tmp_path / "report.json"
    cache_dir = tmp_path / "receipts"
    cache_dir.mkdir()
    seed.write_text(json.dumps(_registry_payload()), encoding="utf-8")
    receipt_name = "hapax-podium-20260606T153000Z.json"
    (cache_dir / receipt_name).write_text(json.dumps(_receipt()), encoding="utf-8")

    rc = reconcile_main(
        [
            "--seed-json",
            str(seed),
            "--registry-json",
            str(runtime_registry),
            "--cache-dir",
            str(cache_dir),
            "--report-json",
            str(report),
            "--no-observe-backups",
            "--no-notify",
        ]
    )

    assert rc == 0
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    assert report_payload["summary"]["drifted"] == 0
    assert report_payload["summary"]["receipt_only"] == 0
    runtime_payload = json.loads(runtime_registry.read_text(encoding="utf-8"))
    reconciled_at = datetime.fromisoformat(
        runtime_payload["devices"][0]["reconciled_at"].replace("Z", "+00:00")
    )
    assert reconciled_at.tzinfo == UTC
    assert runtime_payload["devices"][0]["reconciled_against_receipt"] == receipt_name
    assert "reconciled_at" not in json.loads(seed.read_text(encoding="utf-8"))["devices"][0]


def test_reconcile_main_can_exit_on_drift(tmp_path):
    seed = tmp_path / "seed.json"
    runtime_registry = tmp_path / "runtime-registry.json"
    report = tmp_path / "report.json"
    cache_dir = tmp_path / "receipts"
    cache_dir.mkdir()
    payload = _registry_payload()
    payload["devices"] = []
    seed.write_text(json.dumps(payload), encoding="utf-8")
    (cache_dir / "hapax-podium-20260606T153000Z.json").write_text(
        json.dumps(_receipt()),
        encoding="utf-8",
    )

    rc = reconcile_main(
        [
            "--seed-json",
            str(seed),
            "--registry-json",
            str(runtime_registry),
            "--cache-dir",
            str(cache_dir),
            "--report-json",
            str(report),
            "--no-observe-backups",
            "--no-notify",
            "--exit-on-drift",
        ]
    )

    assert rc == 1
    report_payload = json.loads(report.read_text(encoding="utf-8"))
    assert report_payload["summary"]["receipt_only"] == 1


def test_reconcile_main_dry_run_does_not_initialize_runtime_state(tmp_path):
    seed = tmp_path / "seed.json"
    runtime_registry = tmp_path / "runtime-registry.json"
    report = tmp_path / "report.json"
    cache_dir = tmp_path / "receipts"
    cache_dir.mkdir()
    seed.write_text(json.dumps(_registry_payload()), encoding="utf-8")
    (cache_dir / "hapax-podium-20260606T153000Z.json").write_text(
        json.dumps(_receipt()),
        encoding="utf-8",
    )

    rc = reconcile_main(
        [
            "--seed-json",
            str(seed),
            "--registry-json",
            str(runtime_registry),
            "--cache-dir",
            str(cache_dir),
            "--report-json",
            str(report),
            "--no-observe-backups",
            "--no-notify",
            "--dry-run",
        ]
    )

    assert rc == 0
    assert not runtime_registry.exists()
    assert not report.exists()


def test_source_units_call_hapax_infra_reconcile():
    service = Path("systemd/units/hapax-infra-reconcile.service").read_text(encoding="utf-8")
    timer = Path("systemd/units/hapax-infra-reconcile.timer").read_text(encoding="utf-8")

    assert "ExecStart=%h/projects/hapax-council/scripts/hapax-infra-reconcile" in service
    assert "OnFailure=notify-failure@%n.service" in service
    assert "Unit=hapax-infra-reconcile.service" in timer
    assert "Persistent=true" in timer
