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
    monkeypatch.setenv("HAPAX_REMOTE_TOKEN_HANDOFF_TTL_SECONDS", "1")
    monkeypatch.setenv(
        "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE",
        str(_write_codex_access_token(tmp_path / "codex-oauth")),
    )


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "codex":
        body = (
            """if [ "${1:-}" = "debug" ] && [ "${2:-}" = "models" ]; then
  if [ -z "${CODEX_ACCESS_TOKEN:-}" ]; then
    echo "missing CODEX_ACCESS_TOKEN" >&2
    exit 78
  fi
  if [ "${HAPAX_FAKE_CODEX_DEBUG_MODELS_RC:-0}" != "0" ]; then
    echo "unauthorized bearer" >&2
    exit "${HAPAX_FAKE_CODEX_DEBUG_MODELS_RC}"
  fi
  printf '%s\n' '{"models":[{"slug":"gpt-5.5"}]}'
  exit 0
fi
"""
            + body
        )
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _write_rejecting_codex(path: Path, fallback_body: str = "exit 0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env bash
if [ "${1:-}" = "debug" ] && [ "${2:-}" = "models" ]; then
  echo "unauthorized bearer" >&2
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
    cleanup_exit: int = 0,
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
if [[ "$remote_cmd" == rm\\ -f*hapax-codex-token-* ]]; then
  exec "{bash_bin}" -c "$remote_cmd"
fi
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
elif "token_handoff_cleanup" in code:
    print("cleanup")
elif "os.execvp" in code:
    print("exec")
else:
    print("unknown")
PY
)"
if [ "$kind" = "cleanup" ]; then
  printf '%s\\n' "$kind" >> "{log_path}"
  if [ "{cleanup_exit}" -ne 0 ]; then
    exit "{cleanup_exit}"
  fi
  exec "{bash_bin}" -c "$remote_cmd"
fi
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
printf 'HAPAX_DISPATCH_CLAIM_SWEEP=%s\\n' "${{HAPAX_DISPATCH_CLAIM_SWEEP:-}}" >> {env_file}
printf 'HAPAX_CLAIM_LEASE_TTL_SECS=%s\\n' "${{HAPAX_CLAIM_LEASE_TTL_SECS:-}}" >> {env_file}
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
    env["HAPAX_DISPATCH_CLAIM_SWEEP"] = "0"
    env["HAPAX_CLAIM_LEASE_TTL_SECS"] = str(2**63 - 1)

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
    assert "CODEX_ACCESS_TOKEN_PRESENT=yes" in launched_env
    assert "HAPAX_DISPATCH_CLAIM_SWEEP=0" in launched_env
    assert f"HAPAX_CLAIM_LEASE_TTL_SECS={2**63 - 1}" in launched_env
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


def test_codex_headless_refuses_local_launch_without_published_token(tmp_path: Path) -> None:
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

    assert result.returncode == 78
    assert "missing or unsafe published Codex OAuth access token" in result.stderr
    assert "next action:" in result.stderr
    assert not codex_called.exists()


def test_codex_headless_refuses_inherited_token_without_published_token(tmp_path: Path) -> None:
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

    assert result.returncode == 78
    assert "missing or unsafe published Codex OAuth access token" in result.stderr
    assert not codex_called.exists()


def test_codex_headless_refuses_unsafe_published_token_file(tmp_path: Path) -> None:
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

    assert result.returncode == 78
    assert "missing or unsafe published Codex OAuth access token" in result.stderr
    assert "owner-only token file" in result.stderr
    assert not codex_called.exists()


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
    assert "rejected by codex debug models" in result.stderr
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
    proven_token = token_file.read_text(encoding="utf-8").strip()
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
    assert used_token.read_text(encoding="utf-8").strip() == proven_token


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
        "cleanup",
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
        "cleanup",
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


def test_codex_headless_remote_token_preflight_refuses_after_claim(tmp_path: Path) -> None:
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
    assert "remote token preflight failed" in result.stderr
    assert "missing_codex_oauth_access_token" in result.stderr
    assert "HAPAX_DISPATCH_HOST_FALLBACK=local" in result.stderr
    assert claim_log.read_text(encoding="utf-8") == "task-x\n"


def test_codex_headless_remote_token_preflight_rejects_unaccepted_bearer_after_claim(
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
    assert "remote token preflight failed" in result.stderr
    assert "codex_bearer_actuation_failed:rc=77" in result.stderr
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
    assert "remote token preflight failed" in result.stderr
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
        "cleanup",
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
    proven_token = token_file.read_text(encoding="utf-8").strip()
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
        "cleanup",
    ]
    assert preflight_count.read_text(encoding="utf-8").strip() == "3"
    assert token_file.read_text(encoding="utf-8").strip() == rotated_token
    assert used_token.read_text(encoding="utf-8").strip() == proven_token


