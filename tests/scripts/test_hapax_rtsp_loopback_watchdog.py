from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-rtsp-loopback-watchdog"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{textwrap.dedent(body).strip()}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *,
    metrics: str,
    io_text: str | None = None,
    apply: bool = True,
) -> subprocess.CompletedProcess[str]:
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(textwrap.dedent(metrics).strip() + "\n", encoding="utf-8")
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(
        bin_dir / "systemctl",
        f"""
        printf '%s\\n' "$*" >> {calls}
        if [[ "$*" == "--user show -p MainPID --value hapax-rtsp-pi4-brio.service" ]]; then
          printf '1234\\n'
          exit 0
        fi
        if [[ "$*" == "--user restart hapax-rtsp-pi4-brio.service" ]]; then
          exit 0
        fi
        exit 0
        """,
    )
    proc_root = tmp_path / "proc"
    if io_text is not None:
        (proc_root / "1234").mkdir(parents=True)
        (proc_root / "1234" / "io").write_text(textwrap.dedent(io_text), encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    args = [
        str(SCRIPT),
        "--metrics-file",
        str(metrics_file),
        "--producer",
        "brio-operator:/dev/video60:hapax-rtsp-pi4-brio.service",
        "--sample-seconds",
        "0",
        "--proc-root",
        str(proc_root),
        "--state-file",
        str(tmp_path / "state.json"),
        "--textfile-path",
        str(tmp_path / "watchdog.prom"),
        "--ledger-path",
        str(tmp_path / "events.jsonl"),
    ]
    if apply:
        args.append("--apply")
    return subprocess.run(args, text=True, capture_output=True, check=False, env=env)


def test_rtsp_loopback_watchdog_restarts_stale_writer_for_stale_camera(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_cameras_total 9
        studio_compositor_cameras_healthy 8
        studio_camera_last_frame_age_seconds{model="unknown",role="brio-operator"} 7.5
        studio_camera_state{role="brio-operator",state="healthy"} 0
        """,
        io_text="""
        wchar: 100
        syscw: 10
        write_bytes: 0
        """,
    )

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "systemctl-calls.txt").read_text(encoding="utf-8")
    assert "--user restart hapax-rtsp-pi4-brio.service" in calls
    textfile = (tmp_path / "watchdog.prom").read_text(encoding="utf-8")
    assert 'hapax_rtsp_loopback_watchdog_camera_stale{role="brio-operator"' in textfile
    assert 'hapax_rtsp_loopback_watchdog_writer_stale{role="brio-operator"' in textfile
    assert "hapax_rtsp_loopback_watchdog_restart_attempted" in textfile
    assert (tmp_path / "events.jsonl").exists()


def test_rtsp_loopback_watchdog_noops_when_camera_is_fresh(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_cameras_total 9
        studio_compositor_cameras_healthy 9
        studio_camera_last_frame_age_seconds{model="unknown",role="brio-operator"} 0.2
        studio_camera_state{role="brio-operator",state="healthy"} 1
        """,
        io_text=None,
    )

    assert result.returncode == 0, result.stderr
    calls_path = tmp_path / "systemctl-calls.txt"
    calls = calls_path.read_text(encoding="utf-8") if calls_path.exists() else ""
    assert "restart hapax-rtsp-pi4-brio.service" not in calls
    assert "action=none reason=camera_fresh" in result.stdout


def test_rtsp_loopback_watchdog_dry_run_records_without_restart(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_cameras_total 9
        studio_compositor_cameras_healthy 8
        studio_camera_last_frame_age_seconds{model="unknown",role="brio-operator"} 9
        """,
        io_text="""
        wchar: 100
        syscw: 10
        """,
        apply=False,
    )

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "systemctl-calls.txt").read_text(encoding="utf-8")
    assert "restart hapax-rtsp-pi4-brio.service" not in calls
    assert "action=dry_run_restart" in result.stdout
