"""Phase 11 of the DR script provisions /store from the storage registry's identity.

Fifth review round of #4623: the previous rule — "first unmounted /dev/sda or /dev/sdb; if it has
no partitions, mklabel + mkfs" — would have formatted podium's second SATA disk, which the registry
records as a whole-disk filesystem with no partition table. The script now mounts the filesystem
the registry names by UUID, formats only a replacement disk the operator names and only when it
carries no signature, and carries the restored fstab's network mounts for the required roots.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESTORE_SCRIPT = REPO / "scripts" / "hapax-cachyos-restore"
REGISTRY = REPO / "config/infrastructure/host-storage-registry.json"

# The registry's record for podium's /store: the values the script must resolve, not guess.
STORE_UUID = "3210603f-c7c4-4f46-88e2-f92a856fb5eb"
STORE_BY_ID = "ata-Samsung_SSD_870_EVO_1TB_S6PTNL0YA01820L"
REPLACEMENT = "/dev/disk/by-id/ata-Replacement_Disk_NEW0001"

_SUDO = """#!/bin/sh
set -eu
case "${1:-}" in
    mkdir) printf '%s\\n' "$*" >> "$COMMAND_LOG"; shift; exec /usr/bin/mkdir "$@" ;;
    tee) printf '%s\\n' "$*" >> "$COMMAND_LOG"; shift; exec /usr/bin/tee "$@" ;;
    blkid|lsblk|parted|mkfs.ext4|udevadm) cmd=$1; shift; exec "$cmd" "$@" ;;
esac
"""

_BLKID = """#!/bin/sh
printf 'blkid %s\\n' "$*" >> "$COMMAND_LOG"
case "${1:-}" in
    -U) if [ "${FAKE_STORE_PRESENT:-0}" = 1 ]; then echo /dev/sda1; exit 0; fi; exit 2 ;;
    -s) echo new-uuid-0001 ;;
esac
"""

_LSBLK = """#!/bin/sh
printf 'lsblk %s\\n' "$*" >> "$COMMAND_LOG"
case "$*" in
    *"-dno TYPE"*) echo "${FAKE_DISK_TYPE:-disk}" ;;
    *"-no FSTYPE,PTTYPE"*) echo "${FAKE_SIGNATURES:-}" ;;
esac
"""

_LOG_ONLY = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$COMMAND_LOG"
"""


def _fake_bin(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in (
        ("sudo", _SUDO),
        ("blkid", _BLKID),
        ("lsblk", _LSBLK),
        ("parted", _LOG_ONLY),
        ("mkfs.ext4", _LOG_ONLY),
        ("udevadm", _LOG_ONLY),
    ):
        tool = fake_bin / name
        tool.write_text(body, encoding="utf-8")
        tool.chmod(0o755)
    return fake_bin


def _provision(
    tmp_path: Path,
    *,
    present: bool,
    replacement: str = "",
    signatures: str = "",
    disk_type: str = "disk",
) -> tuple[subprocess.CompletedProcess[str], Path, list[str]]:
    fake_bin = _fake_bin(tmp_path)
    fake_root = tmp_path / "fake-root"
    command_log = tmp_path / "commands.log"
    command_log.write_text("", encoding="utf-8")
    fstab = tmp_path / "fstab"
    fstab.write_text("# fresh fstab\n", encoding="utf-8")
    probe = tmp_path / "provision.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
load_backup_storage_roots "$2"
provision_store_root /store "$2" "$REPLACEMENT" "$FSTAB" "$3"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "COMMAND_LOG": str(command_log),
            "FAKE_STORE_PRESENT": "1" if present else "0",
            "FAKE_SIGNATURES": signatures,
            "FAKE_DISK_TYPE": disk_type,
            "REPLACEMENT": replacement,
            "FSTAB": str(fstab),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )
    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(REGISTRY), str(fake_root)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result, fstab, command_log.read_text(encoding="utf-8").splitlines()


def _formatting_commands(commands: list[str]) -> list[str]:
    return [c for c in commands if c.startswith(("parted ", "mkfs.ext4 "))]


def test_present_canonical_filesystem_is_mounted_by_registry_uuid_and_never_formatted(
    tmp_path: Path,
) -> None:
    result, fstab, commands = _provision(tmp_path, present=True)

    assert result.returncode == 0, result.stderr
    assert f"blkid -U {STORE_UUID}" in commands
    assert _formatting_commands(commands) == []
    assert f"UUID={STORE_UUID} /store ext4 defaults,noatime,commit=60 0 2" in fstab.read_text()
    assert (tmp_path / "fake-root" / "store").is_dir()


