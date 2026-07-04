"""Tests for the governed Codex headless launcher."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-codex-headless"


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _write_classifying_ssh(
    path: Path,
    log_path: Path,
    *,
    remove_workdir_on_worktree: Path | None = None,
    remove_council_on_worktree: Path | None = None,
    remote_path_on_worktree: Path | None = None,
    remote_path_on_preflight: Path | None = None,
) -> None:
    bash_bin = shutil.which("bash") or "/bin/bash"
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
elif "os.execvp" in code:
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
{run_preflight_with_path}fi
exec "{bash_bin}" -c "$remote_cmd"
""",
    )


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
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

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
    legacy_epoch, _, legacy_task = (
        (cache / "cc-claim-epoch-cx-amber").read_text(encoding="utf-8").strip().partition(" ")
    )
    session_epoch, _, session_task = (
        (cache / f"cc-claim-epoch-cx-amber-{sid}")
        .read_text(encoding="utf-8")
        .strip()
        .partition(" ")
    )
    assert legacy_epoch.isdigit()
    assert session_epoch.isdigit()
    assert legacy_task == "task-x"
    assert session_task == "task-x"


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


def test_codex_headless_creates_missing_remote_default_worktree(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-cx-amber").write_text("task-x\n", encoding="utf-8")
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree", "preflight", "exec"]
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
    # A governed lane running this suite carries its own dispatch task binding;
    # the launcher would adopt it at CODEX_TASK init and skip the no-task guard.
    env.pop("HAPAX_METHODOLOGY_DISPATCH_TASK", None)
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


def test_codex_headless_external_no_claim_requires_live_redemption_authority(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)

    fake_capability = tmp_path / "same-user-capability.json"
    fake_capability.write_text('{"kind":"dispatch","capability_id":"fake"}\n', encoding="utf-8")
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
    env["HAPAX_METHODOLOGY_DISPATCH_CAPABILITY"] = str(fake_capability)
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 17
    assert "requires live methodology dispatch redemption" in result.stderr
    assert "dispatch redemption refused" in result.stderr
    assert not codex_called.exists()


def test_codex_headless_council_symlink_to_external_tree_still_requires_redemption(
    tmp_path: Path,
) -> None:
    # A council-prefixed SPELLING of an external tree must classify by what it
    # resolves to (pwd -P), matching dispatcher-side is_external_project_worktree:
    # the symlink name must not exempt the launch from redemption.
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    real_workdir = home / "projects" / "reins"
    real_workdir.mkdir(parents=True)
    council_spelling = home / "projects" / "hapax-council--reins"
    council_spelling.symlink_to(real_workdir)

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
    env["HAPAX_CODEX_HEADLESS_WORKDIR"] = str(council_spelling)
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 17
    assert "requires live methodology dispatch redemption" in result.stderr
    assert "dispatch redemption refused" in result.stderr
    assert not codex_called.exists()


def test_codex_headless_redemption_verifier_imports_from_launcher_checkout(
    tmp_path: Path,
) -> None:
    # The verifier must import shared.governance.dispatch_redemption from the
    # launcher's own council checkout, never from the caller's cwd (`python3 -`
    # puts cwd at sys.path[0]). From a non-council cwd the launch must reach
    # the redemption verdict (socket refusal), not an import failure.
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)

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
    env["HAPAX_METHODOLOGY_DISPATCH_REDEMPTION_TOKEN"] = "self-minted"
    env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "019f-fake"
    env["HAPAX_METHODOLOGY_DISPATCH_ROUTE_DECISION_REF"] = "route-decision:fake"
    env["HAPAX_METHODOLOGY_DISPATCH_AUTHORITY_CASE"] = "CASE-CAPACITY-ROUTING-001"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--no-claim", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
    )

    assert result.returncode == 17
    assert "cannot import dispatch redemption verifier" not in result.stderr
    assert "dispatch redemption refused" in result.stderr
    assert not codex_called.exists()


def test_codex_headless_external_claim_task_redeems_before_local_claim(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)

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

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
    )

    assert result.returncode == 17
    assert "missing dispatch redemption binding env" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert "missing cc-claim" not in result.stderr
    assert not codex_called.exists()


def test_codex_headless_external_workdir_redeems_before_spoofed_lifecycle_scripts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    workdir = home / "projects" / "reins"
    workdir.mkdir(parents=True)
    spoofed_claim = tmp_path / "spoofed-cc-claim-called"

    _write_executable(
        workdir / "scripts" / "cc-claim",
        f""": > "{spoofed_claim}"
exit 0
""",
    )
    _write_executable(workdir / "scripts" / "cc-close", "exit 0\n")

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

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "--force", "cx-amber", "governed prompt"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=10,
    )

    assert result.returncode == 17
    assert "missing dispatch redemption binding env" in result.stderr
    assert "requires live methodology dispatch redemption" in result.stderr
    assert not spoofed_claim.exists()
    assert not codex_called.exists()


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


def test_codex_headless_remote_bootstrap_refuses_missing_explicit_workdir(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree"]
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "disabled" in result.stderr


def test_codex_headless_remote_bootstrap_reports_missing_remote_council(
    tmp_path: Path,
) -> None:
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "council checkout" in result.stderr


def test_codex_headless_live_pid_blocks_remote_bootstrap_before_ssh(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree", "preflight"]
    assert "remote preflight failed" in result.stderr
    assert "missing_binaries" in result.stderr
    assert "codex" in result.stderr
    assert "next action:" in result.stderr
    assert "hook adapter" in result.stderr
    assert "HAPAX_DISPATCH_HOST_FALLBACK=local" in result.stderr


def test_codex_headless_remote_bootstrap_reports_missing_git(
    tmp_path: Path,
) -> None:
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "git binary missing" in result.stderr


def test_codex_headless_remote_bootstrap_uses_existing_branch_when_present(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree", "preflight", "exec"]
    assert pwd_file.read_text(encoding="utf-8").strip() == str(workdir)
    branch = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "codex/cx-amber"


def test_codex_headless_remote_bootstrap_reports_council_not_git_worktree(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree"]
    assert "remote worktree bootstrap failed" in result.stderr
    assert "not a git worktree" in result.stderr


def test_codex_headless_remote_bootstrap_falls_back_to_head_for_missing_base_ref(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree", "preflight", "exec"]
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
    assert ssh_log.read_text(encoding="utf-8").splitlines() == ["worktree"]
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
