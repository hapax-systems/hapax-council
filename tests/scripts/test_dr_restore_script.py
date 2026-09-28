"""The DR restore script, moved into council from the archived distro-work repository.

Row tier1-backup-hardening-from-4623-20260927, piece 5. This first PR is a move: the file is podium's
~/projects/distro-work/hapax-cachyos-restore.sh at 4e0087f (git blob 53b4137e6, sha256 fa0dafc7…), with one granted
line (seat ruling 2026-09-28): RESTORE_DIR under /var/tmp, so Phase 11's tmpfs mount over /tmp cannot hide the
restored tree (#4623 round 3 prior art). The other granted fixes land in the stacked PR that follows.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-cachyos-restore.sh"

# sha256 of the live blob 53b4137e6 plus the one granted line (RESTORE_DIR=/var/tmp/hapax-restore).
MOVED_SHA256 = "a8b53fb0ed2a9c5cb153895eed1c4859176f6499a8394c27c2c490d1c6022a00"


def test_the_dr_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)


def test_the_dr_script_is_the_live_one_plus_the_restore_dir_line() -> None:
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
