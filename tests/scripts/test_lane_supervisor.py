"""Tests for the FM-11 lane supervisor (dead lanes always auto-restart).

The supervisor guarantees lane-process liveness *regardless of task presence*
(operator standing mandate: dead lanes must ALWAYS auto-restart). It is a clean
split from dispatch: the supervisor guarantees the process exists; the launcher
(dispatcher) decides what it does — so respawning a quota-walled or task-less
lane into idle-await is correct, not spam.

Coverage spans all runtimes: claude (greek, headless pidfile model), codex
(cx-*, tmux model), and antigrav (tmux model).
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _write_recorder(path: Path, log: Path) -> None:
    """A fake launcher that records its argv to ``log`` and exits 0."""
    _write_executable(
        path,
        f"""
        #!/usr/bin/env bash
        printf '%s\\n' "$*" >> "{log}"
        """,
    )


def _write_fake_tmux(bin_dir: Path) -> None:
    """Fake tmux: ``has-session`` succeeds only for sessions in $TMUX_LIVE."""
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        cmd="$1"; shift || true
        case "$cmd" in
          has-session)
            target=""
            while [ $# -gt 0 ]; do
              case "$1" in
                -t) target="$2"; shift 2 ;;
                *) shift ;;
              esac
            done
            for live in ${TMUX_LIVE:-}; do
              [ "$live" = "$target" ] && exit 0
            done
            exit 1
            ;;
          *) exit 0 ;;
        esac
        """,
    )


def _base(tmp_path: Path, **overrides: str) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    calls = tmp_path / "calls"
    for d in (home, bin_dir, state_dir, runtime_dir, calls):
        d.mkdir(parents=True, exist_ok=True)
    (home / "projects").mkdir(parents=True, exist_ok=True)

    _write_fake_tmux(bin_dir)
    _write_recorder(bin_dir / "hapax-claude-headless", calls / "claude-headless.txt")
    _write_recorder(bin_dir / "hapax-claude", calls / "claude.txt")
    _write_recorder(bin_dir / "hapax-codex", calls / "codex.txt")
    _write_recorder(bin_dir / "hapax-antigrav", calls / "antigrav.txt")

    env = os.environ.copy()
    # Strip any inherited lane identity so it cannot leak into the subprocess.
    for leaky in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "TMUX_LIVE"):
        env.pop(leaky, None)
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_SUPERVISOR_STATE_DIR": str(state_dir),
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(runtime_dir),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_RESTART_COOLDOWN_S": "0",
            "HAPAX_CLAUDE_HEADLESS_BIN": str(bin_dir / "hapax-claude-headless"),
            "HAPAX_CLAUDE_BIN": str(bin_dir / "hapax-claude"),
            "HAPAX_CODEX_BIN": str(bin_dir / "hapax-codex"),
            "HAPAX_ANTIGRAV_BIN": str(bin_dir / "hapax-antigrav"),
        }
    )
    env.update(overrides)
    return env, calls


def _make_worktree(env: dict[str, str], lane: str) -> Path:
    wt = Path(env["HAPAX_SUPERVISOR_WORKTREE_ROOT"]) / f"hapax-council--{lane}"
    wt.mkdir(parents=True, exist_ok=True)
    return wt


def _write_claim(env: dict[str, str], lane: str, task_id: str, *, status: str = "claimed") -> None:
    claim_dir = Path(env["HOME"]) / ".cache" / "hapax"
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / f"cc-active-task-{lane}").write_text(f"{task_id}\n", encoding="utf-8")
    active = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active"
    active.mkdir(parents=True, exist_ok=True)
    (active / f"{task_id}.md").write_text(
        f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {lane}\n"
        f'title: "Resume me {task_id}"\n---\n# task\n',
        encoding="utf-8",
    )


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True)


def _reads(calls: Path, name: str) -> str:
    p = calls / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _wait_reads(calls: Path, name: str, *, timeout: float = 8.0) -> str:
    """Poll a recorder file until non-empty. The headless launcher is spawned
    in the background (it supervises forever), so its recorder write is async.
    """
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        text = _reads(calls, name)
        if text.strip():
            return text
        time.sleep(0.05)
    return text


# ─── core fix: dead lanes ALWAYS respawn, even with no task ────────────────────


def test_supervisor_respawns_dead_claude_lane_with_no_task(tmp_path: Path) -> None:
    """The FM-11 fix: a dead lane with NO active task is respawned (idle-await),
    not left dead. Claude's headless launcher is default-deny on task-less
    launch, so the supervisor brings it up read-only to await governed dispatch.
    """
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _make_worktree(env, "delta")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    claude = _reads(calls, "claude.txt")
    assert "--role delta" in claude
    assert "--readonly" in claude
    # It respawns rather than leaving the lane dead (the old watchdog logged
    # "DEAD with no active task — not restarting"; the supervisor must not).
    assert "not restarting" not in result.stdout
    assert "respawning read-only" in result.stdout


