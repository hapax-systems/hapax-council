"""Tests for shared.host_storage_inventory — the SN7100 regression is pinned here.

Canned lsblk fixtures (no live host / no SSH). Asserts the host-context-drift
failure cannot recur: podium lacks serial 24511K802589, appendix has it, and the
two are never collapsed into a single global verb.
"""

from __future__ import annotations

import json

from shared.host_storage_inventory import (
    build_receipt,
    parse_lsblk,
    query_serial,
    render_rollup,
    root_serial_from,
)

SN7100 = "24511K802589"
SN7100_UUID = "1e70ec1f-00db-4734-8885-3ecbdfa400e5"
PODIUM_STORE_UUID = "3210603f-c7c4-4f46-88e2-f92a856fb5eb"

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
                    "name": "nvme0n1p1",
                    "fstype": "vfat",
                    "uuid": "CD79-B1BE",
                    "mountpoints": ["/boot"],
                },
                {
                    "name": "nvme0n1p2",
                    "fstype": "btrfs",
                    "uuid": "e8d4439a-90ff-4391-a384-04fc632e46f1",
                    "mountpoints": ["/home", "/", "/var/log"],
                },
            ],
        },
        {
            "name": "sda",
            "type": "disk",
            "tran": "sata",
            "model": "Samsung SSD 870 EVO 1TB",
            "serial": "S6PTNL0YA01820L",
            "children": [
                {
                    "name": "sda1",
                    "fstype": "ext4",
                    "label": "store",
                    "uuid": PODIUM_STORE_UUID,
                    "mountpoints": ["/store", "/var/lib/docker"],
                },
            ],
        },
        {
            "name": "sdb",
            "type": "disk",
            "tran": "sata",
            "model": "Samsung SSD 870 EVO 1TB",
            "serial": "S8HUNS0YC03008L",
            "fstype": "btrfs",
            "label": "hapax-data",
            "uuid": "65221e40-a3aa-4537-afe3-91a93f825708",
            "mountpoints": ["/data"],
        },
        {"name": "zram0", "type": "disk"},
    ]
}

APPENDIX_LSBLK = {
    "blockdevices": [
        {
            "name": "sda",
            "type": "disk",
            "tran": "sata",
            "model": "T-FORCE 2TB",
            "serial": "TPBF2510310070101576",
            "children": [
                {"name": "sda1", "fstype": "vfat", "uuid": "7719-38FF", "mountpoints": ["/boot"]},
                {
                    "name": "sda2",
                    "fstype": "btrfs",
                    "uuid": "d6acb7bd-74e0-4d39-8ef7-53193c6085b5",
                    "mountpoints": ["/", "/home"],
                },
            ],
        },
        {
            "name": "nvme0n1",
            "type": "disk",
            "tran": "nvme",
            "model": "Samsung SSD 9100 PRO 2TB",
            "serial": "S7YCNJ0L100668Y",
            "children": [
                {
                    "name": "nvme0n1p1",
                    "fstype": "xfs",
                    "label": "store-fast",
                    "uuid": "5934e619-0f38-4285-8556-5fed21ef7b9a",
                    "mountpoints": ["/store-fast"],
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
                    "mountpoints": ["/store"],
                },
            ],
        },
    ]
}


def _sections(hostname: str, lsblk: dict, pci_lines: int) -> dict[str, str]:
    return {
        "HOSTNAME": hostname,
        "LSBLK": json.dumps(lsblk),
        "BYID": "",
        "PCINVME": "\n".join(f"00:0{i}.0 Non-Volatile memory controller" for i in range(pci_lines)),
        "EXIT": "lsblk=0\nbyid=0\nlspci=0",
    }


def _podium() -> dict:
    return build_receipt(
        "hapax-podium", "hapax-podium", "local", _sections("hapax-podium", PODIUM_LSBLK, 1), 0
    )


def _appendix() -> dict:
    return build_receipt(
        "hapax-appendix", "hapax-podium", "ssh", _sections("hapax-appendix", APPENDIX_LSBLK, 2), 0
    )


