"""Tests for hapax-velocity-report script and systemd units."""

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-velocity-report"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-velocity-report.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-velocity-report.timer"


def _parse_unit(path):
    sections = {}
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


class TestVelocityScript:
    def test_script_exists_and_executable(self):
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111

    def test_strict_mode(self):
        assert "set -euo pipefail" in SCRIPT.read_text()

    def test_uses_pass_for_token(self):
        text = SCRIPT.read_text()
        assert "pass show" in text

    def test_writes_json_output(self):
        text = SCRIPT.read_text()
        assert "velocity.json" in text.lower() or "REPORT_JSON" in text

    def test_writes_markdown_output(self):
        text = SCRIPT.read_text()
        assert "velocity.md" in text.lower() or "REPORT_MD" in text

    def test_collects_pr_metrics(self):
        text = SCRIPT.read_text()
        assert "prs_merged" in text or "pr_count" in text

    def test_collects_dora_metrics(self):
        text = SCRIPT.read_text()
        assert "dora" in text.lower()

    def test_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestVelocitySystemdUnits:
    def test_service_is_oneshot(self):
        assert _parse_unit(SERVICE)["Service"]["Type"] == ["oneshot"]

    def test_service_has_memory_limit(self):
        assert "MemoryMax" in _parse_unit(SERVICE)["Service"]

    def test_service_has_on_failure(self):
        assert "OnFailure" in _parse_unit(SERVICE)["Unit"]

    def test_timer_fires_at_end_of_day(self):
        unit = _parse_unit(TIMER)
        cal = unit["Timer"]["OnCalendar"][0]
        hour = int(cal.split()[-1].split(":")[0])
        assert hour >= 23, f"Timer fires at {hour}:00, should be near end of day"

    def test_timer_is_persistent(self):
        assert _parse_unit(TIMER)["Timer"]["Persistent"] == ["true"]

    def test_timer_has_install(self):
        assert "Install" in _parse_unit(TIMER)
