"""Tests for the governed Codex headless launcher."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-codex-headless"


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def test_codex_headless_runs_on_appendix_via_remote_payload(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("task-x\n", encoding="utf-8")
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
    assert "exec --dangerously-bypass-approvals-and-sandbox" in args_file.read_text(
        encoding="utf-8"
    )
    launched_env = env_file.read_text(encoding="utf-8")
    assert "LOGOS_BASE_URL=http://192.168.68.85:8051/api" in launched_env
    assert "HAPAX_DISPATCH_HOST=local" in launched_env
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
    sid = proof["session_id"]
    assert (cache / f"session-role-{sid}").read_text(encoding="utf-8") == "cx-amber\n"
    assert (cache / f"cc-active-task-cx-amber-{sid}").read_text(encoding="utf-8") == "task-x\n"


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