def test_codex_headless_remote_preflight_refuses_preexisting_token_handoff(
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
        assert result.returncode == 75
        assert "refused unsafe preflight-proven Codex OAuth token handoff" in result.stderr
        assert ssh_log.read_text(encoding="utf-8").splitlines() == [
            "preflight",
            "worktree",
            "preflight",
            "preflight",
        ]


def test_codex_headless_remote_cleanup_refuses_traversal_handoff_path() -> None:
    cleanup_py = _extract_remote_python("REMOTE_TOKEN_CLEANUP_PY")
    payload = {"path": "/tmp/hapax-codex-token-../../hapax-codex-headless-cleanup-leak"}
    env = os.environ.copy()
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    result = subprocess.run(
        [sys.executable, "-c", cleanup_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 78
    assert "refusing invalid Codex OAuth token handoff cleanup path" in result.stderr


def test_codex_headless_remote_preflight_self_cleans_unconsumed_token_handoff(
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
        assert handoff.exists()
        sealed = handoff.read_text(encoding="utf-8")
        assert sealed.startswith("hapax-token-sealed-v1.")
        assert sealed != token.read_text(encoding="utf-8").strip()
        for _ in range(40):
            if not handoff.exists():
                break
            time.sleep(0.1)
        assert not handoff.exists()
    finally:
        handoff.unlink(missing_ok=True)


def test_codex_headless_remote_preflight_refuses_invalid_token_handoff_ttl(
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

    assert result.returncode == 78
    assert "refused invalid Codex OAuth token handoff TTL" in result.stderr
    assert not handoff.exists()


def test_codex_headless_remote_preflight_refuses_world_readable_published_token(
    tmp_path: Path,
) -> None:
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
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
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    result = subprocess.run(
        [sys.executable, "-c", remote_preflight_py],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 1
    assert "unsafe_codex_oauth_access_token" in result.stderr


def test_codex_headless_remote_preflight_cleanup_child_clears_bearer_material_before_sleep() -> (
    None
):
    remote_preflight_py = _extract_remote_python("REMOTE_PREFLIGHT_PY")
    child_start = remote_preflight_py.index("if pid == 0:")
    sleep_start = remote_preflight_py.index("time.sleep(ttl)", child_start)
    child_before_sleep = remote_preflight_py[child_start:sleep_start]

    assert 'token=""' in child_before_sleep
    assert 'seal_key=""' in child_before_sleep


def test_codex_headless_remote_preflight_fails_closed_when_self_cleanup_cannot_fork(
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

    assert result.returncode == 78
    assert "failed to schedule Codex OAuth token handoff self-cleanup" in result.stderr
    assert not handoff.exists()


def test_codex_headless_claim_failure_does_not_create_remote_handoff(
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
    assert "failed to delete preflight-proven Codex OAuth token handoff" not in result.stderr
    assert not ssh_log.exists()


def test_codex_headless_remote_handoff_sanitizes_session_id_before_cleanup(
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


def test_codex_headless_remote_exec_fails_if_token_handoff_cleanup_fails(
    tmp_path: Path,
) -> None:
    remote_exec_py = _extract_remote_python("REMOTE_EXEC_PY")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    token_path = _write_codex_access_token(handoff_dir, exp=int(time.time()) + 3600)
    seal_key = "d" * 64
    token_path.write_text(
        _seal_token_for_test(token_path.read_text(encoding="utf-8").strip(), seal_key),
        encoding="utf-8",
    )
    handoff_dir.chmod(0o500)
    payload = {
        "workdir": str(workdir),
        "env": {},
        "proof_file": "",
        "token_handoff_file": str(token_path),
        "token_handoff_seal_key": seal_key,
    }
    env = os.environ.copy()
    env["HAPAX_REMOTE_PAYLOAD"] = base64.b64encode(json.dumps(payload).encode()).decode()

    try:
        result = subprocess.run(
            [sys.executable, "-c", remote_exec_py],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
    finally:
        handoff_dir.chmod(0o700)

    assert result.returncode == 78
    assert "failed to delete preflight-proven Codex OAuth token handoff" in result.stderr
    assert token_path.exists()


def test_codex_headless_remote_exec_fails_if_claim_cache_materialization_fails(
    tmp_path: Path,
) -> None:
    remote_exec_py = _extract_remote_python("REMOTE_EXEC_PY")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
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
        "cleanup",
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
