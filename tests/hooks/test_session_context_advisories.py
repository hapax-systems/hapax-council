"""Tests for the system-state advisory lines in session-context.sh.

The hook emits several optional advisory lines based on host system
state — pacman update age, failed systemd units, stale-branch count,
disk usage, and recent reboot. These tests pin the visibility
contracts (the advisory only fires when the threshold is crossed)
without requiring the host to be in any particular state.

Each advisory is extracted into a small bash fragment and exercised
with a fake-bin PATH that injects controlled stat / systemctl / df /
uptime outputs. This is the same pattern used by the open-PR-count
test (``test_session_context_open_pr_count.py``) for the same reasons:
session-context.sh is 600+ lines and re-running the full hook is
slow + non-hermetic. Fragment extraction keeps the tests fast and
deterministic.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _make_fake_bin(tmp_path: Path, fakes: dict[str, str]) -> Path:
    """Create a fake-bin dir mapping ``name -> shell script body``.

    Each entry is written verbatim as the bin's content (after a
    ``#!/bin/sh`` shebang). The bin is chmod 755.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, body in fakes.items():
        path = bin_dir / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
    return bin_dir


def _run_fragment(tmp_path: Path, fragment: str, fake_bin: Path) -> tuple[int, str, str]:
    """Run ``fragment`` with PATH pointing at fake_bin first."""
    script = tmp_path / "fragment.sh"
    script.write_text("#!/bin/bash\nset -u\n" + fragment)
    script.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


# ── Updates advisory — pacman local-dir mtime → age threshold ─────────


UPDATES_FRAGMENT = """
LAST_UPDATE_EPOCH=$(stat -c %Y /var/lib/pacman/local 2>/dev/null || echo 0)
if [ "$LAST_UPDATE_EPOCH" -gt 0 ]; then
  UPDATE_AGE=$(( ($(date +%s) - LAST_UPDATE_EPOCH) / 86400 ))
  if [ "$UPDATE_AGE" -gt 3 ]; then
    echo "Updates: last package update was ${UPDATE_AGE} days ago (run /distro-health)"
  fi
fi
"""


class TestUpdatesAdvisory:
    def test_emits_when_more_than_3_days_old(self, tmp_path: Path) -> None:
        # 5 days ago in seconds.
        five_days_ago = "$(($(date +%s) - 5 * 86400))"
        fake = _make_fake_bin(
            tmp_path,
            {"stat": f"echo {five_days_ago}"},
        )
        rc, out, _err = _run_fragment(tmp_path, UPDATES_FRAGMENT, fake)
        assert rc == 0
        assert "Updates: last package update was 5 days ago" in out
        assert "/distro-health" in out

    def test_silent_when_recent(self, tmp_path: Path) -> None:
        # 1 day ago = within threshold, no advisory.
        one_day_ago = "$(($(date +%s) - 1 * 86400))"
        fake = _make_fake_bin(tmp_path, {"stat": f"echo {one_day_ago}"})
        rc, out, _err = _run_fragment(tmp_path, UPDATES_FRAGMENT, fake)
        assert rc == 0
        assert "Updates:" not in out

    def test_silent_when_stat_unavailable(self, tmp_path: Path) -> None:
        # stat returns 0 → fragment skips the inner block entirely.
        fake = _make_fake_bin(tmp_path, {"stat": "echo 0"})
        rc, out, _err = _run_fragment(tmp_path, UPDATES_FRAGMENT, fake)
        assert rc == 0
        assert out.strip() == ""


# ── Systemd advisory — sum of failed user + system units ──────────────


SYSTEMD_FRAGMENT = """
FAILED_USER=$(systemctl --user --failed --no-legend 2>/dev/null | wc -l)
FAILED_SYS=$(systemctl --failed --no-legend 2>/dev/null | wc -l)
TOTAL_FAILED=$((FAILED_USER + FAILED_SYS))
if [ "$TOTAL_FAILED" -gt 0 ]; then
  echo "Systemd: $TOTAL_FAILED failed unit(s) (run /diagnose or /distro-health)"
fi
"""


