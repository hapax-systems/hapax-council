"""Tests for the governed Codex headless launcher."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-codex-headless"


@pytest.fixture(autouse=True)
def _isolate_headless_pid_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HAPAX_CODEX_HEADLESS_PID_DIR", str(tmp_path / "headless-pids"))
    monkeypatch.setenv(
        "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE",
        str(_write_codex_access_token(tmp_path / "codex-oauth")),
    )


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "codex":
        body = (
            """if [ "${1:-}" = "exec" ] && [[ "$*" == *HAPAX_CODEX_EXEC_AUTH_OK* ]]; then
  if [ "${HAPAX_FAKE_CODEX_EXEC_AUTH_RC:-0}" != "0" ]; then
    echo "login required" >&2
    exit "${HAPAX_FAKE_CODEX_EXEC_AUTH_RC}"
  fi
  printf '%s\n' '{"type":"item.completed","item":{"type":"agent_message","text":"HAPAX_CODEX_EXEC_AUTH_OK"}}'
  exit 0
fi
"""
            + body
        )
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _extract_shell_function(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index(f"{name}() {{")
    end = text.index("\n}\n\n", start) + len("\n}\n")
    return text[start:end]


def _write_rejecting_codex(path: Path, fallback_body: str = "exit 0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env bash
if [ "${1:-}" = "exec" ] && [[ "$*" == *HAPAX_CODEX_EXEC_AUTH_OK* ]]; then
  echo "login required" >&2
  exit 77
fi
"""
        + fallback_body,
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_codex_access_token(root: Path, *, exp: int | None = None) -> Path:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": exp or int(time.time()) + 3600}).encode())
        .decode()
        .rstrip("=")
    )
    token_dir = root
    token_dir.mkdir(parents=True, exist_ok=True)
    target = token_dir / "access_token"
    target.write_text(f"{header}.{payload}.sig", encoding="utf-8")
    target.chmod(0o600)
    return target


def _write_claim_epoch(
    cache: Path,
    role: str,
    task_id: str,
    *,
    epoch: str = "1234567890",
    sid: str | None = None,
) -> None:
    suffix = f"-{sid}" if sid else ""
    (cache / f"cc-active-task-{role}{suffix}").write_text(
        f"{task_id}\n",
        encoding="utf-8",
    )
    (cache / f"cc-claim-epoch-{role}{suffix}").write_text(
        f"{epoch} {task_id}\n",
        encoding="utf-8",
    )


def _seal_token_for_test(token: str, key_hex: str) -> str:
    key = bytes.fromhex(key_hex)
    plain = token.encode()
    stream = hashlib.shake_256(key + b":hapax-codex-token-handoff-v1").digest(len(plain))
    cipher = bytes(a ^ b for a, b in zip(plain, stream, strict=True))
    mac = hmac.new(key, b"hapax-codex-token-handoff-v1\0" + cipher, hashlib.sha256).hexdigest()
    return (
        "hapax-token-sealed-v1." + base64.urlsafe_b64encode(cipher).decode().rstrip("=") + "." + mac
    )


def _write_classifying_ssh(
    path: Path,
    log_path: Path,
    *,
    remove_workdir_on_worktree: Path | None = None,
    remove_council_on_worktree: Path | None = None,
    remote_path_on_worktree: Path | None = None,
    remote_path_on_preflight: Path | None = None,
    before_preflight_run: str = "",
    before_exec_run: str = "",
    after_preflight_success: str = "",
) -> None:
    bash_bin = shutil.which("bash") or "/bin/bash"
    codex_stub = path.parent / "codex"
    if not codex_stub.exists():
        _write_executable(codex_stub, "exit 0\n")
    remove_workdir = (
        f"""  rm -rf "{remove_workdir_on_worktree}"
"""
        if remove_workdir_on_worktree is not None
        else ""
    )
    remove_council = (
        f"""  rm -rf "{remove_council_on_worktree}"
"""
        if remove_council_on_worktree is not None
        else ""
    )
    run_worktree_with_path = (
        f"""  PATH="{remote_path_on_worktree}" "{bash_bin}" -c "$remote_cmd"
  exit $?
"""
        if remote_path_on_worktree is not None
        else ""
    )
    run_preflight_with_path = (
        f"""  PATH="{remote_path_on_preflight}" "{bash_bin}" -c "$remote_cmd"
  exit $?
"""
        if remote_path_on_preflight is not None
        else ""
    )
    _write_executable(
        path,
        f"""remote_cmd="${{@: -1}}"
kind="$(python3 - "$remote_cmd" <<'PY'
import base64
import shlex
import sys

parts = shlex.split(sys.argv[1])
code = base64.b64decode(parts[-1]).decode()
if "create_worktree" in code and "worktree" in code:
    print("worktree")
elif "required_dirs" in code and "executables" in code:
    print("preflight")
elif "os.execv" in code:
    print("exec")
else:
    print("unknown")
PY
)"
printf '%s\\n' "$kind" >> "{log_path}"
if [ "$kind" = "worktree" ]; then
  :
{remove_workdir}{remove_council}{run_worktree_with_path}fi
if [ "$kind" = "preflight" ]; then
  :
{before_preflight_run}
{run_preflight_with_path}  "{bash_bin}" -c "$remote_cmd"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    :
{after_preflight_success}
  fi
  exit "$rc"
fi
if [ "$kind" = "exec" ]; then
  :
{before_exec_run}
fi
exec "{bash_bin}" -c "$remote_cmd"
""",
    )


def _extract_remote_python(name: str) -> str:
    prefix = f"{name}='"
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index(prefix) + len(prefix)
    end = text.index("'\n", start)
    return text[start:end]


def _python_only_remote_path(tmp_path: Path) -> Path:
    remote_bin = tmp_path / "remote-bin"
    remote_bin.mkdir()
    python_bin = shutil.which("python3")
    bash_bin = shutil.which("bash")
    assert python_bin is not None
    assert bash_bin is not None
    (remote_bin / "python3").symlink_to(python_bin)
    (remote_bin / "bash").symlink_to(bash_bin)
    return remote_bin


