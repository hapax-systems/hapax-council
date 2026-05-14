"""Tests for hapax-backup-watchdog script and systemd units."""

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-backup-watchdog"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-backup-watchdog.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-backup-watchdog.timer"


def _parse_unit(path: pathlib.Path) -> dict[str, dict[str, list[str]]]:
    """Parse a systemd unit file, handling duplicate keys."""
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
        elif "=" in line and current is not None:
            key, _, val = line.partition("=")
            sections[current].setdefault(key.strip(), []).append(val.strip())
    return sections


class TestWatchdogScript:
    """Verify script structure and safety."""

    def test_script_exists_and_is_executable(self):
        assert SCRIPT.exists(), f"{SCRIPT} does not exist"
        assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} is not executable"

    def test_script_has_set_euo_pipefail(self):
        text = SCRIPT.read_text()
        assert "set -euo pipefail" in text, "Script must use strict mode"

    def test_script_uses_pass_for_secrets(self):
        """Secrets must come from pass, never hardcoded."""
        text = SCRIPT.read_text()
        assert "pass show" in text, "Must use pass for restic password"

    def test_script_checks_tier1_and_tier2(self):
        text = SCRIPT.read_text()
        assert "Tier1-NAS" in text, "Must check Tier 1 (NAS) snapshots"
        assert "Tier2-B2" in text, "Must check Tier 2 (B2) snapshots"

    def test_script_checks_qdrant(self):
        text = SCRIPT.read_text()
        assert "qdrant" in text.lower(), "Must check Qdrant snapshots"

    def test_script_sends_ntfy_on_failure(self):
        text = SCRIPT.read_text()
        assert "NTFY_URL" in text, "Must notify via ntfy on failure"

    def test_script_has_nonzero_exit_on_failure(self):
        text = SCRIPT.read_text()
        assert "exit 1" in text, "Must exit non-zero on failure"

    def test_script_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestWatchdogSystemdUnits:
    """Verify systemd unit file structure."""

    def test_service_file_exists(self):
        assert SERVICE.exists()

    def test_timer_file_exists(self):
        assert TIMER.exists()

    def test_service_is_oneshot(self):
        unit = _parse_unit(SERVICE)
        assert unit["Service"]["Type"] == ["oneshot"]

    def test_service_has_memory_limit(self):
        unit = _parse_unit(SERVICE)
        assert "MemoryMax" in unit["Service"], "Must have MemoryMax"

    def test_service_has_on_failure(self):
        unit = _parse_unit(SERVICE)
        assert "OnFailure" in unit["Unit"], "Must have OnFailure handler"

    def test_service_exec_start_points_to_script(self):
        unit = _parse_unit(SERVICE)
        exec_start = unit["Service"]["ExecStart"][0]
        assert "hapax-backup-watchdog" in exec_start

    def test_timer_has_persistent(self):
        unit = _parse_unit(TIMER)
        assert unit["Timer"]["Persistent"] == ["true"], "Timer must be Persistent=true"

    def test_timer_has_install_section(self):
        unit = _parse_unit(TIMER)
        assert "Install" in unit, "Timer must have [Install] section"

    def test_timer_fires_after_backup_window(self):
        unit = _parse_unit(TIMER)
        on_calendar = unit["Timer"]["OnCalendar"][0]
        time_part = on_calendar.split()[-1]
        hour = int(time_part.split(":")[0])
        assert hour >= 5, f"Timer fires at {hour}:00, should be >=05:00"
