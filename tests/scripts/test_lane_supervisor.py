"""Regression tests for the projection-only lane supervisor."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _base(tmp_path: Path, **overrides: str) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "effect-calls.log"
    vault = home / "vault"
    for path in (
        home / "projects",
        home / ".cache" / "hapax",
        vault / "active",
        tmp_path / "runtime",
        tmp_path / "logs",
        tmp_path / "metrics",
    ):
        path.mkdir(parents=True, exist_ok=True)

    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        if [[ "$1" == "has-session" ]]; then
          target=""
          while [[ $# -gt 0 ]]; do
            if [[ "$1" == "-t" ]]; then target="$2"; shift 2; else shift; fi
          done
          for live in ${TMUX_LIVE:-}; do
            [[ "$live" == "$target" ]] && exit 0
          done
          exit 1
        fi
        exit 0
        """,
    )
    for command in ("hapax-claude", "hapax-claude-headless", "hapax-codex", "hapax-alert"):
        _write_executable(
            bin_dir / command,
            f"""
            #!/usr/bin/env bash
            printf '%s %s\n' "{command}" "$*" >> "{calls}"
            """,
        )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(tmp_path / "runtime"),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(vault),
            "HAPAX_SUPERVISOR_CLAIM_CACHE_DIR": str(home / ".cache" / "hapax"),
            "HAPAX_SUPERVISOR_CLAUDE_LOG_DIR": str(tmp_path / "logs"),
            "HAPAX_SUPERVISOR_METRICS_FILE": str(tmp_path / "metrics" / "supervisor.prom"),
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
        }
    )
    env.update(overrides)
    return env, calls, vault


def _make_worktree(env: dict[str, str], lane: str) -> None:
    (Path(env["HAPAX_SUPERVISOR_WORKTREE_ROOT"]) / f"hapax-council--{lane}").mkdir(
        parents=True, exist_ok=True
    )


