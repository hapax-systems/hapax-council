"""Tests for LRR Phase 3 hardware measurement helper scripts.

Covers:
  - scripts/psu-stress-test.sh — argparse + log-header generation (skips
    the actual 30-min loop by driving --duration-s 0)
  - scripts/measure-brio-operator-fps.sh — argparse + log-header
    generation + zero-sample failure mode (unreachable metrics URL)

These are operator-driven scripts that can't be exercised end-to-end
in CI (nvidia-smi not available, compositor not running), so the tests
focus on the thin shell surface: argument handling, state-dir
creation, --help output, and deterministic failure modes.

Spec: docs/superpowers/specs/2026-04-15-lrr-phase-3-hardware-validation-design.md
Plan: docs/superpowers/plans/2026-04-15-lrr-phase-3-hardware-validation-plan.md §3, §5
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PSU_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "psu-stress-test.sh"
FPS_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "measure-brio-operator-fps.sh"


def _run(script: Path, home: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{home}/bin:{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
    )


class TestPsuStressTestHelp:
    def test_help_exits_zero(self, tmp_path: Path):
        result = _run(PSU_SCRIPT, tmp_path, "--help")
        assert result.returncode == 0
        assert "PSU audit" in result.stdout
        assert "nvidia-smi" in result.stdout

    def test_unknown_flag_exits_2(self, tmp_path: Path):
        result = _run(PSU_SCRIPT, tmp_path, "--bogus")
        assert result.returncode == 2


class TestPsuStressTestNvidiaGuard:
    def test_missing_nvidia_smi_exits_2(self, tmp_path: Path):
        # Create a shadow bin dir that shadows PATH so `nvidia-smi` is
        # unreachable but basic POSIX tools (bash, date, awk, mkdir,
        # etc.) still resolve. Symlinking every tool the script needs
        # is clunky, so we symlink the ones that matter and rely on
        # /usr/bin for the rest — provided /usr/bin has no nvidia-smi.
        import shutil

        real_nvidia = shutil.which("nvidia-smi")
        # If nvidia-smi is present under a directory we can't easily
        # shadow from, skip the test — we cannot reliably hide it.
        if real_nvidia and real_nvidia == "/usr/bin/nvidia-smi":
            import pytest

            pytest.skip("nvidia-smi is in /usr/bin; cannot reliably hide it in this env")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        # Symlink every binary the script needs from /usr/bin, EXCEPT
        # nvidia-smi.
        for name in ("bash", "date", "awk", "mkdir", "sleep", "nvidia-smi"):
            if name == "nvidia-smi":
                continue
            src = shutil.which(name)
            if src:
                (bin_dir / name).symlink_to(src)
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["PATH"] = str(bin_dir)
        result = subprocess.run(
            ["bash", str(PSU_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "nvidia-smi not found" in result.stderr


class TestPsuStressTestWithNvidiaSmiStub:
    def _stub_nvidia_smi(self, bin_dir: Path, *, brake_active: bool = False) -> None:
        brake_str = "Active" if brake_active else "Not Active"
        stub = bin_dir / "nvidia-smi"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            # Emit a sample line the script's awk parser can read.
            f"echo '  120.5, 55, {brake_str}'\n"
        )
        stub.chmod(0o755)

    def test_zero_duration_runs_successfully_and_writes_log(self, tmp_path: Path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        self._stub_nvidia_smi(bin_dir)
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        result = subprocess.run(
            ["bash", str(PSU_SCRIPT), "--duration-s", "0"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        state_dir = tmp_path / "hapax-state" / "hardware-validation"
        assert state_dir.exists()
        logs = list(state_dir.glob("psu-*.log"))
        assert len(logs) == 1
        content = logs[0].read_text()
        assert "LRR Phase 3 item 3 PSU stress test" in content
        assert "# SUMMARY" in content
        assert "samples: 0" in content


class TestFpsScriptHelp:
    def test_help_exits_zero(self, tmp_path: Path):
        result = _run(FPS_SCRIPT, tmp_path, "--help")
        assert result.returncode == 0
        assert "brio-operator" in result.stdout or "28fps deficit" in result.stdout

    def test_unknown_flag_exits_2(self, tmp_path: Path):
        result = _run(FPS_SCRIPT, tmp_path, "--bogus")
        assert result.returncode == 2


class TestFpsScriptUnreachableMetrics:
    def test_unreachable_metrics_url_fails_with_no_samples(self, tmp_path: Path):
        # duration-s 1 so the loop has a chance to curl once and exit
        result = _run(
            FPS_SCRIPT,
            tmp_path,
            "--duration-s",
            "1",
            "--metrics-url",
            "http://127.0.0.1:1/metrics",
        )
        assert result.returncode == 1
        assert "no metric samples" in result.stderr or "fps stayed at 0" in result.stderr


class TestFpsScriptWithMetricsStub:
    def _start_metrics_server(self, port_file: Path, fps: str) -> subprocess.Popen:
        """Start a tiny Python HTTP server serving a stubbed metrics body."""
        body = (
            b"# HELP studio_camera_fps Current camera fps\n"
            b"# TYPE studio_camera_fps gauge\n"
            b'studio_camera_fps{role="brio-operator"} ' + fps.encode() + b"\n"
        )
        script = (
            "import http.server\n"
            "import socketserver\n"
            "import sys\n"
            f"body = {body!r}\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        self.send_response(200)\n"
            "        self.send_header('Content-Type', 'text/plain')\n"
            "        self.send_header('Content-Length', str(len(body)))\n"
            "        self.end_headers()\n"
            "        self.wfile.write(body)\n"
            "    def log_message(self, *a, **k):\n"
            "        pass\n"
            "srv = socketserver.TCPServer(('127.0.0.1', 0), H)\n"
            f"open({str(port_file)!r}, 'w').write(str(srv.server_address[1]))\n"
            "srv.serve_forever()\n"
        )
        return subprocess.Popen(
            ["python", "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_happy_path_produces_mean_fps_and_verdict(self, tmp_path: Path):
        port_file = tmp_path / "port.txt"
        proc = self._start_metrics_server(port_file, "30.5")
        try:
            # Wait for server to bind + write its port
            import time

            for _ in range(30):
                if port_file.exists() and port_file.read_text().strip():
                    break
                time.sleep(0.1)
            port = port_file.read_text().strip()
            assert port, "metrics stub server failed to start"

            result = _run(
                FPS_SCRIPT,
                tmp_path,
                "--duration-s",
                "2",
                "--metrics-url",
                f"http://127.0.0.1:{port}/metrics",
            )
            assert result.returncode == 0, result.stderr
            state_dir = tmp_path / "hapax-state" / "camera-validation"
            logs = list(state_dir.glob("brio-operator-fps-*.log"))
            assert len(logs) == 1
            content = logs[0].read_text()
            assert "# SUMMARY" in content
            assert "verdict: root-cause-closed" in content
        finally:
            proc.terminate()
            proc.wait(timeout=5)
