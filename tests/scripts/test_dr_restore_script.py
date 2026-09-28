"""The DR restore script, moved into council from the archived distro-work repository.

Row tier1-backup-hardening-from-4623-20260927, piece 5. This first PR is a move: the file is podium's
~/projects/distro-work/hapax-cachyos-restore.sh at 4e0087f (git blob 53b4137e6, sha256 fa0dafc7…), with two granted
hunks (seat rulings 2026-09-28): RESTORE_DIR under /var/tmp, so Phase 11's tmpfs mount over /tmp cannot hide the
restored tree (#4623 round 3 prior art), and Phase 14 initializing nothing, only warning with the NAS tier-1 target.
The other granted fixes land in the stacked PR that follows.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-cachyos-restore.sh"

# sha256 of the live blob 53b4137e6 plus the two granted hunks (RESTORE_DIR=/var/tmp/hapax-restore; Phase 14 warns).
MOVED_SHA256 = "2860f98355895768edab9becbd64128cd56af0d1c63d7278839e38c75ec5e479"


def test_the_dr_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)


def test_the_dr_script_is_the_live_one_plus_the_two_granted_hunks() -> None:
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == MOVED_SHA256


def test_the_dr_script_is_executable() -> None:
    assert SCRIPT.stat().st_mode & 0o111


def test_the_restore_tree_survives_the_later_tmpfs_mount() -> None:
    """Phase 2 restores into RESTORE_DIR, and Phase 11 later mounts tmpfs over /tmp. A restore tree under /tmp would
    be hidden before Phase 12 reads it, so RESTORE_DIR lives under /var/tmp (#4623 round 3 prior art; seat ruling
    2026-09-28, #4820's one granted line). No mount in the script may cover RESTORE_DIR or any of its parents."""

    import re

    text = SCRIPT.read_text(encoding="utf-8")
    (restore_dir,) = re.findall(r'^RESTORE_DIR="([^"]+)"$', text, re.M)
    assert restore_dir == "/var/tmp/hapax-restore"
    assert not restore_dir.startswith("/tmp/")
    covered = {
        "/" + "/".join(Path(restore_dir).parts[1:i])
        for i in range(1, len(Path(restore_dir).parts) + 1)
    }
    mount_points = re.findall(r"^\s*(?:sudo\s+)?mount\s.*\s(\S+)\s*$", text, re.M)
    assert mount_points, "the scan found no mount lines; it must see Phase 11's tmpfs mount"
    assert not covered & set(mount_points), (
        f"a mount covers the restore tree: {covered & set(mount_points)}"
    )


def test_phase_14_initializes_nothing_and_names_the_real_tier1_repo() -> None:
    """The live Phase 14 ran `restic init` on a root-owned /data/backups/restic as the user, hid the error and reported
    success, and hapax-backup-local never writes there. It now only warns with the NAS target and the next action
    (seat ruling 2026-09-28, #4820's second granted hunk)."""

    text = SCRIPT.read_text(encoding="utf-8")
    phase_14 = text.split('log "=== Phase 14:')[1].split('log "=== Phase 15:')[0]
    assert "restic" not in phase_14.replace("/backups/restic", "")
    assert "|| ok" not in phase_14 and "/data/backups" not in phase_14
    assert "warn " in phase_14 and "/mnt/nas/backups/restic" in phase_14
    assert "hapax-backup-local" in phase_14
    local = (SCRIPT.parent / "hapax-backup-local").read_text(encoding="utf-8")
    assert 'REPO="/mnt/nas/backups/restic"' in local
