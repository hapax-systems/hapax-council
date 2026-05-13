from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-v4l2-bridge-watchdog"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{textwrap.dedent(body).strip()}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *,
    metrics: str,
    bridge_metrics: str,
    state: str | None = None,
    apply: bool = True,
    systemctl_body: str | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    metrics_file = tmp_path / "metrics.prom"
    metrics_file.write_text(textwrap.dedent(metrics).strip() + "\n", encoding="utf-8")
    bridge_file = tmp_path / "bridge.prom"
    bridge_file.write_text(textwrap.dedent(bridge_metrics).strip() + "\n", encoding="utf-8")
    if state is not None:
        (tmp_path / "state.json").write_text(textwrap.dedent(state), encoding="utf-8")
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(
        bin_dir / "systemctl",
        systemctl_body
        or f"""
        printf '%s\\n' "$*" >> {calls}
        exit 0
        """,
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    args = [
        str(SCRIPT),
        "--metrics-file",
        str(metrics_file),
        "--bridge-metrics-file",
        str(bridge_file),
        "--restart-after-stale-ticks",
        "2",
        "--state-file",
        str(tmp_path / "state.json"),
        "--textfile-path",
        str(tmp_path / "watchdog.prom"),
        "--ledger-path",
        str(tmp_path / "events.jsonl"),
    ]
    if apply:
        args.append("--apply")
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, text=True, capture_output=True, check=False, env=env)


def test_bridge_watchdog_restarts_compositor_when_shmsink_branch_stalls(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
        studio_compositor_shmsink_frames_total 100
        studio_compositor_shmsink_last_frame_seconds_ago 30
        """,
        bridge_metrics="""
        hapax_v4l2_bridge_write_frames_total 100
        hapax_v4l2_bridge_heartbeat_seconds_ago 30
        """,
        state='{"shmsink_frames": 100, "bridge_write_frames": 100, "stale_ticks": 1}',
    )

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "systemctl-calls.txt").read_text(encoding="utf-8")
    assert "--user restart studio-compositor.service hapax-v4l2-bridge.service" in calls
    textfile = (tmp_path / "watchdog.prom").read_text(encoding="utf-8")
    assert "hapax_v4l2_bridge_watchdog_restart_attempted 1" in textfile
    assert 'hapax_v4l2_bridge_watchdog_action{action="restart_compositor_bridge"} 1' in textfile


def test_bridge_watchdog_restarts_only_bridge_when_writer_stalls(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
        studio_compositor_shmsink_frames_total 120
        studio_compositor_shmsink_last_frame_seconds_ago 0.2
        """,
        bridge_metrics="""
        hapax_v4l2_bridge_write_frames_total 100
        hapax_v4l2_bridge_heartbeat_seconds_ago 30
        """,
        state='{"shmsink_frames": 100, "bridge_write_frames": 100, "stale_ticks": 1}',
    )

    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "systemctl-calls.txt").read_text(encoding="utf-8")
    assert "--user restart hapax-v4l2-bridge.service" in calls
    assert "studio-compositor.service" not in calls


def test_bridge_watchdog_noops_when_bridge_frames_advance(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
        studio_compositor_shmsink_frames_total 130
        studio_compositor_shmsink_last_frame_seconds_ago 0.1
        """,
        bridge_metrics="""
        hapax_v4l2_bridge_write_frames_total 130
        hapax_v4l2_bridge_heartbeat_seconds_ago 0.1
        """,
        state='{"shmsink_frames": 100, "bridge_write_frames": 100, "stale_ticks": 1}',
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "systemctl-calls.txt").exists()
    assert "action=none reason=bridge_fresh" in result.stdout


def test_bridge_watchdog_dry_run_does_not_restart(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
        studio_compositor_shmsink_frames_total 100
        studio_compositor_shmsink_last_frame_seconds_ago 30
        """,
        bridge_metrics="""
        hapax_v4l2_bridge_write_frames_total 100
        hapax_v4l2_bridge_heartbeat_seconds_ago 30
        """,
        state='{"shmsink_frames": 100, "bridge_write_frames": 100, "stale_ticks": 1}',
        apply=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "systemctl-calls.txt").exists()
    assert "outcome=dry_run" in result.stdout


def test_bridge_watchdog_records_timeout_without_crashing(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        metrics="""
        studio_compositor_runtime_feature_active{feature="shmsink_bridge"} 1
        studio_compositor_shmsink_frames_total 100
        studio_compositor_shmsink_last_frame_seconds_ago 30
        """,
        bridge_metrics="""
        hapax_v4l2_bridge_write_frames_total 100
        hapax_v4l2_bridge_heartbeat_seconds_ago 30
        """,
        state='{"shmsink_frames": 100, "bridge_write_frames": 100, "stale_ticks": 1}',
        systemctl_body="""
        sleep 1
        """,
        extra_args=["--command-timeout", "0.01"],
    )

    assert result.returncode == 0, result.stderr
    assert "outcome=timeout_submitted" in result.stdout
    state = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert '"stale_ticks": 0' in state
    textfile = (tmp_path / "watchdog.prom").read_text(encoding="utf-8")
    assert 'hapax_v4l2_bridge_watchdog_outcome{outcome="timeout_submitted"} 1' in textfile
