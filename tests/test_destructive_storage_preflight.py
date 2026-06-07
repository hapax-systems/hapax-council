from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.destructive_storage_preflight import (
    ApprovedAgainst,
    DestructiveStoragePreflightRequest,
    SmartHealth,
    WipeAuth,
    evaluate_preflight,
)
from shared.host_storage_inventory import build_receipt

TARGET = "hapax-appendix"
MACHINE_ID = "ffc36d1a0ca64320a3f1c9f1060292af"
SN7100 = "24511K802589"
SN7100_UUID = "1e70ec1f-00db-4734-8885-3ecbdfa400e5"
SN7100_PARTUUID = "appendix-sn7100-partuuid"
SN7100_BY_ID = "nvme-WD_BLACK_SN7100_1TB_24511K802589"
NOW = datetime(2026, 6, 6, 10, 40, tzinfo=UTC)


APPENDIX_LSBLK = {
    "blockdevices": [
        {
            "name": "sda",
            "type": "disk",
            "tran": "sata",
            "model": "T-FORCE 2TB",
            "serial": "TPBF2510310070101576",
            "children": [
                {
                    "name": "sda2",
                    "fstype": "btrfs",
                    "uuid": "d6acb7bd-74e0-4d39-8ef7-53193c6085b5",
                    "partuuid": "appendix-root-partuuid",
                    "mountpoints": ["/", "/home"],
                },
            ],
        },
        {
            "name": "nvme1n1",
            "type": "disk",
            "tran": "nvme",
            "model": "WD_BLACK SN7100 1TB",
            "serial": SN7100,
            "children": [
                {
                    "name": "nvme1n1p1",
                    "fstype": "xfs",
                    "label": "store",
                    "uuid": SN7100_UUID,
                    "partuuid": SN7100_PARTUUID,
                    "mountpoints": ["/store"],
                },
            ],
        },
    ]
}


PODIUM_LSBLK = {
    "blockdevices": [
        {
            "name": "nvme0n1",
            "type": "disk",
            "tran": "nvme",
            "model": "Samsung SSD 980 PRO with Heatsink 1TB",
            "serial": "S6WSNS0W406658B",
            "children": [
                {
                    "name": "nvme0n1p2",
                    "fstype": "btrfs",
                    "uuid": "e8d4439a-90ff-4391-a384-04fc632e46f1",
                    "partuuid": "podium-root-partuuid",
                    "mountpoints": ["/", "/home"],
                }
            ],
        }
    ]
}


def _sections(hostname: str, machine_id: str, lsblk: dict, byid: str = "") -> dict[str, str]:
    return {
        "HOSTNAME": hostname,
        "MACHINEID": machine_id,
        "LSBLK": json.dumps(lsblk),
        "BYID": byid,
        "PCINVME": "0000:01:00.0 Non-Volatile memory controller",
        "EXIT": "lsblk=0\nbyid=0\nlspci=0",
    }


def _live_appendix_receipt() -> dict:
    return build_receipt(
        TARGET,
        TARGET,
        "local",
        _sections(TARGET, MACHINE_ID, APPENDIX_LSBLK, f"{SN7100_BY_ID} ../../nvme1n1"),
        0,
    )


def _podium_receipt() -> dict:
    return build_receipt(
        "hapax-podium",
        "hapax-podium",
        "local",
        _sections("hapax-podium", "15c4e584aac74d048bcbe90fc35e6da3", PODIUM_LSBLK),
        0,
    )


def _auth(**overrides) -> WipeAuth:
    payload = {
        "target_host": TARGET,
        "serial": SN7100,
        "machine_id": MACHINE_ID,
        "approved_against": ApprovedAgainst(
            fs_uuid=SN7100_UUID,
            by_id=SN7100_BY_ID,
            partuuid=SN7100_PARTUUID,
            mountpoint="/store",
        ),
        "expires_at": NOW + timedelta(hours=1),
        "approval_ref": "operator-20260606-sn7100",
    }
    payload.update(overrides)
    return WipeAuth.model_validate(payload)


def _request(**overrides) -> DestructiveStoragePreflightRequest:
    payload = {
        "target_host": TARGET,
        "serial": SN7100,
        "wipe_auth": _auth(),
        "live_receipt": _live_appendix_receipt(),
        "receipt_emitted_at_approval": True,
        "smart_health": SmartHealth.PASSED,
        "now": NOW,
    }
    payload.update(overrides)
    return DestructiveStoragePreflightRequest.model_validate(payload)


def _predicates(result) -> set[str]:
    return {failure.predicate for failure in result.failures}


def test_exact_live_two_subsystem_preflight_passes():
    result = evaluate_preflight(_request())
    assert result.passed
    assert result.failures == []


