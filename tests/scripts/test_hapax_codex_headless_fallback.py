"""Fallback-path tests for the governed Codex headless launcher."""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from tests.scripts.launcher_activation_fixture import install_launcher_activation

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-codex-headless"

_DISPATCH_BINDING_ENV = {
    "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "dispatch-message",
    "HAPAX_CLAIM_DISPATCH_BINDING_HASH": "b" * 64,
    "HAPAX_CLAIM_DISPATCH_PLATFORM": "codex",
    "HAPAX_CLAIM_DISPATCH_MODE": "headless",
    "HAPAX_CLAIM_DISPATCH_PROFILE": "full",
    "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": "CASE-TEST-001",
    "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": "dispatch-test",
    "HAPAX_CLAIM_DISPATCH_TASK_PATH": "/tmp/task-x.md",
    "HAPAX_CLAIM_DISPATCH_TASK_SHA256": "c" * 64,
    "HAPAX_CLAIM_DISPATCH_PARENT_SPEC": "/tmp/parent.md",
    "HAPAX_CLAIM_DISPATCH_PARENT_SPEC_SHA256": "d" * 64,
    "HAPAX_CLAIM_DISPATCH_LANE_SESSION": "hapax-codex-cx-amber",
    "HAPAX_CLAIM_DISPATCH_LANE_GENERATION": "session:test",
    "HAPAX_CLAIM_DISPATCH_CLAIM_PROJECTION_SHA256": "e" * 64,
    "HAPAX_CLAIM_DISPATCH_RELAY_PROJECTION_SHA256": "f" * 64,
}


@pytest.fixture(autouse=True)
def _activated_claim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HAPAX_CLAIM_RESUME_SESSION_ID", raising=False)
    for name, value in install_launcher_activation(tmp_path / "activation-home").items():
        monkeypatch.setenv(name, value)
    for name, value in _DISPATCH_BINDING_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("HAPAX_SESSION_ID", "codex-test-session")


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "cc-claim":
        body = (
            """case "${1:-}" in
  --dispatch-protocol-version)
    printf '%s\n' 'hapax-claim-dispatch-v1'
    exit 0
    ;;
  --verify-dispatch-binding)
    exit "${HAPAX_FAKE_CC_CLAIM_VERIFY_RC:-0}"
    ;;
esac
if [ "${HAPAX_FAKE_CC_CLAIM_NO_PUBLISH:-0}" != "1" ]; then
  mkdir -p "$HOME/.cache/hapax"
  role="${HAPAX_AGENT_ROLE:-${CODEX_ROLE:-}}"
  sid="${HAPAX_SESSION_ID:-}"
  for key in "$role" "$role-$sid"; do
    printf '%s\n' "$1" > "$HOME/.cache/hapax/cc-active-task-$key"
    printf '1234567890 %s\n' "$1" > "$HOME/.cache/hapax/cc-claim-epoch-$key"
    printf '{}\n' > "$HOME/.cache/hapax/cc-claim-dispatch-$key.json"
  done
fi
"""
            + body
        )
    elif path.name == "codex":
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


def _write_codex_access_token(home: Path, signature: str = "sig") -> None:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode())
        .decode()
        .rstrip("=")
    )
    target = home / ".cache" / "hapax" / "codex-oauth" / "access_token"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{header}.{payload}.{signature}", encoding="utf-8")
    target.chmod(0o600)


