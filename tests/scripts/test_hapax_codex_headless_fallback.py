"""Fallback-path tests for the governed Codex headless launcher."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-codex-headless"


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


def _write_codex_access_token(home: Path) -> None:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode())
        .decode()
        .rstrip("=")
    )
    target = home / ".cache" / "hapax" / "codex-oauth" / "access_token"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{header}.{payload}.sig", encoding="utf-8")
    target.chmod(0o600)


def _write_claim_epoch(cache: Path, role: str, task_id: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(f"{task_id}\n", encoding="utf-8")
    (cache / f"cc-claim-epoch-{role}").write_text(
        f"1234567890 {task_id}\n",
        encoding="utf-8",
    )


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
    env["HAPAX_DISPATCH_HOST_FALLBACK"] = "local"
    env["HAPAX_DISPATCH_PROOF_DIR"] = str(tmp_path / "proofs")

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
    assert "HAPAX_DISPATCH_HOST=appendix" in launched_env
    assert "CODEX_ACCESS_TOKEN_PRESENT=yes" in launched_env
    proofs = list((tmp_path / "proofs").glob("*cx-amber-task-x-headless-local.json"))
    assert len(proofs) == 1
    proof = json.loads(proofs[0].read_text(encoding="utf-8"))
    assert proof["fallback"] is True
    assert proof["fallback_reason"] == "dispatch_host_unready:appendix"
    assert proof["requested_host"] == "appendix"


def test_codex_headless_validates_local_fallback_token_before_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".cache" / "hapax").mkdir(parents=True)
    _write_codex_access_token(home)
    token_path = home / ".cache" / "hapax" / "codex-oauth" / "access_token"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = tmp_path / "worktree"
    workdir.mkdir()

    bin_dir = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    claim_log = tmp_path / "claim.log"
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
  rm -f "{token_path}"
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
    env["HAPAX_DISPATCH_HOST"] = "appendix"
    env["HAPAX_DISPATCH_HOST_FALLBACK"] = "local"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 78
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["preflight", "worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "explicit local fallback" in result.stderr
    assert "Codex OAuth access token" in result.stderr
    assert claim_log.read_text(encoding="utf-8") == "task-x\n"
