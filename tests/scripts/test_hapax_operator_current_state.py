"""Tests for operator-current-state systemd units."""

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "operator-current-state-render"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-operator-current-state.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-operator-current-state.timer"


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


class TestOperatorRenderScript:
    def test_script_exists_and_executable(self):
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111

    def test_script_uses_uv(self):
        assert "uv run" in SCRIPT.read_text()

    def test_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestOperatorSystemdUnits:
    def test_service_is_oneshot(self):
        assert _parse_unit(SERVICE)["Service"]["Type"] == ["oneshot"]

    def test_service_has_memory_limit(self):
        assert "MemoryMax" in _parse_unit(SERVICE)["Service"]

    def test_service_has_on_failure(self):
        assert "OnFailure" in _parse_unit(SERVICE)["Unit"]

    def test_service_exec_runs_renderer(self):
        exec_start = _parse_unit(SERVICE)["Service"]["ExecStart"][0]
        assert "operator-current-state-render" in exec_start

    def test_timer_exists(self):
        assert TIMER.exists()

    def test_timer_refreshes_frequently(self):
        unit = _parse_unit(TIMER)
        active_sec = unit["Timer"]["OnUnitActiveSec"][0]
        # Must be <= 10 minutes for useful freshness
        assert "min" in active_sec
        val = int(active_sec.replace("min", "").strip())
        assert val <= 10, f"Timer interval {val}min is too slow for freshness"

    def test_timer_has_install(self):
        assert "Install" in _parse_unit(TIMER)
