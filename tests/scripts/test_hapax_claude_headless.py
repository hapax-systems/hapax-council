import fcntl
import hashlib
import json
import os
import subprocess
import textwrap
from pathlib import Path

from tests.scripts.launcher_activation_fixture import install_launcher_activation

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-headless"
VISIBLE = REPO_ROOT / "scripts" / "hapax-claude"


def _stub_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def _stub_claim(workdir: Path, log_path: Path) -> Path:
    script_dir = workdir / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    _stub_bin(
        script_dir,
        "cc-claim",
        f"""
        case "${{1:-}}" in
          --dispatch-protocol-version)
            printf '%s\\n' 'hapax-claim-dispatch-v1'
            printf '%s\\n' protocol >> {log_path}
            exit 0
            ;;
          --verify-dispatch-binding)
            printf 'verify %s\\n' "${{2:-}}" >> {log_path}
            exit "${{HAPAX_FAKE_CC_CLAIM_VERIFY_RC:-0}}"
            ;;
        esac
        printf 'claim %s\\n' "$*" >> {log_path}
        mkdir -p "$HOME/.cache/hapax"
        printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_ROLE"
        printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$HAPAX_AGENT_ROLE-$HAPAX_SESSION_ID"
        printf '{{}}\\n' > "$HOME/.cache/hapax/cc-claim-dispatch-$HAPAX_AGENT_ROLE.json"
        printf '{{}}\\n' > "$HOME/.cache/hapax/cc-claim-dispatch-$HAPAX_AGENT_ROLE-$HAPAX_SESSION_ID.json"
        """,
    )
    return script_dir / "cc-claim"


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
        "HAPAX_CLAUDE_BIN",
        "HAPAX_CLAUDE_BIN_PATH",
        "NPM_CONFIG_PREFIX",
    ):
        env.pop(var, None)
    for var in tuple(env):
        if var.startswith("HAPAX_CLAIM_DISPATCH_"):
            env.pop(var)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    # Don't re-exec into a real systemd scope from the test sandbox.
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(pipe_dir)
    # Fast loop so a respawn regression spins (and is caught by the timeout)
    # rather than waiting 30s between iterations.
    env["HAPAX_CLAUDE_HEADLESS_RESTART_BACKOFF_SECONDS"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_RESPAWN"] = "0"
    env.update(install_launcher_activation(home))
    return env


def _add_complete_dispatch_binding(env: dict[str, str]) -> None:
    env.update(
        {
            "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "dispatch-message",
            "HAPAX_CLAIM_DISPATCH_BINDING_HASH": "b" * 64,
            "HAPAX_CLAIM_DISPATCH_PLATFORM": "claude",
            "HAPAX_CLAIM_DISPATCH_MODE": "headless",
            "HAPAX_CLAIM_DISPATCH_PROFILE": "full",
            "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": "CASE-TEST-001",
            "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": "dispatch-test",
            "HAPAX_CLAIM_DISPATCH_TASK_PATH": "/tmp/task-x.md",
            "HAPAX_CLAIM_DISPATCH_TASK_SHA256": "c" * 64,
            "HAPAX_CLAIM_DISPATCH_PARENT_SPEC": "/tmp/parent.md",
            "HAPAX_CLAIM_DISPATCH_PARENT_SPEC_SHA256": "d" * 64,
            "HAPAX_CLAIM_DISPATCH_LANE_SESSION": "hapax-claude-beta",
            "HAPAX_CLAIM_DISPATCH_LANE_GENERATION": "session:test",
            "HAPAX_CLAIM_DISPATCH_CLAIM_PROJECTION_SHA256": "e" * 64,
            "HAPAX_CLAIM_DISPATCH_RELAY_PROJECTION_SHA256": "f" * 64,
        }
    )


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
    assert "refusing mutating launch without an exact dispatched --task" in text
    assert "Do not create, select, or claim other work from the task pool." in text
    assert "--task TASK_ID" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text


def test_headless_new_claim_uses_local_protocol_then_verifies_binding(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_log = tmp_path / "claim.log"
    local_claim = _stub_claim(workdir, claim_log)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    path_claim_used = tmp_path / "path-claim-used"
    _stub_bin(bin_dir, "cc-claim", f"touch {path_claim_used}\nexit 99\n")
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f"touch {claude_called}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = "dispatch-message"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claim_log.read_text(encoding="utf-8").splitlines() == [
        "protocol",
        "claim task-x",
        "verify task-x",
    ]
    assert local_claim == workdir / "scripts" / "cc-claim"
    assert not path_claim_used.exists()
    assert claude_called.exists()


def test_headless_refuses_dirty_activated_shared_implementation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _stub_claim(workdir, tmp_path / "claim.log")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f"touch {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    activation = Path(env["HAPAX_SOURCE_ACTIVATION_WORKTREE"]).resolve()
    shared_module = activation / "shared" / "sdlc_task_store.py"
    shared_module.write_text(
        shared_module.read_text(encoding="utf-8") + "\n# dirty activation\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 14
    assert "refusing unverified source-activation cc-claim" in result.stderr
    assert not claude_called.exists()


def test_headless_refuses_mismatched_activation_last_success(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    receipt = Path(env["HAPAX_SOURCE_ACTIVATION_RECEIPT"])
    (receipt.parent / "last-success-sha").write_text("a" * 40 + "\n", encoding="ascii")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 14
    assert "refusing unverified source-activation cc-claim" in result.stderr


def test_headless_refuses_release_target_with_non_head_basename(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    worktree = Path(env["HAPAX_SOURCE_ACTIVATION_WORKTREE"])
    receipt = Path(env["HAPAX_SOURCE_ACTIVATION_RECEIPT"])
    target = worktree.resolve()
    renamed = target.with_name("release-with-wrong-basename")
    target.rename(renamed)
    worktree.unlink()
    worktree.symlink_to(renamed)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["active_source_target"] = str(renamed)
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 14
    assert "refusing unverified source-activation cc-claim" in result.stderr


def test_headless_legacy_only_cache_requires_session_claim_and_binding(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n", encoding="utf-8")
    claim_log = tmp_path / "claim.log"
    _stub_claim(workdir, claim_log)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_called = tmp_path / "claude-called"
    _stub_bin(bin_dir, "claude", f"touch {claude_called}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = "dispatch-message"
    env["HAPAX_FAKE_CC_CLAIM_VERIFY_RC"] = "23"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 18
    assert "exact dispatch binding verification failed" in result.stderr
    assert claim_log.read_text(encoding="utf-8").splitlines() == [
        "protocol",
        "claim task-x",
        "verify task-x",
    ]
    assert not claude_called.exists()


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


def test_appendix_hop_passes_remote_args_without_shell_interpolation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _stub_claim(workdir, tmp_path / "claim.log")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exploit = tmp_path / "logos-url-shell-injection"
    claude_args = tmp_path / "claude-args.txt"
    claude_env = tmp_path / "claude-env.txt"
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
        f"""printf "%s\\n" "$@" > {claude_args}
printf "HAPAX_DISPATCH_CLAIM_SWEEP=%s\\n" "${{HAPAX_DISPATCH_CLAIM_SWEEP:-}}" > {claude_env}
printf "HAPAX_CLAIM_LEASE_TTL_SECS=%s\\n" "${{HAPAX_CLAIM_LEASE_TTL_SECS:-}}" >> {claude_env}
printf "HAPAX_CLAIM_DISPATCH_MESSAGE_ID=%s\\n" "${{HAPAX_CLAIM_DISPATCH_MESSAGE_ID:-}}" >> {claude_env}
: > {claim_file}
exit 0
""",
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    _add_complete_dispatch_binding(env)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["HAPAX_DISPATCH_LOGOS_URL"] = f"http://podium.invalid/api; touch {exploit}"
    env["HAPAX_DISPATCH_CLAIM_SWEEP"] = "0"
    env["HAPAX_CLAIM_LEASE_TTL_SECS"] = str(2**63 - 1)

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
    assert claude_env.read_text(encoding="utf-8").splitlines() == [
        "HAPAX_DISPATCH_CLAIM_SWEEP=0",
        f"HAPAX_CLAIM_LEASE_TTL_SECS={2**63 - 1}",
        "HAPAX_CLAIM_DISPATCH_MESSAGE_ID=dispatch-message",
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

    result = subprocess.run(
        [str(SCRIPT), "beta", "Task: fake\nAuthorityCase: fake\nParent spec: fake"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 15
    assert "without an exact dispatched --task" in result.stderr


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


def test_committed_launcher_pins_post_exit_terminality_markers() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    # flock idempotency + named launcher pidfile
    assert "flock -n" in text
    assert "LAUNCHER_PIDFILE" in text
    # Terminality is checked only after the child exits naturally.
    assert "task_is_terminal" in text
    assert "stopping respawn loop" in text
    assert 'kill -TERM "$CLAUDE_PID"' not in text
    assert "SELF_REAP" not in text
    assert text.rindex('task_is_terminal "$CLAUDE_TASK"') > text.index('if wait "$CLAUDE_PID"')
    # Line-count floor: the regression stripped the launcher to ~190 lines. The
    # Full launcher with flock, strict admission, and teardown is well over 250.
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
    canonical remote claim verification -> proof."""
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
    _add_complete_dispatch_binding(env)
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

    # The canonical claim transaction publishes exactly one session claim.
    keyed_claims = sorted(cache.glob("cc-active-task-beta-*"))
    assert len(keyed_claims) == 1
    sid = keyed_claims[0].name.removeprefix("cc-active-task-beta-")

    # The exec-side claude carries the SAME identity the launcher minted.
    claude_vars = dict(
        line.split("=", 1) for line in claude_env.read_text().splitlines() if "=" in line
    )
    assert claude_vars.get("HAPAX_SESSION_ID") == sid
    assert claude_vars.get("HAPAX_AGENT_ROLE") == "beta"
    assert claude_vars.get("CLAUDE_ROLE") == "beta"
    assert claude_vars.get("HAPAX_METHODOLOGY_DISPATCH_TASK") == "task-x"

    # The session-keyed claim and binding were established by canonical
    # cc-claim, never by direct launcher writes.
    keyed = cache / f"cc-active-task-beta-{sid}"
    assert keyed.read_text(encoding="utf-8") == "task-x\n"
    assert (cache / f"cc-claim-dispatch-beta-{sid}.json").is_file()

    # The dispatch proof witnesses the session, not just the pid.
    proofs = sorted((cache / "orchestration" / "dispatch-host-proofs").glob("*.json"))
    assert proofs, "remote exec must write a dispatch proof"
    proof = json.loads(proofs[-1].read_text(encoding="utf-8"))
    assert proof["session_id"] == sid
    assert proof["role"] == "beta"
    assert proof["task_id"] == "task-x"
    assert proof["claim_established"] is True
    assert proof["post_claim_task_sha256"] == "9" * 64
    remote_receipt = Path(proof["remote_projection_receipt"])
    assert remote_receipt.is_file()
    assert (
        proof["remote_projection_receipt_sha256"]
        == hashlib.sha256(remote_receipt.read_bytes()).hexdigest()
    )
