import fcntl
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-headless"
VISIBLE = REPO_ROOT / "scripts" / "hapax-claude"


def _write_parent_envelope(path: Path, task_id: str = "task-x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "parent_route_resource_envelope_schema": 1,
        "envelope_id": "parent-route-claude-test",
        "issued_at": "2026-06-30T05:00:00+00:00",
        "stale_after": "999999h",
        "task_id": task_id,
        "lane": "beta",
        "platform": "claude",
        "mode": "headless",
        "profile": "full",
        "route_id": "claude.headless.full",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "/vault/spec.md",
        "route_decision_id": "decision-claude-test",
        "route_decision_receipt_ref": "route-decision-receipt:test",
        "capability_profile": "claude.headless.full",
        "resource_budget": {
            "quota_state": "ok",
            "quota_receipt_refs": ["quota-receipt:test"],
            "resource_receipt_refs": ["resource-receipt:test"],
            "quota_freshness_green": True,
            "resource_freshness_green": True,
            "stale_after": "999999h",
        },
        "stop_conditions": ["parent_task_closed", "budget_or_resource_receipt_stale"],
        "receipt_chain": [
            "route-decision-receipt:test",
            "route-decision:decision-claude-test",
            "resource-receipt:test",
            "quota-receipt:test",
        ],
        "child_receipts": [],
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _wire_child_receipt_helper(workdir: Path) -> None:
    (workdir / "scripts").mkdir(parents=True, exist_ok=True)
    _stub_bin(
        workdir / "scripts",
        "hapax-child-spawn-receipt",
        f'exec "{REPO_ROOT / "scripts" / "hapax-child-spawn-receipt"}" "$@"\n',
    )


def _write_claude_settings_with_agent_gate(home: Path) -> Path:
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Agent|Task",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(
                                        REPO_ROOT / "hooks" / "scripts" / "conductor-pre.sh"
                                    ),
                                }
                            ],
                        }
                    ]
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return settings_path