class TestSystemdAdvisory:
    def test_emits_when_user_units_failed(self, tmp_path: Path) -> None:
        # First call (--user) returns 2 lines; second call (no --user) returns 0.
        fake = _make_fake_bin(
            tmp_path,
            {
                "systemctl": (
                    'case "$*" in\n'
                    '  *--user*)  printf "unit-a failed\\nunit-b failed\\n";;\n'
                    '  *)         printf "";;\n'
                    "esac"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, SYSTEMD_FRAGMENT, fake)
        assert rc == 0
        assert "Systemd: 2 failed unit(s)" in out
        assert "/diagnose" in out

    def test_silent_when_no_failures(self, tmp_path: Path) -> None:
        fake = _make_fake_bin(tmp_path, {"systemctl": 'printf ""'})
        rc, out, _err = _run_fragment(tmp_path, SYSTEMD_FRAGMENT, fake)
        assert rc == 0
        assert "Systemd:" not in out

    def test_sums_user_and_system_failures(self, tmp_path: Path) -> None:
        # 1 user failure + 2 system failures = 3 total.
        fake = _make_fake_bin(
            tmp_path,
            {
                "systemctl": (
                    'case "$*" in\n'
                    '  *--user*) printf "u1\\n";;\n'
                    '  *)        printf "s1\\ns2\\n";;\n'
                    "esac"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, SYSTEMD_FRAGMENT, fake)
        assert rc == 0
        assert "Systemd: 3 failed unit(s)" in out


# ── Disk-warning advisory — df / >85% threshold ──────────────────────


DISK_FRAGMENT = """
ROOT_USE=$(df / 2>/dev/null | awk 'NR==2{gsub(/%/,""); print $5}')
if [ -n "$ROOT_USE" ] && [ "$ROOT_USE" -gt 85 ]; then
  echo "DISK WARNING: root filesystem at ${ROOT_USE}% (run /disk-triage)"
fi
"""


class TestDiskWarning:
    def test_emits_above_85_percent(self, tmp_path: Path) -> None:
        # df output: header line + data line where 5th field is "92%".
        fake = _make_fake_bin(
            tmp_path,
            {
                "df": (
                    "printf '%s\\n%s\\n' "
                    "'Filesystem 1K-blocks Used Available Use% Mounted on' "
                    "'/dev/root 100 92 8 92% /'"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, DISK_FRAGMENT, fake)
        assert rc == 0
        assert "DISK WARNING" in out
        assert "92%" in out

    def test_silent_at_or_below_threshold(self, tmp_path: Path) -> None:
        fake = _make_fake_bin(
            tmp_path,
            {
                "df": (
                    "printf '%s\\n%s\\n' "
                    "'Filesystem 1K-blocks Used Available Use% Mounted on' "
                    "'/dev/root 100 50 50 50% /'"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, DISK_FRAGMENT, fake)
        assert rc == 0
        assert "DISK WARNING" not in out

    def test_silent_at_exactly_85_percent(self, tmp_path: Path) -> None:
        # The threshold uses `-gt 85` not `-ge 85`; 85% itself is not a warning.
        fake = _make_fake_bin(
            tmp_path,
            {
                "df": (
                    "printf '%s\\n%s\\n' "
                    "'Filesystem 1K-blocks Used Available Use% Mounted on' "
                    "'/dev/root 100 85 15 85% /'"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, DISK_FRAGMENT, fake)
        assert rc == 0
        assert "DISK WARNING" not in out


# ── Recent-boot advisory — uptime <60min → "recent reboot" ──────────


BOOT_FRAGMENT = """
BOOT_AGE=$(( $(date +%s) - $(date -d "$(uptime -s)" +%s 2>/dev/null || echo "$(date +%s)") ))
if [ "$BOOT_AGE" -gt 0 ] && [ "$BOOT_AGE" -lt 3600 ]; then
  echo "System: booted $((BOOT_AGE / 60))min ago -- recent reboot (run /sys-forensics)"
fi
"""


class TestRecentBootAdvisory:
    def test_emits_when_recent_boot(self, tmp_path: Path) -> None:
        # uptime -s emits a date string; mock to 30 minutes ago.
        # Date format: "YYYY-MM-DD HH:MM:SS" (what `uptime -s` produces).
        fake = _make_fake_bin(
            tmp_path,
            {
                "uptime": (
                    'if [ "$1" = "-s" ]; then\n'
                    "  date -d '30 minutes ago' '+%Y-%m-%d %H:%M:%S'\n"
                    "fi"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, BOOT_FRAGMENT, fake)
        assert rc == 0
        assert "recent reboot" in out
        match = re.search(r"booted (\d+)min ago", out)
        assert match is not None
        assert int(match.group(1)) in {29, 30}

    def test_silent_when_uptime_more_than_an_hour(self, tmp_path: Path) -> None:
        fake = _make_fake_bin(
            tmp_path,
            {
                "uptime": (
                    "if [ \"$1\" = \"-s\" ]; then\n  date -d '2 hours ago' '+%Y-%m-%d %H:%M:%S'\nfi"
                )
            },
        )
        rc, out, _err = _run_fragment(tmp_path, BOOT_FRAGMENT, fake)
        assert rc == 0
        assert "recent reboot" not in out
