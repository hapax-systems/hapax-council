"""An old branch uses hooks and scanners from the activated checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN = "Zqxvbn"


def _git(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=False
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    old = tmp_path / "old-branch"
    old.mkdir()
    assert _git(old, "init", "-q").returncode == 0
    assert _git(old, "config", "user.email", "test@example.invalid").returncode == 0
    assert _git(old, "config", "user.name", "test").returncode == 0
    (old / "seed.txt").write_text("seed\n")
    assert _git(old, "add", "-A").returncode == 0
    assert _git(old, "commit", "-qm", "seed").returncode == 0
    assert not (old / "scripts").exists()

    remote = tmp_path / "remote.git"
    assert _git(tmp_path, "init", "--bare", "-q", str(remote)).returncode == 0
    assert _git(old, "remote", "add", "origin", str(remote)).returncode == 0

    activation = tmp_path / "activation"
    scripts = activation / "scripts"
    scripts.mkdir(parents=True)
    (activation / "hooks" / "scripts").mkdir(parents=True)
    for name in ("pre-push", "check-principal-names-diff.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    shutil.copy2(
        REPO_ROOT / "hooks" / "scripts" / "principal-name-map.sh",
        activation / "hooks" / "scripts" / "principal-name-map.sh",
    )
    secret_log = tmp_path / "secret.log"
    (scripts / "hapax-prepush-secret-scan").write_text(
        "#!/usr/bin/env python3\nfrom pathlib import Path\n"
        f"Path({str(secret_log)!r}).write_text('ran\\n')\n"
    )
    active = tmp_path / "active"
    active.symlink_to(activation, target_is_directory=True)
    assert _git(old, "config", "core.hooksPath", str(active / "scripts")).returncode == 0
    registry = tmp_path / "principals.yaml"
    registry.write_text(f"principal-a1: {TOKEN}\n")
    env = dict(os.environ, HAPAX_PRINCIPAL_NAME_MAP=str(registry))
    return old, scripts, secret_log, env


def test_old_branch_push_uses_activation_scanner_and_refuses_registered_token(tmp_path: Path):
    old, scripts, secret_log, env = _fixture(tmp_path)
    clean = _git(old, "push", "-u", "origin", "HEAD:refs/heads/old", env=env)
    assert clean.returncode == 0, clean.stderr
    assert secret_log.read_text() == "ran\n"

    (old / "note.txt").write_text(f"author: {TOKEN}\n")
    assert _git(old, "add", "-A").returncode == 0
    assert _git(old, "commit", "-qm", "registered-token").returncode == 0
    refused = _git(old, "push", "origin", "HEAD:refs/heads/old", env=env)
    assert refused.returncode != 0
    assert "REFUSED" in refused.stderr
    assert TOKEN not in refused.stderr
    assert (scripts / "check-principal-names-diff.py").is_file()
    assert not (old / "scripts").exists()


def test_missing_scanner_everywhere_refuses(tmp_path: Path):
    old, scripts, _secret_log, env = _fixture(tmp_path)
    (scripts / "check-principal-names-diff.py").unlink()
    refused = _git(old, "push", "origin", "HEAD:refs/heads/old", env=env)
    assert refused.returncode != 0
    assert "missing scripts/check-principal-names-diff.py" in refused.stderr
    direct = subprocess.run(
        [str(scripts / "pre-push"), "origin", "file:///dev/null"],
        input="",
        capture_output=True,
        text=True,
        cwd=old,
        env=env,
        check=False,
    )
    assert direct.returncode == 3


def test_missing_secret_scanner_everywhere_refuses_with_exit_3(tmp_path: Path):
    old, scripts, _secret_log, env = _fixture(tmp_path)
    (scripts / "hapax-prepush-secret-scan").unlink()
    direct = subprocess.run(
        [str(scripts / "pre-push"), "origin", "file:///dev/null"],
        input="",
        capture_output=True,
        text=True,
        cwd=old,
        env=env,
        check=False,
    )
    assert direct.returncode == 3
    assert "missing scripts/hapax-prepush-secret-scan" in direct.stderr
    assert "Remedy:" in direct.stderr


def test_branch_scanner_cannot_shadow_activation_scanner(tmp_path: Path):
    old, _scripts, _secret_log, env = _fixture(tmp_path)
    (old / "scripts").mkdir()
    (old / "scripts" / "check-principal-names-diff.py").write_text("raise SystemExit(0)\n")
    (old / "note.txt").write_text(f"author: {TOKEN}\n")
    assert _git(old, "add", "-A").returncode == 0
    assert _git(old, "commit", "-qm", "shadow-attempt").returncode == 0
    refused = _git(old, "push", "origin", "HEAD:refs/heads/old", env=env)
    assert refused.returncode != 0
    assert "REFUSED" in refused.stderr
    assert TOKEN not in refused.stderr


def test_linked_worktree_falls_back_to_primary_for_untracked_secret_scanner(tmp_path: Path):
    primary, scripts, secret_log, env = _fixture(tmp_path)
    linked = tmp_path / "linked"
    assert _git(primary, "worktree", "add", "-qb", "linked", str(linked)).returncode == 0
    (primary / "scripts").mkdir()
    shutil.move(
        str(scripts / "hapax-prepush-secret-scan"),
        str(primary / "scripts" / "hapax-prepush-secret-scan"),
    )
    pushed = _git(linked, "push", "origin", "HEAD:refs/heads/linked", env=env)
    assert pushed.returncode == 0, pushed.stderr
    assert secret_log.read_text() == "ran\n"


def test_precommit_uses_activation_config_even_when_branch_config_differs(tmp_path: Path):
    old, scripts, _secret_log, env = _fixture(tmp_path)
    shutil.copy2(REPO_ROOT / "scripts" / "pre-commit", scripts / "pre-commit")
    (scripts.parent / ".pre-commit-config.yaml").write_text("activation: true\n")
    (old / ".pre-commit-config.yaml").write_text("old-branch: true\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "precommit-args.txt"
    shim = bin_dir / "pre-commit"
    shim.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$PRECOMMIT_ARGS_LOG"\n')
    shim.chmod(0o755)
    env.update(PATH=f"{bin_dir}:{env['PATH']}", PRECOMMIT_ARGS_LOG=str(log))
    assert _git(old, "add", ".pre-commit-config.yaml").returncode == 0
    committed = _git(old, "commit", "-qm", "branch-config", env=env)
    assert committed.returncode == 0, committed.stderr
    args = log.read_text().splitlines()
    assert f"--config={scripts.parent / '.pre-commit-config.yaml'}" in args
    assert "--hook-type=pre-commit" in args


def test_precommit_prefers_activation_framework_over_branch_path(tmp_path: Path):
    old, scripts, _secret_log, env = _fixture(tmp_path)
    shutil.copy2(REPO_ROOT / "scripts" / "pre-commit", scripts / "pre-commit")
    (scripts.parent / ".pre-commit-config.yaml").write_text("repos: []\n")
    active_cli = scripts.parent / ".venv" / "bin" / "pre-commit"
    active_cli.parent.mkdir(parents=True)
    active_log = tmp_path / "active-framework.log"
    active_cli.write_text(f"#!/bin/sh\nprintf 'active\\n' > {active_log}\n")
    active_cli.chmod(0o755)
    branch_bin = tmp_path / "branch-bin"
    branch_bin.mkdir()
    branch_log = tmp_path / "branch-framework.log"
    branch_cli = branch_bin / "pre-commit"
    branch_cli.write_text(f"#!/bin/sh\nprintf 'branch\\n' > {branch_log}\n")
    branch_cli.chmod(0o755)
    env["PATH"] = f"{branch_bin}:{env['PATH']}"
    (old / "new.txt").write_text("clean\n")
    assert _git(old, "add", "new.txt").returncode == 0
    committed = _git(old, "commit", "-qm", "framework-selection", env=env)
    assert committed.returncode == 0, committed.stderr
    assert active_log.read_text() == "active\n"
    assert not branch_log.exists()


def test_precommit_missing_activation_config_refuses_with_next_action(tmp_path: Path):
    old, scripts, _secret_log, env = _fixture(tmp_path)
    shutil.copy2(REPO_ROOT / "scripts" / "pre-commit", scripts / "pre-commit")
    direct = subprocess.run(
        [str(scripts / "pre-commit")],
        capture_output=True,
        text=True,
        cwd=old,
        env=env,
        check=False,
    )
    assert direct.returncode == 1
    assert "missing activation .pre-commit-config.yaml" in direct.stderr
    assert "Remedy:" in direct.stderr
