"""Launcher detach projections must never signal a process or clear ownership."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"
REAPER = REPO_ROOT / "scripts" / "hapax-lane-reaper"


def _spawn_launcher() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["python3", "-c", "import time; time.sleep(600)"], start_new_session=True
    )


def _cleanup(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)


def _base(
    tmp_path: Path,
    proc: subprocess.Popen[bytes],
    *,
    task_status: str | None,
    ceiling: int = 21600,
) -> tuple[dict[str, str], tuple[Path, ...]]:
    home = tmp_path / "home"
    active = home / "vault" / "active"
    cache = home / ".cache" / "hapax"
    runtime = tmp_path / "runtime"
    worktree = home / "projects" / "hapax-council--delta"
    for path in (active, cache, runtime, worktree, tmp_path / "bin"):
        path.mkdir(parents=True, exist_ok=True)
    tmux = tmp_path / "bin" / "tmux"
    tmux.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    tmux.chmod(0o755)

    task_id = "launcher-task"
    claim = cache / "cc-active-task-delta"
    epoch = cache / "cc-claim-epoch-delta"
    binding = cache / "cc-dispatch-binding-delta.json"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    epoch.write_text(f"1783814400 {task_id}\n", encoding="utf-8")
    binding.write_text('{"binding":"sentinel"}\n', encoding="utf-8")
    paths: list[Path] = [claim, epoch, binding]
    if task_status is not None:
        note = active / f"{task_id}.md"
        note.write_text(
            textwrap.dedent(
                f"""\
                ---
                task_id: {task_id}
                title: "Launcher task"
                status: {task_status}
                assigned_to: delta
                pr: null
                claimed_at: 2026-07-12T00:00:00Z
                ---
                """
            ),
            encoding="utf-8",
        )
        paths.append(note)
    (runtime / "delta.launcher.pid").write_text(f"{proc.pid}\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{tmp_path / 'bin'}:{env['PATH']}",
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(runtime),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAIM_CACHE_DIR": str(cache),
            "HAPAX_SUPERVISOR_METRICS_FILE": "",
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "delta",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            "HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S": str(ceiling),
        }
    )
    return env, tuple(paths)


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True, timeout=30)


def _snapshot(paths: tuple[Path, ...]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def test_terminal_projection_keeps_launcher_and_claim_state(tmp_path: Path) -> None:
    proc = _spawn_launcher()
    try:
        env, paths = _base(tmp_path, proc, task_status=None)
        before = _snapshot(paths)

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert "DETACH_CANDIDATE" in result.stdout
        assert "claim_note_incoherent" in result.stdout
        assert "no signal, task rewrite, or claim cleanup" in result.stdout
        assert proc.poll() is None
        assert _snapshot(paths) == before
    finally:
        _cleanup(proc)


def test_lifetime_projection_keeps_live_launcher_and_task(tmp_path: Path) -> None:
    proc = _spawn_launcher()
    try:
        env, paths = _base(tmp_path, proc, task_status="in_progress", ceiling=0)
        before = _snapshot(paths)

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert "DETACH_CANDIDATE" in result.stdout
        assert "reason=lifetime_projection" in result.stdout
        assert "elapsed age is diagnostic evidence only" in result.stdout
        assert proc.poll() is None
        assert _snapshot(paths) == before
    finally:
        _cleanup(proc)


def test_live_launcher_with_live_task_is_only_observed(tmp_path: Path) -> None:
    proc = _spawn_launcher()
    try:
        env, paths = _base(tmp_path, proc, task_status="in_progress")
        before = _snapshot(paths)

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert "PROCESS_OBSERVED" in result.stdout
        assert "DETACH_CANDIDATE" not in result.stdout
        assert proc.poll() is None
        assert _snapshot(paths) == before
    finally:
        _cleanup(proc)


def test_detach_projection_can_be_disabled(tmp_path: Path) -> None:
    proc = _spawn_launcher()
    try:
        env, paths = _base(tmp_path, proc, task_status=None, ceiling=0)
        env["HAPAX_SUPERVISOR_REAP_OFF"] = "1"
        before = _snapshot(paths)

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert "DETACH_CANDIDATE" not in result.stdout
        assert proc.poll() is None
        assert _snapshot(paths) == before
    finally:
        _cleanup(proc)


def test_supervisor_contains_no_process_termination_primitive() -> None:
    code = SUPERVISOR.read_text(encoding="utf-8")
    assert "kill -TERM" not in code
    assert "kill --" not in code
    assert "killpg" not in code
    assert "os.kill" not in code
    assert "reap_launcher" not in code


def test_lane_reaper_has_no_mutable_source_fallback_or_effect_entrypoint() -> None:
    code = REAPER.read_text(encoding="utf-8")

    assert "$HOME/projects/hapax-council" not in code
    assert "${HOME}/projects/hapax-council" not in code
    for forbidden in (
        "tmux kill-",
        "kill -",
        "systemctl",
        "hapax-alert",
        "hapax-p0-incident-intake",
        "cc-close",
        "cc-claim",
        "git worktree remove",
        "--recompute",
        "rm -f",
    ):
        assert forbidden not in code


def test_supervisor_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