def _write_claim_epoch(cache: Path, role: str, task_id: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for key in (role, f"{role}-{os.environ.get('HAPAX_SESSION_ID', 'codex-test-session')}"):
        (cache / f"cc-active-task-{key}").write_text(f"{task_id}\n", encoding="utf-8")
        (cache / f"cc-claim-epoch-{key}").write_text(
            f"1234567890 {task_id}\n",
            encoding="utf-8",
        )
        (cache / f"cc-claim-dispatch-{key}.json").write_text("{}\n", encoding="utf-8")


def _remote_dispatch_host() -> str:
    current_host = socket.gethostname().split(".", 1)[0]
    return "podium" if current_host == "hapax-appendix" else "appendix"


def test_codex_headless_takes_explicit_local_fallback_after_appendix_preflight_failure(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_claim_epoch(cache, "cx-amber", "task-x")
    _write_codex_access_token(home)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "codex-args.txt"
    env_file = tmp_path / "codex-env.txt"
    _write_executable(
        bin_dir / "ssh",
        "exit 255\n",
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
    remote_host = _remote_dispatch_host()
    env["HAPAX_DISPATCH_HOST"] = remote_host
    env["HAPAX_DISPATCH_HOST_FALLBACK"] = "local"
    env["HAPAX_CLAIM_RESUME_SESSION_ID"] = "codex-test-session"
    env["HAPAX_DISPATCH_PROOF_DIR"] = str(tmp_path / "proofs")
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
    assert "explicit local fallback" in result.stderr
    assert "exec --dangerously-bypass-approvals-and-sandbox" in args_file.read_text(
        encoding="utf-8"
    )
    launched_env = env_file.read_text(encoding="utf-8")
    assert "LOGOS_BASE_URL=http://localhost:8051/api" in launched_env
    assert f"HAPAX_DISPATCH_HOST={remote_host}" in launched_env
    assert "CODEX_ACCESS_TOKEN_PRESENT=yes" not in launched_env
    assert "CODEX_HOME_PRESENT=yes" not in launched_env
    assert "CODEX_API_KEY_PRESENT=yes" not in launched_env
    assert "OPENAI_API_KEY_PRESENT=yes" not in launched_env
    proofs = list((tmp_path / "proofs").glob("*cx-amber-task-x-headless-local.json"))
    assert len(proofs) == 1
    proof = json.loads(proofs[0].read_text(encoding="utf-8"))
    assert proof["fallback"] is True
    assert proof["fallback_reason"] == f"dispatch_host_unready:{remote_host}"
    assert proof["requested_host"] == remote_host


def test_codex_headless_validates_local_fallback_saved_auth_before_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax").mkdir(parents=True)
    _write_codex_access_token(home)
    token_path = home / ".cache" / "hapax" / "codex-oauth" / "access_token"
    token_path.unlink()
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    claim_log = tmp_path / "claim.log"
    _write_executable(bin_dir / "codex", "exit 0\n")
    _write_executable(
        bin_dir / "ssh",
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
elif "os.execvp" in code:
    print("exec")
else:
    print("unknown")
PY
)"
printf '%s\\n' "$kind" >> "{ssh_log}"
if [ "$kind" = "worktree" ]; then
  exit 255
fi
exec bash -c "$remote_cmd"
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
    env["HAPAX_DISPATCH_HOST"] = _remote_dispatch_host()
    env["HAPAX_DISPATCH_HOST_FALLBACK"] = "local"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "explicit local fallback" in result.stderr
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert claim_log.read_text(encoding="utf-8").strip() == "task-x"


def test_codex_headless_strips_bearer_on_local_fallback_after_claim(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    _write_codex_access_token(home, signature="preclaim")
    token_path = home / ".cache" / "hapax" / "codex-oauth" / "access_token"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    exec_token_file = tmp_path / "codex-exec-token.txt"
    claim_log = tmp_path / "claim.log"
    _write_executable(bin_dir / "ssh", "exit 255\n")
    _write_executable(
        bin_dir / "codex",
        f"""printf '%s\\n' "$CODEX_ACCESS_TOKEN" > "{exec_token_file}"
exit 0
""",
    )
    _write_executable(
        workdir / "scripts" / "cc-claim",
        f"""printf '%s\\n' "$*" >> "{claim_log}"
cat > "{token_path}" <<'EOF'
rotated.after.claim.token
EOF
chmod 600 "{token_path}"
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
    env["HAPAX_DISPATCH_HOST"] = _remote_dispatch_host()
    env["HAPAX_DISPATCH_HOST_FALLBACK"] = "local"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "remote Codex auth preflight failed" in result.stderr
    assert "explicit local fallback" in result.stderr
    assert claim_log.read_text(encoding="utf-8").strip() == "task-x"
    assert token_path.read_text(encoding="utf-8") == "rotated.after.claim.token\n"
    assert exec_token_file.read_text(encoding="utf-8") == "\n"
