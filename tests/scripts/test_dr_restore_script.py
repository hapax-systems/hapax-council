"""The DR restore script, moved into council from the archived distro-work repository.

Row tier1-backup-hardening-from-4623-20260927, piece 5. This first PR is a pure move: the file is podium's
~/projects/distro-work/hapax-cachyos-restore.sh at 4e0087f (git blob 53b4137e6), byte for byte. The seat's granted
fixes to it land in the stacked PR that follows, with their own tests.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-cachyos-restore.sh"

# sha256 of the live blob 53b4137e6 at distro-work 4e0087f.
LIVE_SHA256 = "fa0dafc78244daae304028fb980b53efb0ff36362f773325d0b4f7d7806e30cc"


def test_the_dr_script_parses() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, timeout=30)


def test_the_dr_script_is_the_live_one_byte_for_byte() -> None:
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == LIVE_SHA256


def test_the_dr_script_is_executable() -> None:
    assert SCRIPT.stat().st_mode & 0o111
