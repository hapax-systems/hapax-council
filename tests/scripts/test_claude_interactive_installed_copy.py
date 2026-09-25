"""Regular published copies use governed source, with synthetic offline admission."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pydantic
import pytest

from tests.scripts.test_claude_interactive_launch_auth import REPO_ROOT, launch_fixture


def installed_fixture(tmp_path, *, explicit):
    env, config, workdir, observed, credential = launch_fixture(tmp_path)
    home = tmp_path / "home"
    release = home / ".cache/hapax/source-activation/releases/test-release"
    for relative in (
        "scripts/hapax-claude-account-live-observe",
        "scripts/hapax-claude-subscription-quota-admission",
        "shared/__init__.py",
        "shared/quota_spend_ledger.py",
        "shared/agentic_trust_boundary.py",
    ):
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    alias = tmp_path / "declared-release" if explicit else release.parents[1] / "worktree"
    alias.symlink_to(release, target_is_directory=True)
    installed = home / ".local/bin"
    installed.mkdir(parents=True)
    for name in ("hapax-claude", "hapax-claude-account-live-observe"):
        shutil.copy2(REPO_ROOT / "scripts" / name, installed / name)
        assert (installed / name).is_file() and not (installed / name).is_symlink()
    # A mutable checkout/cwd is not the installed release binding. If imported,
    # this decoy fails visibly instead of accidentally satisfying the test.
    (workdir / "shared").mkdir()
    (workdir / "shared/__init__.py").write_text("raise RuntimeError('wrong source root')\n")
    env.update(HOME=str(home), HAPAX_COUNCIL_DIR=str(workdir))
    # Keep real third-party dependencies but do not execute the development
    # venv's .pth files: its editable Council install would mask missing roots.
    bootstrap = (
        "import runpy,sys; from pathlib import Path; "
        "script=sys.argv.pop(1); sys.path[0]=str(Path(script).parent); "
        f"sys.path.append({str(Path(pydantic.__file__).parents[1])!r}); "
        "runpy.run_path(script,run_name='__main__')"
    )
    python = tmp_path / "bin/python3"
    python.write_text(
        f"#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} -S -c "
        f'{shlex.quote(bootstrap)} "$@"\n'
    )
    python.chmod(0o700)
    if explicit:
        env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(alias)
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env
    return env, installed, release, alias, workdir, observed, credential


def run_installed(env, installed, workdir, *, terminal):
    return subprocess.run(
        [
            str(installed / "hapax-claude"),
            "--role",
            "beta",
            "--cd",
            str(workdir),
            "--terminal",
            terminal,
            "--task",
            "governed-build",
            "--subscription-only",
            "--model",
            "claude-opus-4-8",
        ],
        cwd=workdir,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("terminal", ["none", "tmux"])
def test_installed_copy_uses_bound_release_without_pythonpath(tmp_path, explicit, terminal):
    env, installed, release, alias, workdir, observed, _ = installed_fixture(
        tmp_path, explicit=explicit
    )
    # A pre-existing tmux server loses the source binding and an activation can
    # move the public alias after preflight. The runner must retain the physical
    # release used before spawn, just as it retains HOME/config/ledger.
    tmux = tmp_path / "bin/tmux"
    tmux.write_text(
        tmux.read_text().replace(
            "for runner; do :; done",
            "for runner; do :; done\n"
            "export HAPAX_SOURCE_ACTIVATE_WORKTREE=/synthetic-wrong-release\n"
            f"ln -sfn -- '{tmp_path / 'unavailable-release'}' '{alias}'",
        )
    )
    result = run_installed(env, installed, workdir, terminal=terminal)
    assert result.returncode == 0, result.stdout + result.stderr
    binding = json.loads(observed.read_text())
    assert binding["oauth_bound"] is True and binding["host_bound"] is True
    assert binding["endpoint"] == "https://api.anthropic.com"
    assert binding["api_auth_present"] is False
    assert binding["hooks_preserved"] is True
    assert "claude-opus-4-8" in binding["argv"] and "max" in binding["argv"]
    assert "PYTHONPATH" not in binding["env_names"]
    assert "synthetic-subscription-access-token" not in result.stdout + result.stderr
    if terminal == "tmux":
        runners = list((tmp_path / "home/.cache/hapax/claude-spawns").glob("*.sh"))
        assert len(runners) == 1
        assert str(release) in runners[0].read_text()
        assert "synthetic-subscription-access-token" not in runners[0].read_text()


@pytest.mark.parametrize(
    "defect", ["missing-release", "missing-module", "wrong-credential", "missing-ledger"]
)
def test_installed_copy_cannot_replace_missing_proof_with_ambient_source(tmp_path, defect):
    env, installed, release, _, workdir, observed, credential = installed_fixture(
        tmp_path, explicit=True
    )
    if defect == "missing-release":
        env["HAPAX_SOURCE_ACTIVATE_WORKTREE"] = str(tmp_path / "absent")
        # Even an importable ambient source tree cannot replace this binding.
        env["PYTHONPATH"] = str(REPO_ROOT)
    elif defect == "missing-module":
        (release / "shared/quota_spend_ledger.py").unlink()
        env["PYTHONPATH"] = str(REPO_ROOT)
    elif defect == "wrong-credential":
        data = json.loads(credential.read_text())
        data["claudeAiOauth"]["accessToken"] = "synthetic-distinct-account-b"
        credential.write_text(json.dumps(data))
    else:
        Path(env["HAPAX_QUOTA_SPEND_LEDGER"]).unlink()
    result = run_installed(env, installed, workdir, terminal="tmux")
    assert result.returncode == 4, result.stdout + result.stderr
    assert "Next action:" in result.stderr
    assert not observed.exists()
    assert not (tmp_path / "home/.cache/hapax/claude-spawns").exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_installed_observer_resolves_writer_from_same_release(tmp_path, explicit):
    env, installed, release, _, workdir, _, _ = installed_fixture(tmp_path, explicit=explicit)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import runpy,sys; m=runpy.run_path(sys.argv[1]); print(m['ADMISSION_WRITER'])",
            str(installed / "hapax-claude-account-live-observe"),
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(
        release / "scripts/hapax-claude-subscription-quota-admission"
    )


def test_source_checkout_keeps_its_own_implementation(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import runpy,sys; m=runpy.run_path(sys.argv[1]); print(m['ADMISSION_WRITER'])",
            str(REPO_ROOT / "scripts/hapax-claude-account-live-observe"),
        ],
        cwd=tmp_path,
        env={"HAPAX_SOURCE_ACTIVATE_WORKTREE": str(tmp_path / "absent")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(
        REPO_ROOT / "scripts/hapax-claude-subscription-quota-admission"
    )