def test_resolve_local_codex_bin_skips_directory_candidates(tmp_path: Path) -> None:
    bad_dir = tmp_path / "not-a-codex-binary"
    bad_dir.mkdir()
    home = tmp_path / "home"
    fallback_codex = home / ".npm-global" / "bin" / "codex"
    _write_executable(fallback_codex, "exit 0\n")
    path_dir = tmp_path / "path"
    path_dir.mkdir()
    bash = shutil.which("bash") or "/usr/bin/bash"

    result = subprocess.run(
        [
            bash,
            "-c",
            f"{_extract_shell_function('resolve_local_codex_bin')}\nresolve_local_codex_bin",
        ],
        capture_output=True,
        text=True,
        env={
            "HOME": str(home),
            "HAPAX_CODEX_BIN_PATH": str(bad_dir),
            "NPM_CONFIG_PREFIX": "",
            "PATH": str(path_dir),
        },
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(fallback_codex)


def _write_minimal_council(council_dir: Path, retire_log: Path) -> None:
    _write_executable(council_dir / "hooks" / "scripts" / "codex-hook-adapter.sh", "exit 0\n")
    _write_executable(
        council_dir / "scripts" / "hapax-relay-retire",
        f"""printf '%s\\n' "$*" >> "{retire_log}"
exit 0
""",
    )


def _init_primary_council_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    _write_executable(path / "hooks" / "scripts" / "codex-hook-adapter.sh", "exit 0\n")
    (path / "README.md").write_text("primary council\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_codex_headless_runs_on_appendix_via_remote_payload(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("task-x\n", encoding="utf-8")
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    env_file = tmp_path / "codex-env.txt"
    _write_executable(
        bin_dir / "ssh",
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
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
printf 'LOGOS_BASE_URL=%s\\n' "${{LOGOS_BASE_URL:-}}" > {env_file}
printf 'HAPAX_DISPATCH_HOST=%s\\n' "${{HAPAX_DISPATCH_HOST:-}}" >> {env_file}
printf 'CODEX_ACCESS_TOKEN_PRESENT=%s\\n' "${{CODEX_ACCESS_TOKEN:+yes}}" >> {env_file}
printf 'CODEX_HOME_PRESENT=%s\\n' "${{CODEX_HOME:+yes}}" >> {env_file}
printf 'CODEX_API_KEY_PRESENT=%s\\n' "${{CODEX_API_KEY:+yes}}" >> {env_file}
printf 'OPENAI_API_KEY_PRESENT=%s\\n' "${{OPENAI_API_KEY:+yes}}" >> {env_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["CODEX_ACCESS_TOKEN"] = "ambient-token-must-not-reach-worker"
    env["CODEX_HOME"] = str(tmp_path / "ambient-codex-home")
    env["CODEX_API_KEY"] = "ambient-codex-api-key-must-not-reach-worker"
    env["OPENAI_API_KEY"] = "ambient-openai-api-key-must-not-reach-worker"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "exec --dangerously-bypass-approvals-and-sandbox" in args_file.read_text(
        encoding="utf-8"
    )
    launched_env = env_file.read_text(encoding="utf-8")
    assert "LOGOS_BASE_URL=http://192.168.68.85:8051/api" in launched_env
    assert "HAPAX_DISPATCH_HOST=local" in launched_env
    assert "CODEX_ACCESS_TOKEN_PRESENT=yes" not in launched_env
    assert "CODEX_HOME_PRESENT=yes" not in launched_env
    assert "CODEX_API_KEY_PRESENT=yes" not in launched_env
    assert "OPENAI_API_KEY_PRESENT=yes" not in launched_env
    proofs = list(
        (home / ".cache" / "hapax" / "orchestration" / "dispatch-host-proofs").glob(
            "*cx-amber-task-x-headless-remote.json"
        )
    )
    assert len(proofs) == 1
    assert '"platform": "codex-headless"' in proofs[0].read_text(encoding="utf-8")
    proof = json.loads(proofs[0].read_text(encoding="utf-8"))
    assert proof["role"] == "cx-amber"
    assert proof["task_id"] == "task-x"
    assert proof["session_id"]
    assert proof["claim_materialized"] is True
    assert proof["claim_epoch_verified"] is True
    sid = proof["session_id"]
    assert (cache / f"session-role-{sid}").read_text(encoding="utf-8") == "cx-amber\n"
    assert (cache / f"cc-active-task-cx-amber-{sid}").read_text(encoding="utf-8") == "task-x\n"
    legacy_epoch, _, legacy_task = (
        (cache / "cc-claim-epoch-cx-amber").read_text(encoding="utf-8").strip().partition(" ")
    )
    session_epoch, _, session_task = (
        (cache / f"cc-claim-epoch-cx-amber-{sid}")
        .read_text(encoding="utf-8")
        .strip()
        .partition(" ")
    )
    assert legacy_epoch == "1234567890"
    assert session_epoch == "1234567890"
    assert legacy_task == "task-x"
    assert session_task == "task-x"


def test_codex_headless_remote_uses_configured_codex_binary(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("task-x\n", encoding="utf-8")
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    remote_path = _python_only_remote_path(tmp_path)
    path_marker = tmp_path / "path-codex-used"
    _write_executable(
        bin_dir / "ssh",
        f"""remote_cmd="${{@: -1}}"
env -u HAPAX_CODEX_BIN -u HAPAX_CODEX_BIN_PATH -u NPM_CONFIG_PREFIX PATH="{remote_path}" bash -c "$remote_cmd"
""",
    )
    _write_rejecting_codex(
        bin_dir / "codex",
        fallback_body=f"""printf '%s\\n' "$*" > {path_marker}
exit 66
""",
    )
    configured_codex = tmp_path / "configured-bin" / "codex"
    configured_args = tmp_path / "configured-codex-args.txt"
    _write_executable(
        configured_codex,
        f"""printf '%s\\n' "$*" > {configured_args}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["HAPAX_CODEX_BIN_PATH"] = str(configured_codex)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "exec --dangerously-bypass-approvals-and-sandbox" in configured_args.read_text(
        encoding="utf-8"
    )
    assert not path_marker.exists()
    proofs = list(
        (home / ".cache" / "hapax" / "orchestration" / "dispatch-host-proofs").glob(
            "*cx-amber-task-x-headless-remote.json"
        )
    )
    assert len(proofs) == 1
    proof = json.loads(proofs[0].read_text(encoding="utf-8"))
    assert proof["argv0"] == str(configured_codex)


def test_codex_headless_remote_no_claim_without_epoch_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("task-x\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_executable(
        bin_dir / "ssh",
        f"""printf 'ssh-called\\n' >> {ssh_log}
remote_cmd="${{@: -1}}"
exec bash -c "$remote_cmd"
""",
    )
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert "without a matching local cc-claim epoch" in result.stderr
    assert not ssh_log.exists()
    assert not args_file.exists()
    assert not list((cache / "orchestration" / "dispatch-host-proofs").glob("*remote.json"))


def test_codex_headless_remote_no_claim_with_orphan_epoch_fails_closed(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-claim-epoch-cx-amber").write_text("1234567890 task-x\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_executable(
        bin_dir / "ssh",
        f"""printf 'ssh-called\\n' >> {ssh_log}
exit 99
""",
    )
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert "without a matching local cc-claim epoch" in result.stderr
    assert not ssh_log.exists()
    assert not args_file.exists()
    assert not list((cache / "orchestration" / "dispatch-host-proofs").glob("*remote.json"))


def test_codex_headless_treats_appendix_alias_as_local_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_called = tmp_path / "ssh-called"
    codex_args = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _write_executable(
        bin_dir / "ssh",
        f""": > "{ssh_called}"
echo 'ssh should not be called for local appendix alias' >&2
exit 99
""",
    )
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\n' "$*" > "{codex_args}"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert codex_args.exists()


def test_codex_headless_treats_appendix_local_ip_as_local(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_called = tmp_path / "ssh-called"
    codex_args = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  -I) printf '%s\n' '192.168.68.50 10.0.0.50' ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _write_executable(
        bin_dir / "ssh",
        f""": > "{ssh_called}"
echo 'ssh should not be called for local appendix IP' >&2
exit 99
""",
    )
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\n' "$*" > "{codex_args}"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "192.168.68.50"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert codex_args.exists()


def test_codex_headless_local_launch_uses_saved_auth_without_published_token(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    codex_called = tmp_path / "codex-called"
    _write_executable(
        bin_dir / "codex",
        f""": > "{codex_called}"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(home / "missing-access-token")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert codex_called.exists()


def test_codex_headless_ignores_inherited_access_token_without_published_token(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    codex_called = tmp_path / "codex-called"
    _write_executable(
        bin_dir / "codex",
        f""": > "{codex_called}"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(home / "missing-access-token")
    env["CODEX_ACCESS_TOKEN"] = "inherited-junk-token"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "ignoring inherited CODEX_ACCESS_TOKEN" in result.stderr
    assert codex_called.exists()


def test_codex_headless_ignores_unsafe_published_token_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    codex_called = tmp_path / "codex-called"
    _write_executable(
        bin_dir / "codex",
        f""": > "{codex_called}"
exit 0
""",
    )
    token_file = _write_codex_access_token(home / "codex-oauth", exp=int(time.time()) + 3600)
    token_file.chmod(0o644)

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(token_file)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert codex_called.exists()


def test_codex_headless_refuses_rejected_local_bearer_before_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    codex_args = tmp_path / "codex-args.txt"
    claim_log = tmp_path / "claim.log"
    _write_rejecting_codex(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > "{codex_args}"
exit 0
""",
    )
    _write_executable(
        workdir / "scripts" / "cc-claim",
        f"""printf '%s\\n' "$*" >> "{claim_log}"
mkdir -p "$HOME/.cache/hapax"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert "saved Codex auth was rejected by codex exec" in result.stderr
    assert "codex_saved_auth_login_required" in result.stderr
    assert not claim_log.exists()
    assert not codex_args.exists()


def test_codex_headless_uses_preclaim_proven_local_bearer_after_claim_rotation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    token_file = _write_codex_access_token(
        home / ".cache" / "hapax" / "codex-oauth",
        exp=int(time.time()) + 3600,
    )
    rotated_token = (
        _write_codex_access_token(
            tmp_path / "rotated-token",
            exp=int(time.time()) + 7200,
        )
        .read_text(encoding="utf-8")
        .strip()
    )

    bin_dir = tmp_path / "bin"
    used_token = tmp_path / "used-token.txt"
    claim_log = tmp_path / "claim.log"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "${{CODEX_ACCESS_TOKEN:-}}" > "{used_token}"
exit 0
""",
    )
    _write_executable(
        workdir / "scripts" / "cc-claim",
        f"""printf '%s\\n' "{rotated_token}" > "{token_file}"
printf '%s\\n' "$*" >> "{claim_log}"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(token_file)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert claim_log.exists()
    assert token_file.read_text(encoding="utf-8").strip() == rotated_token
    assert used_token.read_text(encoding="utf-8").strip() == ""


def test_codex_headless_creates_missing_remote_default_worktree(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("task-x\n", encoding="utf-8")
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)

    # Present for the launcher's podium-local validation, then removed by the
    # fake SSH boundary before remote preflight to model appendix missing it.
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    pwd_file = tmp_path / "codex-pwd.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )
    _write_executable(
        bin_dir / "codex",
        f"""pwd > {pwd_file}
printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert ssh_log.read_text(encoding="utf-8").splitlines() == [
        "preflight",
        "worktree",
        "preflight",
        "preflight",
        "exec",
    ]
    assert pwd_file.read_text(encoding="utf-8").strip() == str(workdir)
    branch = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "codex/cx-amber"
    assert "exec --dangerously-bypass-approvals-and-sandbox" in args_file.read_text(
        encoding="utf-8"
    )


def test_codex_headless_remote_refuses_if_claim_revoked_before_exec_payload(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    preflight_count = tmp_path / "preflight-count.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
        after_preflight_success=f"""  count="$(cat "{preflight_count}" 2>/dev/null || printf '0')"
  count="$((count + 1))"
  printf '%s\\n' "$count" > "{preflight_count}"
  if [ "$count" -ge 3 ]; then
    rm -f "{cache / "cc-active-task-cx-amber"}" "{cache / "cc-claim-epoch-cx-amber"}"
  fi
""",
    )
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert "without a matching local cc-claim epoch" in result.stderr
    assert ssh_log.read_text(encoding="utf-8").splitlines() == [
        "preflight",
        "worktree",
        "preflight",
        "preflight",
    ]
    assert preflight_count.read_text(encoding="utf-8").strip() == "3"
    assert not args_file.exists()
    assert not list((cache / "orchestration" / "dispatch-host-proofs").glob("*remote.json"))


def test_codex_headless_refuses_without_task_before_remote_bootstrap(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_executable(
        bin_dir / "ssh",
        f"""printf 'ssh invoked\\n' >> "{ssh_log}"
rm -rf "{workdir}"
exit 99
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 15
    assert "without --task" in result.stderr
    assert not ssh_log.exists()
    assert workdir.exists()


def test_codex_headless_claim_mismatch_refuses_before_remote_bootstrap(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("other-task\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_executable(
        bin_dir / "ssh",
        f"""printf 'ssh invoked\\n' >> "{ssh_log}"
exit 99
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 13
    assert "already claims 'other-task'" in result.stderr
    assert not ssh_log.exists()


def test_codex_headless_remote_saved_auth_preflight_refuses_after_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    claim_log = tmp_path / "claim.log"
    _write_rejecting_codex(bin_dir / "codex")
    _write_classifying_ssh(bin_dir / "ssh", ssh_log)
    _write_executable(
        workdir / "scripts" / "cc-claim",
        f"""printf '%s\\n' "$*" >> "{claim_log}"
mkdir -p "$HOME/.cache/hapax"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(home / "missing-access-token")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight"]
    assert "remote Codex auth preflight failed" in result.stderr
    assert "codex_saved_auth_login_required" in result.stderr
    assert "HAPAX_DISPATCH_HOST_FALLBACK=local" in result.stderr
    assert claim_log.read_text(encoding="utf-8") == "task-x\n"


def test_codex_headless_remote_saved_auth_preflight_rejects_unaccepted_login_after_claim(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    claim_log = tmp_path / "claim.log"
    _write_rejecting_codex(bin_dir / "codex")
    _write_classifying_ssh(bin_dir / "ssh", ssh_log)
    _write_executable(
        workdir / "scripts" / "cc-claim",
        f"""printf '%s\\n' "$*" >> "{claim_log}"
mkdir -p "$HOME/.cache/hapax"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight"]
    assert "remote Codex auth preflight failed" in result.stderr
    assert "codex_saved_auth_login_required" in result.stderr
    assert claim_log.read_text(encoding="utf-8") == "task-x\n"


def test_codex_headless_remote_bootstrap_refuses_missing_explicit_workdir(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "explicit-worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "explicit" in result.stderr
    assert "next action:" in result.stderr
    assert "verify" in result.stderr
    assert "HAPAX_CODEX_CREATE_WORKTREE" in result.stderr


def test_codex_headless_remote_bootstrap_refuses_disabled_worktree_creation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_CREATE_WORKTREE"] = "0"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "disabled" in result.stderr


def test_codex_headless_remote_bootstrap_reports_missing_remote_council(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
        remove_council_on_worktree=primary,
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "council checkout" in result.stderr


def test_codex_headless_live_pid_blocks_remote_bootstrap_before_ssh(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_executable(
        bin_dir / "ssh",
        f"""printf 'ssh invoked\\n' >> "{ssh_log}"
exit 99
""",
    )

    live = subprocess.Popen(["sleep", "60"])
    try:
        (pid_dir / "cx-amber.pid").write_text(f"{live.pid}\n", encoding="utf-8")
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
        env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
        env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
        env["HAPAX_CODEX_HEADLESS_PID_DIR"] = str(pid_dir)
        env["HAPAX_DISPATCH_HOST"] = "appendix"

        result = subprocess.run(
            [
                str(SCRIPT),
                "--task",
                "task-x",
                "--no-claim",
                "--force",
                "cx-amber",
                "governed prompt",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
    finally:
        live.terminate()
        live.wait(timeout=5)

    assert result.returncode == 11
    assert "already live" in result.stderr
    assert not ssh_log.exists()


def test_codex_headless_remote_preflight_reports_missing_codex_binary(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
        remote_path_on_preflight=_python_only_remote_path(tmp_path),
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight"]
    assert "remote Codex auth preflight failed" in result.stderr
    assert "missing_binaries" in result.stderr
    assert "codex" in result.stderr
    assert "next action:" in result.stderr
    assert "HAPAX_DISPATCH_HOST_FALLBACK=local" in result.stderr


def test_codex_headless_remote_bootstrap_reports_missing_git(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
        remote_path_on_worktree=_python_only_remote_path(tmp_path),
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "git binary missing" in result.stderr


def test_codex_headless_remote_bootstrap_uses_existing_branch_when_present(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    subprocess.run(["git", "-C", str(primary), "branch", "codex/cx-amber"], check=True)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    pwd_file = tmp_path / "codex-pwd.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )
    _write_executable(
        bin_dir / "codex",
        f"""pwd > {pwd_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert ssh_log.read_text(encoding="utf-8").splitlines() == [
        "preflight",
        "worktree",
        "preflight",
        "preflight",
        "exec",
    ]
    assert pwd_file.read_text(encoding="utf-8").strip() == str(workdir)
    branch = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "codex/cx-amber"


def test_codex_headless_remote_exec_uses_preclaim_proven_token_handoff(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    _write_executable(
        primary / "scripts" / "cc-claim",
        """mkdir -p "$HOME/.cache/hapax"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
exit 0
""",
    )
    subprocess.run(["git", "-C", str(primary), "add", "scripts/cc-claim"], check=True)
    subprocess.run(
        ["git", "-C", str(primary), "commit", "-m", "add claim helper"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["git", "-C", str(primary), "branch", "codex/cx-amber"], check=True)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)
    _write_executable(
        workdir / "scripts" / "cc-claim",
        """mkdir -p "$HOME/.cache/hapax"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
exit 0
""",
    )

    token_file = _write_codex_access_token(
        home / ".cache" / "hapax" / "codex-oauth",
        exp=int(time.time()) + 3600,
    )
    rotated_token = (
        _write_codex_access_token(
            tmp_path / "rotated-remote-token",
            exp=int(time.time()) + 7200,
        )
        .read_text(encoding="utf-8")
        .strip()
    )

    bin_dir = tmp_path / "bin"
    used_token = tmp_path / "remote-used-token.txt"
    preflight_count = tmp_path / "preflight-count.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
        after_preflight_success=f"""  count="$(cat "{preflight_count}" 2>/dev/null || printf '0')"
  count="$((count + 1))"
  printf '%s\\n' "$count" > "{preflight_count}"
  if [ "$count" -ge 3 ]; then
    printf '%s\\n' "{rotated_token}" > "{token_file}"
  fi
""",
    )
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "${{CODEX_ACCESS_TOKEN:-}}" > "{used_token}"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(token_file)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert ssh_log.read_text(encoding="utf-8").splitlines() == [
        "preflight",
        "worktree",
        "preflight",
        "preflight",
        "exec",
    ]
    assert preflight_count.read_text(encoding="utf-8").strip() == "3"
    assert token_file.read_text(encoding="utf-8").strip() == rotated_token
    assert used_token.read_text(encoding="utf-8").strip() == ""


def test_codex_headless_remote_preflight_does_not_materialize_token_handoff(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    _write_executable(
        primary / "scripts" / "cc-claim",
        """mkdir -p "$HOME/.cache/hapax"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
exit 0
""",
    )
    subprocess.run(["git", "-C", str(primary), "add", "scripts/cc-claim"], check=True)
    subprocess.run(
        ["git", "-C", str(primary), "commit", "-m", "add claim helper"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["git", "-C", str(primary), "branch", "codex/cx-amber"], check=True)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)
    _write_executable(
        workdir / "scripts" / "cc-claim",
        """mkdir -p "$HOME/.cache/hapax"
printf '1234567890 %s\\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-cx-amber"
printf '%s\\n' "$1" > "$HOME/.cache/hapax/cc-active-task-cx-amber"
exit 0
""",
    )

    token_file = _write_codex_access_token(
        home / ".cache" / "hapax" / "codex-oauth",
        exp=int(time.time()) + 3600,
    )
    handoff_path_log = tmp_path / "handoff-path.txt"
    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
        before_preflight_run=f"""  python3 - "$remote_cmd" "{handoff_path_log}" <<'PY'
import base64
import json
import pathlib
import shlex
import sys

parts = shlex.split(sys.argv[1])
payload = json.loads(base64.b64decode(parts[-2]))
handoff = payload.get("token_handoff_file")
if handoff:
    pathlib.Path(sys.argv[2]).write_text(handoff, encoding="utf-8")
    pathlib.Path(handoff).write_text("preexisting\\n", encoding="utf-8")
PY
""",
    )
    _write_executable(bin_dir / "codex", "exit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(token_file)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    try:
        if handoff_path_log.exists():
            Path(handoff_path_log.read_text(encoding="utf-8").strip()).unlink(missing_ok=True)
    finally:
        assert result.returncode == 0, result.stderr
        assert not handoff_path_log.exists()
        assert ssh_log.read_text(encoding="utf-8").splitlines() == [
            "preflight",
            "worktree",
            "preflight",
            "preflight",
            "exec",
        ]


def test_codex_headless_remote_token_cleanup_surface_is_retired() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "REMOTE_TOKEN_CLEANUP_PY" not in text
    assert "remote_token_cleanup_payload_b64" not in text
    assert "preflight-proven Codex OAuth token handoff" not in text


def test_codex_headless_remote_preflight_ignores_token_handoff_payload(
    tmp_path: Path,
) -> None:
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "codex", "exit 0\n")
    token = _write_codex_access_token(tmp_path / "oauth", exp=int(time.time()) + 3600)
    seal_key = "a" * 64
    handoff = Path("/tmp") / f"hapax-codex-token-headless-ttl-{os.getpid()}-{tmp_path.name}"
    handoff.unlink(missing_ok=True)
    payload = {
        "required_dirs": [],
        "executables": [],
        "binaries": ["codex"],
        "token_file": str(token),
        "token_handoff_file": str(handoff),
        "token_handoff_seal_key": seal_key,
        "token_handoff_ttl_seconds": 2,
    }
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    try:
        result = subprocess.run(
            [sys.executable, "-c", remote_preflight_py],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )

        assert result.returncode == 0, result.stderr
        assert not handoff.exists()
    finally:
        handoff.unlink(missing_ok=True)


def test_codex_headless_remote_preflight_ignores_invalid_token_handoff_ttl(
    tmp_path: Path,
) -> None:
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "codex", "exit 0\n")
    token = _write_codex_access_token(tmp_path / "oauth", exp=int(time.time()) + 3600)
    seal_key = "b" * 64
    handoff = Path("/tmp") / f"hapax-codex-token-headless-invalid-ttl-{os.getpid()}-{tmp_path.name}"
    handoff.unlink(missing_ok=True)
    payload = {
        "required_dirs": [],
        "executables": [],
        "binaries": ["codex"],
        "token_file": str(token),
        "token_handoff_file": str(handoff),
        "token_handoff_seal_key": seal_key,
        "token_handoff_ttl_seconds": 0,
    }
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    result = subprocess.run(
        [sys.executable, "-c", remote_preflight_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert not handoff.exists()


def test_codex_headless_remote_preflight_ignores_world_readable_published_token(
    tmp_path: Path,
) -> None:
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "codex", "exit 0\n")
    token = _write_codex_access_token(tmp_path / "oauth", exp=int(time.time()) + 3600)
    token.chmod(0o644)
    payload = {
        "required_dirs": [],
        "executables": [],
        "binaries": [],
        "token_file": str(token),
        "token_handoff_file": "",
        "token_handoff_seal_key": "",
        "token_handoff_ttl_seconds": 2,
    }
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    result = subprocess.run(
        [sys.executable, "-c", remote_preflight_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_codex_headless_remote_preflight_cleanup_child_clears_bearer_material_before_sleep() -> (
    None
):
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")

    assert "os.fork" not in remote_preflight_py
    assert 'env.pop("CODEX_ACCESS_TOKEN",None)' in remote_preflight_py
    assert 'p.get("codex_exec_auth_timeout")' in remote_preflight_py
    assert "timeout=auth_timeout" in remote_preflight_py


def test_codex_headless_local_auth_timeout_env_is_validated_before_timeout() -> None:
    prove_auth = _extract_shell_function("prove_local_codex_exec_auth")

    assert "invalid HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS" in prove_auth
    assert "math.isfinite(value)" in prove_auth
    assert "value <= 0" in prove_auth
    assert 'timeout_s="30"' in prove_auth
    assert 'timeout "${timeout_s}s" env -i' in prove_auth


@pytest.mark.parametrize(
    ("timeout_value", "expected_timeout"),
    [
        ("0", "30s"),
        ("-1", "30s"),
        ("nan", "30s"),
        ("inf", "30s"),
        ("0.25", "0.25s"),
    ],
)
def test_codex_headless_local_auth_timeout_rejects_unbounded_values(
    tmp_path: Path,
    timeout_value: str,
    expected_timeout: str,
) -> None:
    bin_dir = tmp_path / "bin"
    timeout_log = tmp_path / "timeout-arg.log"
    fake_codex = bin_dir / "codex"
    _write_executable(fake_codex, "exit 0\n")
    _write_executable(
        bin_dir / "timeout",
        """printf '%s\\n' "$1" > "$HAPAX_TIMEOUT_ARG_LOG"
printf '%s\\n' '{"type":"item.completed","item":{"type":"agent_message","text":"HAPAX_CODEX_EXEC_AUTH_OK"}}'
exit 0
""",
    )
    bash = shutil.which("bash") or "/usr/bin/bash"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_TIMEOUT_ARG_LOG"] = str(timeout_log)
    env["HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS"] = timeout_value

    result = subprocess.run(
        [
            bash,
            "-c",
            "\n".join(
                [
                    _extract_shell_function("codex_exec_auth_sentinel_observed"),
                    _extract_shell_function("prove_local_codex_exec_auth"),
                    f'prove_local_codex_exec_auth "{fake_codex}"',
                ]
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert timeout_log.read_text(encoding="utf-8").strip() == expected_timeout
    if expected_timeout == "30s":
        assert "invalid HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS" in result.stderr
    else:
        assert "invalid HAPAX_CODEX_EXEC_AUTH_TIMEOUT_SECONDS" not in result.stderr


def test_codex_headless_remote_preflight_rejects_prompt_echo_without_agent_sentinel(
    tmp_path: Path,
) -> None:
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        """#!/usr/bin/env bash
if [ "${1:-}" = "exec" ]; then
  printf '%s\n' '{"message":"Reply exactly: HAPAX_CODEX_EXEC_AUTH_OK"}'
  exit 0
fi
exit 77
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    payload = {
        "required_dirs": [],
        "executables": [],
        "binaries": ["codex"],
        "codex_exec_auth_timeout": 5,
    }
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    result = subprocess.run(
        [sys.executable, "-c", remote_preflight_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    assert "codex_saved_auth_sentinel_missing" in result.stderr


def test_codex_headless_remote_preflight_does_not_fork_for_token_cleanup(
    tmp_path: Path,
) -> None:
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "codex", "exit 0\n")
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import os\n"
        "def _fail_fork():\n"
        "    raise OSError('forced fork failure')\n"
        "os.fork = _fail_fork\n",
        encoding="utf-8",
    )
    token = _write_codex_access_token(tmp_path / "oauth", exp=int(time.time()) + 3600)
    seal_key = "c" * 64
    handoff = Path("/tmp") / f"hapax-codex-token-headless-fork-fail-{os.getpid()}-{tmp_path.name}"
    handoff.unlink(missing_ok=True)
    payload = {
        "required_dirs": [],
        "executables": [],
        "binaries": ["codex"],
        "token_file": str(token),
        "token_handoff_file": str(handoff),
        "token_handoff_seal_key": seal_key,
        "token_handoff_ttl_seconds": 2,
    }
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PYTHONPATH"] = str(tmp_path)
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    result = subprocess.run(
        [sys.executable, "-c", remote_preflight_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert not handoff.exists()


def test_codex_headless_claim_failure_does_not_create_remote_bearer_handoff(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    _write_executable(primary / "scripts" / "cc-claim", "exit 42\n")
    subprocess.run(["git", "-C", str(primary), "add", "scripts/cc-claim"], check=True)
    subprocess.run(
        ["git", "-C", str(primary), "commit", "-m", "add failing claim helper"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["git", "-C", str(primary), "branch", "codex/cx-amber"], check=True)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)
    _write_executable(workdir / "scripts" / "cc-claim", "exit 42\n")

    token_file = _write_codex_access_token(
        home / ".cache" / "hapax" / "codex-oauth",
        exp=int(time.time()) + 3600,
    )
    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )
    _write_executable(bin_dir / "codex", "exit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(token_file)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 42
    assert "token handoff" not in result.stderr
    assert not ssh_log.exists()


def test_codex_headless_malicious_session_id_does_not_escape_tmp(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    _write_executable(primary / "scripts" / "cc-claim", "exit 42\n")
    subprocess.run(["git", "-C", str(primary), "add", "scripts/cc-claim"], check=True)
    subprocess.run(
        ["git", "-C", str(primary), "commit", "-m", "add failing claim helper"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["git", "-C", str(primary), "branch", "codex/cx-amber"], check=True)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)
    _write_executable(workdir / "scripts" / "cc-claim", "exit 42\n")

    token_file = _write_codex_access_token(
        home / ".cache" / "hapax" / "codex-oauth",
        exp=int(time.time()) + 3600,
    )
    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )
    _write_executable(bin_dir / "codex", "exit 0\n")

    leak_prefix = f"hapax-codex-headless-leak-{os.getpid()}-{tmp_path.name}"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE"] = str(token_file)
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
    env["HAPAX_SESSION_ID"] = f"../../{leak_prefix}"
    for leaked in Path("/tmp").glob(f"{leak_prefix}-*"):
        leaked.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode == 42
        assert not ssh_log.exists()
        assert not list(Path("/tmp").glob(f"{leak_prefix}-*"))
    finally:
        for leaked in Path("/tmp").glob(f"{leak_prefix}-*"):
            leaked.unlink(missing_ok=True)


def test_codex_headless_remote_exec_strips_inherited_codex_auth_env(
    tmp_path: Path,
) -> None:
    remote_exec_py = _extract_remote_python("REMOTE_EXEC_PY")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    codex_bin = tmp_path / "bin" / "codex"
    used_token = tmp_path / "used-token.txt"
    used_codex_home = tmp_path / "used-codex-home.txt"
    used_codex_api_key = tmp_path / "used-codex-api-key.txt"
    used_openai_api_key = tmp_path / "used-openai-api-key.txt"
    _write_executable(
        codex_bin,
        f"""printf '%s\\n' "${{CODEX_ACCESS_TOKEN:-}}" > "{used_token}"
printf '%s\\n' "${{CODEX_HOME:-}}" > "{used_codex_home}"
printf '%s\\n' "${{CODEX_API_KEY:-}}" > "{used_codex_api_key}"
printf '%s\\n' "${{OPENAI_API_KEY:-}}" > "{used_openai_api_key}"
exit 0
""",
    )
    payload = {
        "workdir": str(workdir),
        "env": {
            "CODEX_ACCESS_TOKEN": "ambient-token-must-not-reach-worker",
            "CODEX_HOME": str(tmp_path / "ambient-codex-home"),
            "CODEX_API_KEY": "ambient-codex-api-key-must-not-reach-worker",
            "OPENAI_API_KEY": "ambient-openai-api-key-must-not-reach-worker",
        },
        "proof_file": "",
        "argv": ["codex"],
    }
    env = os.environ.copy()
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()
    env["NPM_CONFIG_PREFIX"] = ""
    env["PATH"] = str(_python_only_remote_path(tmp_path))
    env["HAPAX_CODEX_BIN_PATH"] = str(codex_bin)

    result = subprocess.run(
        [sys.executable, "-c", remote_exec_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert used_token.read_text(encoding="utf-8").strip() == ""
    assert used_codex_home.read_text(encoding="utf-8").strip() == ""
    assert used_codex_api_key.read_text(encoding="utf-8").strip() == ""
    assert used_openai_api_key.read_text(encoding="utf-8").strip() == ""


def test_codex_headless_remote_exec_fails_if_claim_cache_materialization_fails(
    tmp_path: Path,
) -> None:
    remote_exec_py = _extract_remote_python("REMOTE_EXEC_PY")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    codex_bin = tmp_path / "bin" / "codex"
    _write_executable(codex_bin, "exit 0\n")
    token_path = _write_codex_access_token(tmp_path / "handoff", exp=int(time.time()) + 3600)
    seal_key = "e" * 64
    token_path.write_text(
        _seal_token_for_test(token_path.read_text(encoding="utf-8").strip(), seal_key),
        encoding="utf-8",
    )
    not_a_home = tmp_path / "not-a-home"
    not_a_home.write_text("not a directory\n", encoding="utf-8")
    proof = tmp_path / "proof.json"
    payload = {
        "workdir": str(workdir),
        "env": {
            "HOME": str(not_a_home),
            "HAPAX_SESSION_ID": "remote-cache-session",
            "HAPAX_AGENT_ROLE": "cx-amber",
            "HAPAX_METHODOLOGY_DISPATCH_TASK": "task-x",
            "HAPAX_METHODOLOGY_DISPATCH_CLAIM_EPOCH": "1234567890 task-x",
        },
        "proof_file": str(proof),
        "token_handoff_file": str(token_path),
        "token_handoff_seal_key": seal_key,
        "argv": ["codex"],
    }
    env = os.environ.copy()
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()
    env["NPM_CONFIG_PREFIX"] = ""
    env["PATH"] = str(_python_only_remote_path(tmp_path))
    env["HAPAX_CODEX_BIN_PATH"] = str(codex_bin)

    result = subprocess.run(
        [sys.executable, "-c", remote_exec_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert "failed to materialize remote claim cache" in result.stderr
    assert not proof.exists()


def test_codex_headless_remote_exec_refuses_task_without_claim_epoch(tmp_path: Path) -> None:
    remote_exec_py = _extract_remote_python("REMOTE_EXEC_PY")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    codex_bin = tmp_path / "bin" / "codex"
    _write_executable(codex_bin, "exit 0\n")
    token_path = _write_codex_access_token(tmp_path / "handoff", exp=int(time.time()) + 3600)
    seal_key = "f" * 64
    token_path.write_text(
        _seal_token_for_test(token_path.read_text(encoding="utf-8").strip(), seal_key),
        encoding="utf-8",
    )
    proof = tmp_path / "proof.json"
    payload = {
        "workdir": str(workdir),
        "env": {
            "HOME": str(tmp_path / "home"),
            "HAPAX_SESSION_ID": "remote-cache-session",
            "HAPAX_AGENT_ROLE": "cx-amber",
            "HAPAX_METHODOLOGY_DISPATCH_TASK": "task-x",
        },
        "proof_file": str(proof),
        "token_handoff_file": str(token_path),
        "token_handoff_seal_key": seal_key,
        "argv": ["codex"],
    }
    env = os.environ.copy()
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()
    env["NPM_CONFIG_PREFIX"] = ""
    env["PATH"] = str(_python_only_remote_path(tmp_path))
    env["HAPAX_CODEX_BIN_PATH"] = str(codex_bin)

    result = subprocess.run(
        [sys.executable, "-c", remote_exec_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert "without matching local cc-claim epoch" in result.stderr
    assert not proof.exists()


def test_codex_headless_remote_exec_claim_guards_precede_missing_codex(
    tmp_path: Path,
) -> None:
    remote_exec_py = _extract_remote_python("REMOTE_EXEC_PY")
    no_codex_path = _python_only_remote_path(tmp_path)

    def run_remote_exec(case: str, payload_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        workdir = tmp_path / f"workdir-{case}"
        workdir.mkdir()
        token_path = _write_codex_access_token(
            tmp_path / f"handoff-{case}",
            exp=int(time.time()) + 3600,
        )
        seal_key = "a" * 64
        token_path.write_text(
            _seal_token_for_test(token_path.read_text(encoding="utf-8").strip(), seal_key),
            encoding="utf-8",
        )
        payload = {
            "workdir": str(workdir),
            "env": payload_env,
            "proof_file": str(tmp_path / f"proof-{case}.json"),
            "token_handoff_file": str(token_path),
            "token_handoff_seal_key": seal_key,
            "argv": ["codex"],
        }
        env = os.environ.copy()
        env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()
        env["NPM_CONFIG_PREFIX"] = ""
        env["PATH"] = str(no_codex_path)
        env.pop("HAPAX_CODEX_BIN_PATH", None)
        return subprocess.run(
            [sys.executable, "-c", remote_exec_py],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

    not_a_home = tmp_path / "not-a-home"
    not_a_home.write_text("not a directory\n", encoding="utf-8")
    materialization_result = run_remote_exec(
        "materialization",
        {
            "HOME": str(not_a_home),
            "HAPAX_SESSION_ID": "remote-cache-session",
            "HAPAX_AGENT_ROLE": "cx-amber",
            "HAPAX_METHODOLOGY_DISPATCH_TASK": "task-x",
            "HAPAX_METHODOLOGY_DISPATCH_CLAIM_EPOCH": "1234567890 task-x",
        },
    )
    epoch_result = run_remote_exec(
        "epoch",
        {
            "HOME": str(tmp_path / "home"),
            "HAPAX_SESSION_ID": "remote-cache-session",
            "HAPAX_AGENT_ROLE": "cx-amber",
            "HAPAX_METHODOLOGY_DISPATCH_TASK": "task-x",
        },
    )

    assert materialization_result.returncode == 78
    assert "failed to materialize remote claim cache" in materialization_result.stderr
    assert "remote Codex binary is unavailable" not in materialization_result.stderr
    assert epoch_result.returncode == 78
    assert "without matching local cc-claim epoch" in epoch_result.stderr
    assert "remote Codex binary is unavailable" not in epoch_result.stderr


def test_codex_headless_remote_bootstrap_reports_council_not_git_worktree(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _write_executable(primary / "hooks" / "scripts" / "codex-hook-adapter.sh", "exit 0\n")
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "not a git worktree" in result.stderr


def test_codex_headless_remote_bootstrap_falls_back_to_head_for_missing_base_ref(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    primary_head = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    pwd_file = tmp_path / "codex-pwd.txt"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )
    _write_executable(
        bin_dir / "codex",
        f"""pwd > {pwd_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_WORKTREE_BASE"] = "refs/heads/does-not-exist"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert ssh_log.read_text(encoding="utf-8").splitlines() == [
        "preflight",
        "worktree",
        "preflight",
        "preflight",
        "exec",
    ]
    assert pwd_file.read_text(encoding="utf-8").strip() == str(workdir)
    worktree_head = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert worktree_head == primary_head


def test_codex_headless_remote_bootstrap_reports_git_worktree_add_failure(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    primary = home / "projects" / "hapax-council"
    _init_primary_council_repo(primary)
    subprocess.run(["git", "-C", str(primary), "switch", "-c", "codex/cx-amber"], check=True)
    workdir = home / "projects" / "hapax-council--cx-amber"
    workdir.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    _write_classifying_ssh(
        bin_dir / "ssh",
        ssh_log,
        remove_workdir_on_worktree=workdir,
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(primary)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 75
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "git worktree add failed" in result.stderr


def test_codex_headless_prefers_session_keyed_claim_over_stale_legacy(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    sid = "9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    (cache / "cc-active-task-cx-amber").write_text("old-task\n", encoding="utf-8")
    (cache / f"cc-active-task-cx-amber-{sid}").write_text("task-x\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_SESSION_ID"] = sid

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert args_file.exists()


def test_codex_headless_blocks_retired_relay_without_force(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    relay = cache / "relay"
    cache.mkdir(parents=True)
    relay.mkdir(parents=True)
    (relay / "cx-amber.yaml").write_text("status: retired\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 6
    assert "pass --force to reactivate" in result.stderr
    assert str(relay / "cx-amber.yaml") in result.stderr
    assert not args_file.exists()


def test_codex_headless_blocks_wound_down_relay_session_status(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    relay = cache / "relay"
    cache.mkdir(parents=True)
    relay.mkdir(parents=True)
    relay_file = relay / "cx-amber.yaml"
    relay_file.write_text("session_status: |\n  wind_down_idle\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 6
    assert "retired/wound-down" in result.stderr
    assert f"recheck: sed -n '1,80p' \"{relay_file}\"" in result.stderr
    assert "$RELAY_STATUS_FILE" not in result.stderr
    assert not args_file.exists()


def test_codex_headless_does_not_overmatch_transitional_relay_status(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    relay = cache / "relay"
    cache.mkdir(parents=True)
    relay.mkdir(parents=True)
    (relay / "cx-amber.yaml").write_text("status: retiring-soon\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert args_file.exists()


def test_codex_headless_blocks_suffixed_terminal_relay_status(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    relay = cache / "relay"
    cache.mkdir(parents=True)
    relay.mkdir(parents=True)
    (relay / "cx-amber.yaml").write_text("status: closed_done\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 6
    assert "retired/wound-down" in result.stderr
    assert not args_file.exists()


def test_codex_headless_force_reactivates_retired_relay(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    relay = cache / "relay"
    cache.mkdir(parents=True)
    relay.mkdir(parents=True)
    (relay / "cx-amber.yaml").write_text("status: retired\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "exec --dangerously-bypass-approvals-and-sandbox" in args_file.read_text(
        encoding="utf-8"
    )


def test_codex_headless_force_does_not_bypass_live_pid_guard(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    relay = cache / "relay"
    cache.mkdir(parents=True)
    relay.mkdir(parents=True)
    relay_file = relay / "cx-amber.yaml"
    relay_file.write_text("status: active\n", encoding="utf-8")
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$*" > {args_file}
exit 0
""",
    )

    live = subprocess.Popen(["sleep", "60"])
    try:
        (pid_dir / "cx-amber.pid").write_text(f"{live.pid}\n", encoding="utf-8")
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
        env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
        env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
        env["HAPAX_CODEX_HEADLESS_PID_DIR"] = str(pid_dir)

        result = subprocess.run(
            [
                str(SCRIPT),
                "--task",
                "task-x",
                "--no-claim",
                "--force",
                "cx-amber",
                "governed prompt",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
    finally:
        live.terminate()
        live.wait(timeout=5)

    assert result.returncode == 11
    assert "already live" in result.stderr
    assert not args_file.exists()
    assert (pid_dir / "cx-amber.pid").read_text(encoding="utf-8") == f"{live.pid}\n"
    assert relay_file.read_text(encoding="utf-8") == "status: active\n"


def test_codex_headless_cleanup_removes_owned_pid_and_retires_relay(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    (cache / "relay").mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    council_dir = tmp_path / "council"
    retire_log = tmp_path / "retire.log"
    _write_minimal_council(council_dir, retire_log)

    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "codex", "exit 0\n")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(council_dir)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_CODEX_HEADLESS_PID_DIR"] = str(pid_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not (pid_dir / "cx-amber.pid").exists()
    assert "cx-amber --reason clean exit (codex headless)" in retire_log.read_text(encoding="utf-8")


def test_codex_headless_cleanup_preserves_replaced_pid_without_retiring_relay(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    (cache / "relay").mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    council_dir = tmp_path / "council"
    retire_log = tmp_path / "retire.log"
    _write_minimal_council(council_dir, retire_log)

    bin_dir = tmp_path / "bin"
    _write_executable(
        bin_dir / "codex",
        """pid_file="$HAPAX_CODEX_HEADLESS_PID_DIR/$HAPAX_AGENT_NAME.pid"
for _ in {1..50}; do
  [[ -f "$pid_file" ]] && break
  sleep 0.02
done
printf '999999\\n' > "$pid_file"
exit 0
""",
    )

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HAPAX_COUNCIL_DIR"] = str(council_dir)
    env["HAPAX_CODEX_HEADLESS_ALLOW"] = "1"
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(workdir)
    env["HAPAX_CODEX_HEADLESS_PID_DIR"] = str(pid_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert (pid_dir / "cx-amber.pid").read_text(encoding="utf-8") == "999999\n"
    assert not retire_log.exists()