def test_ssh_or_cross_host_receipt_fails_closed():
    receipt = build_receipt(
        TARGET,
        "hapax-podium",
        "ssh",
        _sections(TARGET, MACHINE_ID, APPENDIX_LSBLK, f"{SN7100_BY_ID} ../../nvme1n1"),
        0,
    )
    result = evaluate_preflight(_request(live_receipt=receipt))
    assert not result.passed
    assert "live_same_host_local_receipt" in _predicates(result)


def test_cached_receipt_fails_even_if_content_matches():
    result = evaluate_preflight(_request(receipt_emitted_at_approval=False))
    assert not result.passed
    assert "receipt_emitted_at_approval" in _predicates(result)


def test_stale_or_failed_collector_receipt_fails_closed():
    receipt = _live_appendix_receipt()
    receipt["recency_class"] = "stale"
    receipt["evidence_class"] = "stale"
    result = evaluate_preflight(_request(live_receipt=receipt))
    assert not result.passed
    assert "live_same_host_local_receipt" in _predicates(result)


def test_one_subsystem_or_weak_byid_alias_fails_closed():
    weak_auth = _auth(
        approved_against=ApprovedAgainst(
            fs_uuid=SN7100_UUID,
            by_id="eui.0011223344556677",
            partuuid="",
            mountpoint="/store",
        )
    )
    result = evaluate_preflight(_request(wipe_auth=weak_auth))
    assert not result.passed
    assert "by_id_is_canonical_device_identity" in _predicates(result)
    assert "two_identifier_subsystems" in _predicates(result)


def test_expired_wipeauth_fails_closed():
    result = evaluate_preflight(_request(wipe_auth=_auth(expires_at=NOW - timedelta(seconds=1))))
    assert not result.passed
    assert "auth_not_expired" in _predicates(result)


def test_uuid_changed_since_approval_fails_closed():
    result = evaluate_preflight(
        _request(
            wipe_auth=_auth(
                approved_against=ApprovedAgainst(
                    fs_uuid="new-format-new-uuid",
                    by_id=SN7100_BY_ID,
                    partuuid=SN7100_PARTUUID,
                    mountpoint="/store",
                )
            )
        )
    )
    assert not result.passed
    assert "fs_uuid_bound_to_live_mount" in _predicates(result)


def test_registry_edit_same_change_is_hard_rejected():
    result = evaluate_preflight(_request(registry_edit_in_same_change=True))
    assert not result.passed
    assert "mutation_surface_separation" in _predicates(result)


def test_machine_id_mismatch_fails_same_channel_binding():
    result = evaluate_preflight(_request(wipe_auth=_auth(machine_id="wrong-machine")))
    assert not result.passed
    assert "machine_id_same_channel" in _predicates(result)


def test_mount_authority_comes_from_live_receipt_not_registry_expectation():
    result = evaluate_preflight(
        _request(
            wipe_auth=_auth(
                approved_against=ApprovedAgainst(
                    fs_uuid=SN7100_UUID,
                    by_id=SN7100_BY_ID,
                    partuuid=SN7100_PARTUUID,
                    mountpoint="/registry-only-store",
                )
            )
        )
    )
    assert not result.passed
    assert "fs_uuid_bound_to_live_mount" in _predicates(result)


def test_smart_unknown_requires_override():
    result = evaluate_preflight(_request(smart_health=SmartHealth.UNKNOWN))
    assert not result.passed
    assert "smart_health_pass_or_override" in _predicates(result)

    override = evaluate_preflight(
        _request(smart_health=SmartHealth.UNKNOWN, smart_override_ref="CASE-SMART-OVERRIDE")
    )
    assert override.passed


def test_podium_receipt_cannot_pass_appendix_sn7100_wipe():
    result = evaluate_preflight(_request(live_receipt=_podium_receipt()))
    assert not result.passed
    assert "live_same_host_local_receipt" in _predicates(result)
    assert "serial_present_on_target" in _predicates(result)


def test_cli_fails_closed_without_leaking_serial_to_stdout(tmp_path: Path):
    auth_path = tmp_path / "auth.json"
    receipt_path = tmp_path / "receipt.json"
    auth_path.write_text(_auth(expires_at=NOW - timedelta(seconds=1)).model_dump_json())
    receipt_path.write_text(json.dumps(_live_appendix_receipt()))

    script = Path(__file__).resolve().parents[1] / "scripts" / "hapax-storage-destructive-preflight"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--target-host",
            TARGET,
            "--serial",
            SN7100,
            "--wipe-auth-json",
            str(auth_path),
            "--receipt-json",
            str(receipt_path),
            "--allow-fixture-receipt",
            "--smart-health",
            "passed",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "auth_not_expired" in result.stdout
    assert SN7100 not in result.stdout