def test_supervisor_appendix_only_suppresses_dead_claude_lane_with_no_task(
    tmp_path: Path,
) -> None:
    """Appendix/thin-client mode must not recreate unclaimed local dev lanes."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_LOCAL_DEV_MAINTENANCE_MODE="appendix-only",
    )
    _make_worktree(env, "delta")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude.txt") == ""
    assert "appendix-only local-dev maintenance" in result.stdout
    assert "suppresses idle-await respawn" in result.stdout


def test_supervisor_respawns_dead_claude_lane_with_claimed_task(tmp_path: Path) -> None:
    """A dead claude lane WITH a claimed task resumes via the headless launcher."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _make_worktree(env, "delta")
    _write_claim(env, "delta", "reform-fix-lane-supervisor-20260531")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    headless = _wait_reads(calls, "claude-headless.txt")
    assert "delta" in headless
    assert "reform-fix-lane-supervisor-20260531" in headless
    # task-bound respawn uses headless (mutating), not the read-only path
    assert "--readonly" not in _reads(calls, "claude.txt")


def test_supervisor_appendix_only_preserves_claimed_task_resume(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_LOCAL_DEV_MAINTENANCE_MODE="appendix-only",
    )
    _make_worktree(env, "delta")
    _write_claim(env, "delta", "appendix-active-task")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    headless = _wait_reads(calls, "claude-headless.txt")
    assert "delta" in headless
    assert "appendix-active-task" in headless
    assert _reads(calls, "claude.txt") == ""


def test_supervisor_skips_live_claude_lane(tmp_path: Path) -> None:
    """A claude lane whose headless pidfile points at a live process is alive."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _make_worktree(env, "delta")
    pid_file = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "delta.pid"
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude.txt") == ""
    assert _reads(calls, "claude-headless.txt") == ""


def test_supervisor_skips_live_claude_lane_via_tmux(tmp_path: Path) -> None:
    """A claude lane with a live tmux session counts as alive (no pidfile)."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        TMUX_LIVE="hapax-claude-delta",
    )
    _make_worktree(env, "delta")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude.txt") == ""
    assert _reads(calls, "claude-headless.txt") == ""


# ─── cx-*/antigrav coverage (criterion: not greek-only) ────────────────────────


def test_supervisor_respawns_dead_codex_lane(tmp_path: Path) -> None:
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CODEX_LANES="cx-amber")
    _make_worktree(env, "cx-amber")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    codex = _reads(calls, "codex.txt")
    assert "--session cx-amber" in codex
    assert "--no-claim" in codex


def test_supervisor_appendix_only_suppresses_unclaimed_codex_lane(
    tmp_path: Path,
) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CODEX_LANES="cx-amber",
        HAPAX_LOCAL_DEV_MAINTENANCE_MODE="appendix-only",
    )
    _make_worktree(env, "cx-amber")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "codex.txt") == ""
    assert "cx-amber (codex): DEAD with no active task" in result.stdout


def test_supervisor_skips_live_codex_lane(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CODEX_LANES="cx-amber",
        TMUX_LIVE="hapax-codex-cx-amber",
    )
    _make_worktree(env, "cx-amber")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "codex.txt") == ""


def test_supervisor_respawns_dead_antigrav_lane(tmp_path: Path) -> None:
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_ANTIGRAV_LANES="antigrav")
    _make_worktree(env, "antigrav")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    antigrav = _reads(calls, "antigrav.txt")
    assert "--session antigrav" in antigrav


# ─── guardrails: cooldown, worktree presence, dry-run, burst ───────────────────


def test_supervisor_skips_lane_without_worktree(tmp_path: Path) -> None:
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    # No worktree created.

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude.txt") == ""


def test_supervisor_respects_restart_cooldown(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_RESTART_COOLDOWN_S="3600",
    )
    _make_worktree(env, "delta")
    # First pass respawns.
    _run(env)
    first = _reads(calls, "claude.txt")
    assert "--role delta" in first
    # Second pass within cooldown must NOT respawn again.
    _run(env)
    assert _reads(calls, "claude.txt") == first


def test_supervisor_dry_run_does_not_launch(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_DRY_RUN="1",
    )
    _make_worktree(env, "delta")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude.txt") == ""
    assert "delta" in result.stdout  # still reports what it WOULD do


def test_supervisor_burst_limit_backs_off(tmp_path: Path) -> None:
    """StartLimit semantics: after too many restarts in the window, back off."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_RESTART_COOLDOWN_S="0",
        HAPAX_SUPERVISOR_BURST_LIMIT="2",
        HAPAX_SUPERVISOR_BURST_WINDOW_S="3600",
    )
    _make_worktree(env, "delta")

    for _ in range(4):
        _run(env)

    launches = [ln for ln in _reads(calls, "claude.txt").splitlines() if ln.strip()]
    assert len(launches) == 2  # capped at burst limit


def test_supervisor_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