def _stub_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def _headless_env(home: Path, bin_dir: Path, pipe_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    # Host-independence: a remotely-dispatched test runner (appendix lanes)
    # carries its OWN dispatch/identity env; scrub it so the launcher under
    # test sees only what each test sets explicitly.
    for var in (
        "HAPAX_DISPATCH_HOST",
        "HAPAX_DISPATCH_HOST_FALLBACK",
        "HAPAX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_AGENT_ROLE",
        "HAPAX_AGENT_NAME",
        "CLAUDE_ROLE",
        "HAPAX_WORKTREE_ROLE",
        "HAPAX_METHODOLOGY_DISPATCH_TASK",
        "HAPAX_PARENT_ROUTE_ENVELOPE",
        "HAPAX_REQUIRE_PARENT_ROUTE_ENVELOPE",
        "HAPAX_CHILD_SPAWN_ENVELOPE",
        "HAPAX_CHILD_RECEIPT_REF",
        "HAPAX_CHILD_RECEIPT_ID",
        "HAPAX_CLAUDE_BIN",
        "HAPAX_CLAUDE_BIN_PATH",
        "HAPAX_CLAUDE_SETTINGS_JSON",
        "NPM_CONFIG_PREFIX",
    ):
        env.pop(var, None)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    # Don't re-exec into a real systemd scope from the test sandbox.
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(pipe_dir)
    # Fast loop so a respawn regression spins (and is caught by the timeout)
    # rather than waiting 30s between iterations.
    env["HAPAX_CLAUDE_HEADLESS_RESTART_BACKOFF_SECONDS"] = "0"
    return env


def test_headless_defaults_to_disabled_without_governed_enable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "/usr/bin:/bin"
    env.pop("HAPAX_CLAUDE_HEADLESS_ALLOW", None)
    env.pop("HAPAX_CLAUDE_HEADLESS_ENABLE_FILE", None)

    result = subprocess.run(
        [str(SCRIPT), "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 77
    assert "disabled until governed enable exists" in result.stderr


def test_headless_source_prepends_workdir_scripts_to_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'PATH="$WORKDIR/scripts:$PATH"' in text, (
        "headless wrapper must prepend $WORKDIR/scripts to PATH"
    )


def test_headless_source_contains_no_generic_work_pool_prompt() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "claim the next" not in text
    assert "highest-WSJF" not in text
    assert "Never stop" not in text
    assert "governed initial message required" in text
    assert "refusing mutating launch without --task" in text
    assert "Do not create, select, or claim other work from the task pool." in text
    assert "--task TASK_ID" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text


def test_headless_source_supports_governed_model_profile_env() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'MODEL="${HAPAX_CLAUDE_MODEL:-}"' in text
    assert 'CLAUDE_ARGS+=(--model "$MODEL")' in text


def test_headless_uses_npm_global_claude_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_args = tmp_path / "claude-args.txt"
    npm_bin = home / ".npm-global" / "bin"
    npm_bin.mkdir(parents=True)
    _stub_bin(
        npm_bin,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claude_args.exists()


def test_headless_honors_explicit_claude_bin_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_args = tmp_path / "claude-args.txt"
    explicit_bin = tmp_path / "explicit" / "claude"
    explicit_bin.parent.mkdir()
    _stub_bin(
        explicit_bin.parent,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_BIN"] = str(explicit_bin)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claude_args.exists()


def test_headless_rejects_invalid_explicit_claude_bin_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fallback_marker = tmp_path / "fallback-used"
    _stub_bin(bin_dir, "claude", f"touch {fallback_marker}\nexit 0\n")
    explicit_bin = tmp_path / "explicit" / "claude"
    explicit_bin.parent.mkdir()
    explicit_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    explicit_bin.chmod(0o644)
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_BIN"] = str(explicit_bin)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 4
    assert "configured Claude binary is not executable" in result.stderr
    assert not fallback_marker.exists()


def test_headless_refuses_required_parent_route_without_envelope(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _wire_child_receipt_helper(workdir)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_marker = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_marker}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_REQUIRE_PARENT_ROUTE_ENVELOPE"] = "1"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 18
    assert "missing_parent_route_resource_receipt" in result.stderr
    assert "next action:" in result.stderr
    assert not claude_marker.exists()


def test_headless_records_child_spawn_receipt_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _wire_child_receipt_helper(workdir)
    _write_claude_settings_with_agent_gate(home)
    parent_path = _write_parent_envelope(tmp_path / "parent.json")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env_file = tmp_path / "claude-env.txt"
    _stub_bin(
        bin_dir,
        "claude",
        f"""
        printf 'parent=%s\\n' "${{HAPAX_PARENT_ROUTE_ENVELOPE:-}}" > {env_file}
        printf 'child=%s\\n' "${{HAPAX_CHILD_SPAWN_ENVELOPE:-}}" >> {env_file}
        printf 'receipt_ref=%s\\n' "${{HAPAX_CHILD_RECEIPT_REF:-}}" >> {env_file}
        printf 'receipt_id=%s\\n' "${{HAPAX_CHILD_RECEIPT_ID:-}}" >> {env_file}
        : > {claim_file}
        exit 0
        """,
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_PARENT_ROUTE_ENVELOPE"] = str(parent_path)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    launched_env = env_file.read_text(encoding="utf-8")
    assert f"parent={parent_path}" in launched_env
    assert "child=" in launched_env and "child-spawn-" in launched_env
    assert "receipt_ref=child-spawn-envelope:" in launched_env
    assert "receipt_id=child-receipt-" in launched_env
    parent_payload = json.loads(parent_path.read_text(encoding="utf-8"))
    assert parent_payload["child_receipts"][0]["child_id"].startswith("claude-headless:beta:")


def test_headless_refuses_parent_route_without_agent_conductor_gate(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _wire_child_receipt_helper(workdir)
    parent_path = _write_parent_envelope(tmp_path / "parent.json")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_marker = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f": > {claude_marker}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_PARENT_ROUTE_ENVELOPE"] = str(parent_path)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 18
    assert "Agent|Task PreToolUse conductor-pre.sh gate" in result.stderr
    assert "next action:" in result.stderr
    assert not claude_marker.exists()
    parent_payload = json.loads(parent_path.read_text(encoding="utf-8"))
    assert parent_payload["child_receipts"] == []


def test_appendix_hop_passes_remote_args_without_shell_interpolation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exploit = tmp_path / "logos-url-shell-injection"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "ssh",
        """remote_cmd="${@: -1}"
case "$remote_cmd" in
  HAPAX_REMOTE_PAYLOAD=*)
    echo 'fish: Expected a variable name after this $' >&2
    exit 127
    ;;
esac
if [[ "$remote_cmd" == *"\\$'"* ]]; then
  echo 'fish: Expected a variable name after this $' >&2
  exit 127
fi
exec bash -c "$remote_cmd"
""",
    )
    _stub_bin(
        bin_dir,
        "gh",
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\nexit 1\n',
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["HAPAX_DISPATCH_LOGOS_URL"] = f"http://podium.invalid/api; touch {exploit}"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not exploit.exists()
    args = claude_args.read_text(encoding="utf-8").splitlines()
    assert args[:5] == [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
    ]


def test_appendix_short_alias_is_local_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_called = tmp_path / "ssh-called"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _stub_bin(
        bin_dir,
        "ssh",
        f": > {ssh_called}\necho 'ssh should not be called for local appendix alias' >&2\nexit 99\n",
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert claude_args.exists()


def test_appendix_local_ip_skips_ssh_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_called = tmp_path / "ssh-called"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  -I) printf '%s\n' '192.168.68.50 10.0.0.50' ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _stub_bin(
        bin_dir,
        "ssh",
        f": > {ssh_called}\necho 'ssh should not be called for local appendix IP' >&2\nexit 99\n",
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "192.168.68.50"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert claude_args.exists()


def test_visible_claude_launcher_requires_task_or_readonly() -> None:
    text = VISIBLE.read_text(encoding="utf-8")

    assert "--task TASK_ID|--readonly" in text
    assert "refusing mutating visible lane without governed task binding" in text
    assert "hapax-methodology-dispatch" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text
    assert 'CLAUDE_TASK="$CLAIMED_TASK"' in text
    assert "Agent|Task PreToolUse conductor-pre.sh gate" in text


def test_headless_refuses_without_task_or_existing_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    claude.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    # Sandbox the launcher lock/pipe dir so a live beta lane on the host doesn't
    # trip the duplicate-launcher guard (exit 16) before the no-task guard (15).
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(tmp_path / "pipe")
    env.pop("HAPAX_METHODOLOGY_DISPATCH_TASK", None)
    env.pop("HAPAX_PARENT_ROUTE_ENVELOPE", None)
    env.pop("HAPAX_REQUIRE_PARENT_ROUTE_ENVELOPE", None)
    env.pop("HAPAX_CHILD_SPAWN_ENVELOPE", None)
    env.pop("HAPAX_CHILD_RECEIPT_REF", None)
    env.pop("HAPAX_CHILD_RECEIPT_ID", None)

    result = subprocess.run(
        [str(SCRIPT), "beta", "Task: fake\nAuthorityCase: fake\nParent spec: fake"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 15
    assert "without --task" in result.stderr


# ---------------------------------------------------------------------------
# Dispatch idempotency (bug #3): refuse a second live launcher for a lane.
# The reboot storm + naive re-dispatch + the supervisor firing during a
# restart-backoff window otherwise stack zombie wrappers that fight over the
# lane-keyed $ROLE.stdin / $ROLE.pid and re-inject restart prompts forever.
# ---------------------------------------------------------------------------


def test_headless_source_has_launcher_idempotency_guard() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "flock -n" in text
    assert "refusing duplicate launcher" in text


def test_headless_refuses_duplicate_launcher_for_live_lane(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    # Simulate a live incumbent wrapper by holding the lane launcher lock.
    lock_path = pipe_dir / "beta.launcher.lock"
    lock_fd = open(lock_path, "w")  # noqa: SIM115 — held for the subprocess lifetime
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    assert result.returncode == 16, result.stderr
    assert "refusing duplicate launcher" in result.stderr


def test_headless_acquires_launcher_lock_when_lane_free(tmp_path: Path) -> None:
    """When no incumbent holds the lock, the wrapper proceeds (and self-heals)."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # claude exits immediately and clears the claim (simulating a closed task),
    # so the lane is free and the loop tears down cleanly on the first pass.
    _stub_bin(
        bin_dir,
        "claude",
        f"echo x >> {counter}\n: > {cache / 'cc-active-task-beta'}\nexit 0\n",
    )
    env = _headless_env(home, bin_dir, pipe_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert counter.read_text().count("x") == 1


# ---------------------------------------------------------------------------
# Merge-aware teardown (bug #2): the respawn loop must stop once its task is
# closed (claim cleared / note left active/ / terminal status) or its PR merged
# — not re-inject a generic restart prompt forever.
# ---------------------------------------------------------------------------


def test_headless_source_has_merge_aware_teardown() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "task_is_terminal" in text
    assert "stopping respawn loop" in text


def test_headless_stops_respawning_when_claim_cleared(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Simulate cc-close: the lane finishes, clearing its claim file, then exits.
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1  # exactly one claude run, no zombie


def test_headless_stops_respawning_when_note_status_terminal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")  # claim stays
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text("---\ntask_id: task-x\nstatus: done\n---\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\nexit 0\n")  # leaves claim
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1


def test_headless_stops_respawning_when_pr_merged(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text(
        "---\ntask_id: task-x\nstatus: pr_open\npr: 555\n---\n"
    )
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\nexit 0\n")
    # gh stub reports the linked PR as merged.
    _stub_bin(bin_dir, "gh", "echo MERGED\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1


# ---------------------------------------------------------------------------
# Out-of-band self-reap (the zombie-launcher bug): the launcher holds the FIFO
# write-end open (exec 3<>), so a persistent stream-json claude NEVER sees EOF,
# `wait` never returns, and the post-turn task_is_terminal teardown is dead code.
# The fix is an out-of-band watchdog that polls task terminality WHILE claude is
# alive and SIGTERMs the child when the task closes/merges — independent of EOF.
# ---------------------------------------------------------------------------


def test_headless_source_has_out_of_band_self_reap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "self-reaping" in text
    assert "TERMINAL_POLL" in text or "HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS" in text


def test_headless_self_reaps_terminal_task_while_claude_persists(tmp_path: Path) -> None:
    """The core fix: with a PERSISTENT claude (never exits → `wait` would block
    forever), the launcher must still tear down when the task goes terminal,
    driven by the out-of-band poll rather than the (unreachable) EOF path.

    If the watchdog were absent the launcher would hang on `wait` for the full
    `sleep 600` and the 20s subprocess timeout would fail the test.
    """
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")  # claim stays
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    # Terminal status from the start: the first out-of-band poll detects it.
    (vault / "active" / "task-x-test.md").write_text("---\ntask_id: task-x\nstatus: done\n---\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # claude that NEVER exits on its own (the production behavior the bug needs):
    # it must be SIGTERM'd by the out-of-band watchdog.
    _stub_bin(bin_dir, "claude", "exec sleep 600\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.3"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "self-reaping" in result.stdout
    assert "stopping respawn loop" in result.stdout


def test_headless_self_reap_keeps_persistent_claude_alive_while_task_live(tmp_path: Path) -> None:
    """The watchdog must NOT reap a persistent claude while the task is still
    live — it only acts once the task is terminal. With a live task the launcher
    blocks (claude never exits), so we assert it TIMES OUT (no premature reap)."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text(
        "---\ntask_id: task-x\nstatus: in_progress\n---\n"
    )
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exec sleep 600\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.3"

    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=4,
        )
    # Reap the still-running launcher + its sleep child (own session) so the
    # sandbox doesn't leak processes.
    subprocess.run(["pkill", "-TERM", "-f", "sleep 600"], check=False)


# ---------------------------------------------------------------------------
# Stale-lock handling on startup: a SIGKILL'd launcher skips its EXIT trap,
# stranding the pidfile. The OFD flock still releases on death, so a free lock
# is reacquired normally; but a genuinely-held lock must never be stolen just
# because the recorded pid looks stale.
# ---------------------------------------------------------------------------


def test_headless_source_has_stale_lock_handling() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "stale" in text.lower()
    # On flock failure the incumbent's liveness is verified before refusing.
    assert "kill -0" in text


def test_headless_refuses_when_lock_held_even_with_stale_pidfile(tmp_path: Path) -> None:
    """A live holder of the lock must still be refused (no false steal) even when
    the recorded launcher pid is dead/stale."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    # A dead/stale pid in the pidfile (pid 2^31-1 is never live).
    (pipe_dir / "beta.launcher.pid").write_text("2147483647\n")
    # A LIVE incumbent holds the lock (Python fd held for the subprocess lifetime).
    lock_path = pipe_dir / "beta.launcher.lock"
    lock_fd = open(lock_path, "w")  # noqa: SIM115
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    assert result.returncode == 16, result.stderr
    assert "refusing duplicate launcher" in result.stderr


# ---------------------------------------------------------------------------
# Drift check (AC3): the committed launcher is the authoritative source — the
# incident was the committed launcher REGRESSING below the deployed runtime (a
# 190-line strip that dropped flock + teardown while the deployed copy had the
# 292-line fix). source-activation only ever deploys FROM git, so pinning the
# committed launcher's fix markers (+ a line-count floor) in CI keeps committed
# and deployed from diverging in the dangerous direction. A byte-equality test
# vs the deployed symlink is intentionally NOT used: it false-fails for the whole
# merged-not-yet-deployed window (the pinned release copy lags main).
# ---------------------------------------------------------------------------


def test_committed_launcher_pins_zombie_reap_fix_markers() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    # flock idempotency + named launcher pidfile
    assert "flock -n" in text
    assert "LAUNCHER_PIDFILE" in text
    # merge-aware terminal detection + out-of-band self-reap
    assert "task_is_terminal" in text
    assert "self-reaping" in text
    assert "stopping respawn loop" in text
    # Line-count floor: the regression stripped the launcher to ~190 lines. The
    # full launcher (flock + teardown + out-of-band self-reap) is well over 250.
    assert len(text.splitlines()) >= 250, "launcher appears stripped — regression risk"


# ---------------------------------------------------------------------------
# Session identity through the dispatch boundary (taxonomy-a3-session-identity):
# the launcher mints HAPAX_SESSION_ID per spawn, but before the fix the G2
# remote hop dropped every identity var at the SSH boundary — the appendix
# claude resolved a DIFFERENT session id (CLAUDE_CODE_SESSION_ID), the
# session-keyed claim file existed only podium-side, and the dispatch proof
# witnessed the exec by pid alone. The lane then hit cc-claim exit-4 walls
# (see relay receipts epsilon-claim-rejected.yaml, zeta-claim-rejected.yaml).
# The identity thread must survive the hop: payload env -> remote exec ->
# marker + claim materialization on the exec host -> session-stamped proof.
# ---------------------------------------------------------------------------


def test_headless_mint_fallback_is_never_pid_derived() -> None:
    """Claim-by-pid unrepresentable: the retired `<role>-$$` fallback minted
    pid-shaped session ids that cc-claim now refuses to key."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"$ROLE" "$$"' not in text, "launcher session-id fallback mints pid-shaped ids"


def test_headless_preamble_carries_session_identity() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Session identity: role=$ROLE session_id=$SESSION_UUID" in text


def test_appendix_hop_threads_session_identity_end_to_end(tmp_path: Path) -> None:
    """E2E canary: fake ssh executes the remote command locally (same HOME),
    so the assertions cover the full chain — launcher mint -> payload env ->
    remote exec env -> exec-host marker/claim materialization -> proof."""
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_env = tmp_path / "claude-env.txt"
    # Simulate the real SSH env boundary: the remote shell never inherits the
    # launcher's exports, so identity can ONLY arrive via the exec payload.
    _stub_bin(
        bin_dir,
        "ssh",
        'remote_cmd="${@: -1}"\n'
        "exec env -u HAPAX_SESSION_ID -u HAPAX_AGENT_INTERFACE -u HAPAX_AGENT_NAME"
        " -u HAPAX_AGENT_ROLE -u CLAUDE_ROLE -u HAPAX_WORKTREE_ROLE"
        ' -u HAPAX_METHODOLOGY_DISPATCH_TASK bash -c "$remote_cmd"\n',
    )
    _stub_bin(
        bin_dir,
        "gh",
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\nexit 1\n',
    )
    # The "remote" claude dumps its env, then clears the legacy claim so the
    # respawn loop tears down after one pass.
    _stub_bin(bin_dir, "claude", f"env > {claude_env}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr

    # One session id, minted by the launcher, recorded in the role marker.
    markers = sorted(cache.glob("session-role-*"))
    assert len(markers) == 1, f"expected exactly one session marker, got {markers}"
    sid = markers[0].name.removeprefix("session-role-")
    assert markers[0].read_text().strip() == "beta"

    # The exec-side claude carries the SAME identity the launcher minted.
    claude_vars = dict(
        line.split("=", 1) for line in claude_env.read_text().splitlines() if "=" in line
    )
    assert claude_vars.get("HAPAX_SESSION_ID") == sid
    assert claude_vars.get("HAPAX_AGENT_ROLE") == "beta"
    assert claude_vars.get("CLAUDE_ROLE") == "beta"
    assert claude_vars.get("HAPAX_METHODOLOGY_DISPATCH_TASK") == "task-x"

    # The session-keyed claim materialized on the exec host (cc-claim was
    # skipped — the pre-seeded legacy claim matched — so only the remote
    # materialization path can have written it), single-line format.
    keyed = cache / f"cc-active-task-beta-{sid}"
    assert keyed.read_text(encoding="utf-8") == "task-x\n"

    # The dispatch proof witnesses the session, not just the pid.
    proofs = sorted((cache / "orchestration" / "dispatch-host-proofs").glob("*.json"))
    assert proofs, "remote exec must write a dispatch proof"
    proof = json.loads(proofs[-1].read_text(encoding="utf-8"))
    assert proof["session_id"] == sid
    assert proof["role"] == "beta"
    assert proof["task_id"] == "task-x"
    assert proof["claim_materialized"] is True