def _write_claim(
    env: dict[str, str],
    vault: Path,
    lane: str,
    task_id: str,
    *,
    status: str = "in_progress",
    session_keyed: bool = False,
) -> tuple[Path, Path, Path, Path]:
    note = vault / "active" / f"{task_id}.md"
    note.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "Task {task_id}"
            status: {status}
            assigned_to: {lane}
            pr: null
            claimed_at: 2026-07-12T00:00:00Z
            ---
            # Task
            """
        ),
        encoding="utf-8",
    )
    cache_dir = Path(env["HAPAX_SUPERVISOR_CLAIM_CACHE_DIR"])
    suffix = "-019f0000-0000-7000-8000-000000000001" if session_keyed else ""
    claim = cache_dir / f"cc-active-task-{lane}{suffix}"
    epoch = cache_dir / f"cc-claim-epoch-{lane}{suffix}"
    binding = cache_dir / f"cc-dispatch-binding-{lane}{suffix}.json"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    epoch.write_text(f"1783814400 {task_id}\n", encoding="utf-8")
    binding.write_text('{"binding":"sentinel"}\n', encoding="utf-8")
    return note, claim, epoch, binding


def _snapshot(*paths: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True, timeout=30)


def test_missing_activated_shared_root_fails_without_primary_checkout_fallback(
    tmp_path: Path,
) -> None:
    isolated = tmp_path / "isolated" / "scripts" / "hapax-lane-supervisor"
    isolated.parent.mkdir(parents=True)
    isolated.write_bytes(SUPERVISOR.read_bytes())
    isolated.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")

    result = subprocess.run(
        [str(isolated)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 78
    assert "activated source root unavailable" in result.stderr
    assert "projects/hapax-council" not in isolated.read_text(encoding="utf-8")


def test_dead_claimed_claude_lane_is_reported_without_effects(tmp_path: Path) -> None:
    env, calls, vault = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _make_worktree(env, "delta")
    paths = _write_claim(env, vault, "delta", "live-task")
    before = _snapshot(*paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "RECOVERY_CANDIDATE" in result.stdout
    assert "claim detach HOLD" in result.stdout
    assert _snapshot(*paths) == before
    assert not calls.exists()


def test_dead_unclaimed_lane_holds_for_governed_recovery(tmp_path: Path) -> None:
    env, calls, _vault = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="beta")
    _make_worktree(env, "beta")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "RECOVERY_CANDIDATE" in result.stdout
    assert "standing effect authority absent" in result.stdout
    assert not calls.exists()


def test_dead_codex_lane_is_reported_without_launcher_call(tmp_path: Path) -> None:
    env, calls, vault = _base(tmp_path, HAPAX_SUPERVISOR_CODEX_LANES="cx-gold")
    _make_worktree(env, "cx-gold")
    paths = _write_claim(env, vault, "cx-gold", "codex-task")
    before = _snapshot(*paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "cx-gold (codex): RECOVERY_CANDIDATE" in result.stdout
    assert _snapshot(*paths) == before
    assert not calls.exists()


def test_platform_qualified_codex_owner_is_reserved_for_exact_lane(tmp_path: Path) -> None:
    env, calls, vault = _base(tmp_path, HAPAX_SUPERVISOR_CODEX_LANES="cx-gold")
    _make_worktree(env, "cx-gold")
    paths = _write_claim(env, vault, "cx-gold", "codex-task")
    note = paths[0]
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "assigned_to: cx-gold",
            "assigned_to: codex/cx-gold",
        ),
        encoding="utf-8",
    )
    before = _snapshot(*paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "cx-gold (codex): RECOVERY_CANDIDATE" in result.stdout
    assert "tasks=codex-task" in result.stdout
    assert _snapshot(*paths) == before
    assert not calls.exists()


def test_live_tmux_lane_is_observed_without_recovery_projection(tmp_path: Path) -> None:
    env, calls, vault = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CODEX_LANES="cx-red",
        TMUX_LIVE="hapax-codex-cx-red",
    )
    _make_worktree(env, "cx-red")
    paths = _write_claim(env, vault, "cx-red", "active-task")
    before = _snapshot(*paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "PROCESS_OBSERVED" in result.stdout
    assert "RECOVERY_CANDIDATE" not in result.stdout
    assert _snapshot(*paths) == before
    assert not calls.exists()


def test_session_keyed_claim_is_reported_but_never_cleared(tmp_path: Path) -> None:
    env, _calls, vault = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="theta")
    _make_worktree(env, "theta")
    paths = _write_claim(env, vault, "theta", "session-task", session_keyed=True)
    before = _snapshot(*paths)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "marker_claims=session-task" in result.stdout
    assert _snapshot(*paths) == before


def test_malformed_task_store_fails_closed_without_mutation(tmp_path: Path) -> None:
    env, calls, vault = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="eta")
    _make_worktree(env, "eta")
    malformed = vault / "active" / "broken.md"
    malformed.write_text("---\ntask_id: broken\nstatus: [\n---\n", encoding="utf-8")
    before = malformed.read_bytes()

    result = _run(env)

    assert result.returncode == 2
    assert "TASK_SSOT_UNKNOWN" in result.stdout
    assert "recovery HOLD: task SSOT unreadable" in result.stdout
    assert malformed.read_bytes() == before
    assert not calls.exists()


def test_missing_worktree_is_a_configuration_candidate_only(tmp_path: Path) -> None:
    env, calls, _vault = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="gamma")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert "CONFIGURATION_CANDIDATE reason=missing_worktree" in result.stdout
    assert "action=HOLD" in result.stdout
    assert not calls.exists()


def test_metrics_pin_zero_effects(tmp_path: Path) -> None:
    env, _calls, _vault = _base(tmp_path)

    result = _run(env)

    assert result.returncode == 0, result.stderr
    metrics = Path(env["HAPAX_SUPERVISOR_METRICS_FILE"]).read_text(encoding="utf-8")
    assert "hapax_lane_supervisor_effects 0" in metrics


def test_supervisor_source_has_no_legacy_effect_paths() -> None:
    text = SUPERVISOR.read_text(encoding="utf-8")
    for forbidden in (
        "reoffer_task",
        "fifo_nudge",
        "respawn_sync",
        "reap_launcher",
        "kill -TERM",
        "setsid ",
        "hapax-p0-incident-intake",
        "hapax-alert",
        "status: offered",
        "assigned_to: unassigned",
    ):
        assert forbidden not in text
    assert "effects 0" in text


def test_supervisor_shell_syntax_and_version() -> None:
    syntax = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    version = subprocess.run([str(SUPERVISOR), "--version"], capture_output=True, text=True)
    assert version.returncode == 0
    assert "v3 (projection-only)" in version.stdout
