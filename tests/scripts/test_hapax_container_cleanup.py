"""Tests for hapax-container-cleanup script and systemd units."""

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-container-cleanup"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-container-cleanup.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-container-cleanup.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


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


class TestCleanupScript:
    def test_script_exists_and_executable(self):
        assert SCRIPT.exists()
        assert SCRIPT.stat().st_mode & 0o111

    def test_strict_mode(self):
        assert "set -euo pipefail" in SCRIPT.read_text()

    def test_retired_cleanup_has_no_container_mutation_surface(self):
        body = SCRIPT.read_text()
        assert "docker" not in body
        assert "HAPAX_CONTAINER_STALE_HOURS" not in body
        assert "launcher owns lifecycle reconciliation" in body

    def test_running_retired_cleanup_never_executes_a_docker_client(self, tmp_path):
        docker_marker = tmp_path / "docker-called"
        docker = tmp_path / "docker"
        docker.write_text(f"#!/bin/sh\ntouch {docker_marker}\nexit 99\n")
        docker.chmod(0o755)

        result = subprocess.run(
            [str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
        )

        assert result.returncode == 0
        assert not docker_marker.exists()
        assert "no container mutation performed" in result.stdout

    def test_bash_syntax_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


class TestCleanupSystemdUnits:
    def test_service_is_oneshot(self):
        assert _parse_unit(SERVICE)["Service"]["Type"] == ["oneshot"]

    def test_service_has_memory_limit(self):
        assert "MemoryMax" in _parse_unit(SERVICE)["Service"]

    def test_timer_is_parked(self):
        assert "# Hapax-Parked: true" in TIMER.read_text()

    def test_timer_is_persistent(self):
        assert _parse_unit(TIMER)["Timer"]["Persistent"] == ["true"]

    def test_preset_disables_retired_timer(self):
        preset = PRESET.read_text().splitlines()
        assert "disable hapax-container-cleanup.timer" in preset
        assert "enable hapax-container-cleanup.timer" not in preset