# ── parsing ─────────────────────────────────────────────────────────────────


def test_parse_lsblk_skips_zram_and_keeps_disks():
    devices = parse_lsblk(json.dumps(PODIUM_LSBLK))
    serials = {d["serial"] for d in devices}
    assert serials == {"S6WSNS0W406658B", "S6PTNL0YA01820L", "S8HUNS0YC03008L"}
    assert SN7100 not in serials


def test_root_serial_detected_across_multi_mountpoint_btrfs():
    # root '/' is NOT the first mountpoint in the btrfs list — must still be found.
    assert root_serial_from(parse_lsblk(json.dumps(PODIUM_LSBLK))) == "S6WSNS0W406658B"
    assert root_serial_from(parse_lsblk(json.dumps(APPENDIX_LSBLK))) == "TPBF2510310070101576"


# ── the SN7100 regression (host-scoped, never global) ───────────────────────


def test_sn7100_absent_on_podium_present_on_appendix():
    receipts = {"hapax-podium": _podium(), "hapax-appendix": _appendix()}
    states = query_serial(receipts, SN7100)
    assert states["hapax-podium"] == "absent"
    assert states["hapax-appendix"] == "present"


def test_failed_collector_yields_not_witnessed_never_absent():
    # lsblk returned nothing (collector failure) -> UNKNOWN, never "absent".
    sec = {
        "HOSTNAME": "hapax-podium",
        "LSBLK": "",
        "BYID": "",
        "PCINVME": "",
        "EXIT": "lsblk=127\nbyid=0\nlspci=0",
    }
    receipt = build_receipt("hapax-podium", "hapax-podium", "local", sec, 0)
    states = query_serial({"hapax-podium": receipt}, SN7100)
    assert states["hapax-podium"] == "not_witnessed"


# ── machine-rooted anchor verification ──────────────────────────────────────


def test_anchor_verified_when_root_serial_matches_pin():
    assert _podium()["evidence_witness"]["anchor_verified"] is True
    assert _appendix()["evidence_witness"]["anchor_verified"] is True


def test_anchor_rejected_on_hostname_or_serial_mismatch():
    # right hostname, wrong root serial (spoof / wrong box) -> anchor fails.
    bad = dict(PODIUM_LSBLK)
    bad_blockdevices = [dict(b) for b in PODIUM_LSBLK["blockdevices"]]
    bad_blockdevices[0] = {**bad_blockdevices[0], "serial": "WRONGSERIAL000"}
    bad["blockdevices"] = bad_blockdevices
    receipt = build_receipt(
        "hapax-podium", "hapax-podium", "local", _sections("hapax-podium", bad, 1), 0
    )
    assert receipt["evidence_witness"]["anchor_verified"] is False
    assert receipt["warnings"]


# ── provenance classes ──────────────────────────────────────────────────────


def test_evidence_class_local_live_vs_ssh_recent():
    assert _podium()["evidence_class"] == "live"  # same-host
    assert _appendix()["evidence_class"] == "recent"  # cross-host SSH


# ── rollup renders three states + per-host divergence ───────────────────────


def test_rollup_shows_per_host_absence_and_distinct_store_devices():
    rollup = render_rollup({"hapax-podium": _podium(), "hapax-appendix": _appendix()})
    # store-fast exists only on appendix -> podium cell is an explicit per-host absence
    assert "not present on this host" in rollup
    # the two /store filesystems are DIFFERENT (distinct UUIDs), never collapsed
    assert SN7100_UUID[:13] in rollup
    assert PODIUM_STORE_UUID[:13] in rollup
    # NVMe controller counts diverge
    assert "hapax-podium**: 1 NVMe" in rollup
    assert "hapax-appendix**: 2 NVMe" in rollup


def test_rollup_never_emits_bare_missing_verb():
    rollup = render_rollup({"hapax-podium": _podium(), "hapax-appendix": _appendix()}).lower()
    assert "not visible" not in rollup
    assert "missing" not in rollup