def test_missing_canonical_filesystem_refuses_and_names_the_expected_disk(tmp_path: Path) -> None:
    result, fstab, commands = _provision(tmp_path, present=False)

    assert result.returncode != 0
    assert STORE_UUID in result.stderr
    assert STORE_BY_ID in result.stderr
    assert "RESTORE_STORE_DEVICE" in result.stderr
    assert "nothing is formatted on a guess" in result.stderr
    assert _formatting_commands(commands) == []
    assert "/store" not in fstab.read_text()


def test_named_empty_replacement_disk_is_the_only_thing_formatted(tmp_path: Path) -> None:
    result, fstab, commands = _provision(tmp_path, present=False, replacement=REPLACEMENT)

    assert result.returncode == 0, result.stderr
    assert _formatting_commands(commands) == [
        f"parted {REPLACEMENT} --script mklabel gpt",
        f"parted {REPLACEMENT} --script mkpart store ext4 1MiB 100%",
        f"mkfs.ext4 -L store {REPLACEMENT}-part1",
    ]
    assert "UUID=new-uuid-0001 /store ext4" in fstab.read_text()
    assert "update its mount and device records" in result.stdout


def test_replacement_disk_with_a_signature_is_refused(tmp_path: Path) -> None:
    result, _fstab, commands = _provision(
        tmp_path, present=False, replacement=REPLACEMENT, signatures="ext4"
    )

    assert result.returncode != 0
    assert "already carries a filesystem or partition table" in result.stderr
    assert "wipefs" in result.stderr
    assert _formatting_commands(commands) == []


def test_replacement_that_is_not_a_whole_disk_is_refused(tmp_path: Path) -> None:
    result, _fstab, commands = _provision(
        tmp_path, present=False, replacement=REPLACEMENT, disk_type="part"
    )

    assert result.returncode != 0
    assert "is not a whole disk" in result.stderr
    assert _formatting_commands(commands) == []


def test_phase_11_no_longer_guesses_a_kernel_name() -> None:
    text = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "/dev/sda /dev/sdb" not in text
    assert 'provision_store_root "$STORE_ROOT"' in text
    assert "carry_network_mount_entries /etc/fstab.restored /etc/fstab" in text


def test_restored_network_mounts_are_carried_but_uuid_lines_are_not(tmp_path: Path) -> None:
    fake_bin = _fake_bin(tmp_path)
    command_log = tmp_path / "commands.log"
    command_log.write_text("", encoding="utf-8")
    restored = tmp_path / "fstab.restored"
    restored.write_text(
        "UUID=0000-old /store ext4 defaults 0 2\n"
        "192.168.68.71:/volume1/backups /mnt/nas nfs defaults,_netdev 0 0\n"
        "# 192.168.68.71:/volume1/media /mnt/nas-media nfs defaults 0 0\n",
        encoding="utf-8",
    )
    fstab = tmp_path / "fstab"
    fstab.write_text(
        f"UUID={STORE_UUID} /store ext4 defaults,noatime,commit=60 0 2\n", encoding="utf-8"
    )
    probe = tmp_path / "carry.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
load_backup_storage_roots "$2"
carry_network_mount_entries "$3" "$4"
carry_network_mount_entries "$3" "$4"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = os.environ.copy()
    env.update({"COMMAND_LOG": str(command_log), "PATH": f"{fake_bin}:/usr/bin:/bin"})
    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(REGISTRY), str(restored), str(fstab)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    lines = fstab.read_text(encoding="utf-8").splitlines()
    assert lines.count("192.168.68.71:/volume1/backups /mnt/nas nfs defaults,_netdev 0 0") == 1
    assert "UUID=0000-old /store ext4 defaults 0 2" not in lines
    assert not any("nas-media" in line for line in lines)


def test_rclone_config_is_written_private() -> None:
    """The rclone config carries the B2 application key; a 022 umask left it 0644 (review finding
    on #4623, round 5). The write runs under umask 077 and the file is pinned to 0600."""
    text = RESTORE_SCRIPT.read_text(encoding="utf-8")
    block = text[text.index("# Configure rclone") : text.index("# Verify backup access")]
    assert "(umask 077; cat > ~/.config/rclone/rclone.conf <<RCLONE" in block
    assert "chmod 600 ~/.config/rclone/rclone.conf" in block
    assert "chmod 700 ~/.config/rclone" in block
