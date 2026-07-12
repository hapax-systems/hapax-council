"""Stale-output projections must never resume or reoffer a lane."""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def _base(
    tmp_path: Path, *, status: str = "in_progress", output_age: int = 3600, **overrides: str
) -> tuple[dict[str, str], tuple[Path, ...], Path]:
    home = tmp_path / "home"
    vault = home / "vault" / "active"
    cache = home / ".cache" / "hapax"
    runtime = tmp_path / "runtime"
    logs = tmp_path / "logs" / "delta"
    worktree = home / "projects" / "hapax-council--delta"
    for path in (vault, cache, runtime, logs, worktree, tmp_path / "bin"):
        path.mkdir(parents=True, exist_ok=True)

    task = "stale-task"
    note = vault / f"{task}.md"
    note.write_text(
        textwrap.dedent(
            f"""\
            ---
            task_id: {task}
            title: "Stale task"
            status: {status}
            assigned_to: delta
            pr: null
            claimed_at: 2026-07-12T00:00:00Z
            ---
            # task
            """
        ),
        encoding="utf-8",
    )
    claim = cache / "cc-active-task-delta"
    epoch = cache / "cc-claim-epoch-delta"
    binding = cache / "cc-dispatch-binding-delta.json"
    claim.write_text(f"{task}\n", encoding="utf-8")
    epoch.write_text(f"1783814400 {task}\n", encoding="utf-8")
    binding.write_text('{"binding":"sentinel"}\n', encoding="utf-8")
    (runtime / "delta.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    output = logs / "output.jsonl"
    output.write_text('{"event":"old"}\n', encoding="utf-8")
    old = time.time() - output_age
    os.utime(output, (old, old))

    calls = tmp_path / "effect-calls.log"
    launcher = tmp_path / "bin" / "hapax-claude-headless"
    launcher.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "{calls}"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    tmux = tmp_path / "bin" / "tmux"
    tmux.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    tmux.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{tmp_path / 'bin'}:{env['PATH']}",
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(runtime),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAIM_CACHE_DIR": str(cache),
            "HAPAX_SUPERVISOR_CLAUDE_LOG_DIR": str(tmp_path / "logs"),
            "HAPAX_SUPERVISOR_METRICS_FILE": str(tmp_path / "supervisor.prom"),
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "delta",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            "HAPAX_SUPERVISOR_STALL_T": "900",
            "HAPAX_CLAUDE_HEADLESS_BIN": str(launcher),
        }
    )
    env.update(overrides)
    return env, (note, claim, epoch, binding), calls


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True, timeout=30)


def _snapshot(paths: tuple[Path, ...]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def test_stale_output_is_reported_without_resume_or_ownership_mutation(tmp_path: Path) -> None:
    env, paths, calls = _base(tmp_path)
    before = _snapshot(paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "STALL_CANDIDATE" in result.stdout
    assert "action=HOLD" in result.stdout
    assert "no resume, prompt injection, task rewrite, or claim cleanup" in result.stdout
    assert _snapshot(paths) == before
    assert not calls.exists()


def test_exhaustion_state_cannot_reoffer_stale_task(tmp_path: Path) -> None:
    env, paths, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_RESUME_MAX_ATTEMPTS="0",
        HAPAX_SUPERVISOR_RESUME_WINDOW_S="1",
    )
    before = _snapshot(paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "STALL_CANDIDATE" in result.stdout
    assert _snapshot(paths) == before
    assert "status: in_progress" in paths[0].read_text(encoding="utf-8")
    assert "assigned_to: delta" in paths[0].read_text(encoding="utf-8")
    assert not calls.exists()


def test_recent_output_is_observed_without_stall_candidate(tmp_path: Path) -> None:
    env, paths, _calls = _base(tmp_path, output_age=10)
    before = _snapshot(paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "PROCESS_OBSERVED" in result.stdout
    assert "STALL_CANDIDATE" not in result.stdout
    assert _snapshot(paths) == before


def test_non_build_status_is_not_stall_candidate(tmp_path: Path) -> None:
    env, paths, _calls = _base(tmp_path, status="pr_open")
    before = _snapshot(paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "STALL_CANDIDATE" not in result.stdout
    assert _snapshot(paths) == before


def test_progress_projection_can_be_disabled(tmp_path: Path) -> None:
    env, paths, _calls = _base(tmp_path, HAPAX_SUPERVISOR_PROGRESS_OFF="1")
    before = _snapshot(paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "STALL_CANDIDATE" not in result.stdout
    assert _snapshot(paths) == before


def test_stall_metrics_are_projection_only(tmp_path: Path) -> None:
    env, _paths, _calls = _base(tmp_path)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    metrics = Path(env["HAPAX_SUPERVISOR_METRICS_FILE"]).read_text(encoding="utf-8")
    assert "hapax_lane_supervisor_stall_candidates 1" in metrics
    assert "hapax_lane_supervisor_effects 0" in metrics


def test_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
