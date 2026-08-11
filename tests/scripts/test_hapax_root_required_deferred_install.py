from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-root-required-deferred-install"
PACKAGE = "oom-containment"
MANIFEST = Path("config/root-required/oom-containment.files")
INSTALLER = Path("scripts/install-p0-oom-containment")
APCUPSD_PACKAGE = "apcupsd-power-alerts"
APCUPSD_MANIFEST = Path("config/root-required/apcupsd-power-alerts.files")
APCUPSD_INSTALLER = Path("scripts/install-apcupsd-power-alerts")


@dataclass
class DeferredFixture:
    package: str
    manifest: Path
    installer: Path
    repo: Path
    repo_alias: Path
    state_root: Path
    defer_root: Path
    stage: Path
    receipt: Path
    sudo: Path
    sudo_calls: Path
    installer_marker: Path
    sha: str
    env: dict[str, str]

    def run(self, *, expected_sha: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(SCRIPT),
                "--package",
                self.package,
                "--expected-sha",
                expected_sha or self.sha,
                "--activation-release",
                str(self.repo),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.env,
        )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def _fixture(tmp_path: Path, *, package: str = PACKAGE) -> DeferredFixture:
    manifest_rel, installer_rel = (
        (MANIFEST, INSTALLER) if package == PACKAGE else (APCUPSD_MANIFEST, APCUPSD_INSTALLER)
    )
    repo = tmp_path / "activation-release"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@hapax.local")
    _git(repo, "config", "user.name", "Hapax Tests")
    installer_marker = tmp_path / "installer-ran"
    environment_marker = tmp_path / "installer-environment"
    manifest = repo / manifest_rel
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f"{manifest_rel.as_posix()}\n{installer_rel.as_posix()}\n", encoding="utf-8"
    )
    installer = repo / installer_rel
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "#!/usr/bin/bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$HAPAX_ROOT_REQUIRED_PACKAGE_SHA\" > {installer_marker}\n"
        f"/usr/bin/env | /usr/bin/sort > {environment_marker}\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "root package")
    sha = _git(repo, "rev-parse", "HEAD")

    repo_alias = tmp_path / "activation-alias"
    repo_alias.symlink_to(repo, target_is_directory=True)
    state_root = tmp_path / "state"
    receipt = state_root / "desired-receipts" / f"{package}.sha"
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(f"{sha}\n".encode())
    defer_root = tmp_path / "deferred"
    stage = defer_root / sha / package
    for rel in (manifest_rel, installer_rel):
        destination = stage / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / rel, destination)
    (stage / ".hapax-root-required-package-sha").write_bytes(f"{sha}\n".encode())
    (stage / "RUNBOOK.txt").write_text("test fixture\n", encoding="utf-8")

    sudo_calls = tmp_path / "sudo-calls"
    sudo = tmp_path / "sudo"
    sudo.write_text(
        f"#!/usr/bin/bash\nprintf '%s\\n' \"$*\" >> {sudo_calls}\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    env = {
        **os.environ,
        "HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_TEST_MODE": "1",
        "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
        "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
        "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo_alias),
        "HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_SUDO": str(sudo),
        "BASH_ENV": str(tmp_path / "hostile-bash-env"),
        "GIT_DIR": str(tmp_path / "hostile-git-dir"),
        "GIT_WORK_TREE": str(tmp_path / "hostile-git-work-tree"),
        "GIT_OBJECT_DIRECTORY": str(tmp_path / "hostile-git-objects"),
        "PYTHONPATH": str(tmp_path / "hostile-python-path"),
    }
    return DeferredFixture(
        package=package,
        manifest=manifest_rel,
        installer=installer_rel,
        repo=repo,
        repo_alias=repo_alias,
        state_root=state_root,
        defer_root=defer_root,
        stage=stage,
        receipt=receipt,
        sudo=sudo,
        sudo_calls=sudo_calls,
        installer_marker=installer_marker,
        sha=sha,
        env=env,
    )


def test_authenticated_deferred_install_executes_git_materialized_installer(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    assert fixture.installer_marker.read_text(encoding="utf-8").strip() == fixture.sha
    assert fixture.sudo_calls.read_text(encoding="utf-8").splitlines() == ["-v"]
    child_environment = (tmp_path / "installer-environment").read_text(encoding="utf-8")
    for unsafe in (
        "BASH_ENV=",
        "GIT_DIR=",
        "GIT_WORK_TREE=",
        "GIT_OBJECT_DIRECTORY=",
        "PYTHONPATH=",
    ):
        assert unsafe not in child_environment
    execution_root = fixture.state_root / ".deferred-install-exec"
    assert execution_root.is_dir()
    assert list(execution_root.iterdir()) == []


def test_apcupsd_deferral_uses_the_same_authenticated_entrypoint(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, package=APCUPSD_PACKAGE)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    assert fixture.installer_marker.read_text(encoding="utf-8").strip() == fixture.sha


def test_expected_sha_mismatch_refuses_before_sudo(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    result = fixture.run(expected_sha="f" * 40)

    assert result.returncode == 1
    assert "desired package receipt changed" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_test_selector_is_refused_without_isolated_test_mode(tmp_path: Path) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("HAPAX_ROOT_REQUIRED_") and key != "HAPAX_POST_MERGE_ROOT_DEFER_DIR"
    }
    env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_SUDO"] = "/bin/true"

    result = subprocess.run(
        [
            str(SCRIPT),
            "--package",
            PACKAGE,
            "--expected-sha",
            "f" * 40,
            "--activation-release",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "test selectors are refused outside isolated test mode" in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        b"../outside\n",
        b"A" * 40 + b"\n",
        b"a" * 39 + b"\n",
        b"a" * 41 + b"\n",
        b"a" * 20 + b" " + b"a" * 20 + b"\n",
        b"a" * 40 + b"\n" + b"b" * 40 + b"\n",
        b"a" * 40,
        b"a" * 20 + b"\x00" + b"a" * 19 + b"\n",
    ],
)
def test_malformed_receipt_refuses_before_sudo_or_execution(tmp_path: Path, content: bytes) -> None:
    fixture = _fixture(tmp_path)
    fixture.receipt.write_bytes(content)

    result = fixture.run()

    assert result.returncode == 1
    assert "exactly 40 lowercase hex characters and one newline" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_symlinked_receipt_refuses_before_sudo(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    target = tmp_path / "receipt-target"
    target.write_bytes(f"{fixture.sha}\n".encode())
    fixture.receipt.unlink()
    fixture.receipt.symlink_to(target)

    result = fixture.run()

    assert result.returncode == 1
    assert "single-link non-symlink regular file" in result.stderr
    assert not fixture.sudo_calls.exists()


@pytest.mark.parametrize("component", ["sha", "package", "installer"])
def test_symlinked_stage_component_refuses_before_sudo(tmp_path: Path, component: str) -> None:
    fixture = _fixture(tmp_path)
    if component == "sha":
        target = tmp_path / "sha-target"
        shutil.move(fixture.stage.parent, target)
        fixture.stage.parent.symlink_to(target, target_is_directory=True)
    elif component == "package":
        target = tmp_path / "package-target"
        shutil.move(fixture.stage, target)
        fixture.stage.symlink_to(target, target_is_directory=True)
    else:
        installer = fixture.stage / INSTALLER
        target = tmp_path / "installer-target"
        shutil.move(installer, target)
        installer.symlink_to(target)

    result = fixture.run()

    assert result.returncode == 1
    assert not fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_substituted_staged_installer_never_executes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    attack_marker = tmp_path / "substituted-installer-ran"
    staged_installer = fixture.stage / INSTALLER
    staged_installer.write_text(f"#!/usr/bin/bash\ntouch {attack_marker}\n", encoding="utf-8")
    staged_installer.chmod(0o755)

    result = fixture.run()

    assert result.returncode == 1
    assert "staged package bytes do not match" in result.stderr
    assert not fixture.sudo_calls.exists()
    assert not attack_marker.exists()
    assert not fixture.installer_marker.exists()


def _hook(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/bash\nset -euo pipefail\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_receipt_change_during_sudo_warmup_refuses_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "swap-receipt",
        f"printf '%s\\n' {'b' * 40} > {fixture.receipt}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "receipt changed during sudo warmup" in result.stderr
    assert fixture.sudo_calls.exists()
    assert not fixture.installer_marker.exists()


def test_stage_change_during_sudo_warmup_refuses_execution(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    hook = _hook(
        tmp_path / "swap-stage",
        f"printf '%s\\n' '#!/usr/bin/bash' 'exit 0' > {fixture.stage / INSTALLER}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 1
    assert "staged package bytes do not match" in result.stderr
    assert not fixture.installer_marker.exists()


def test_activation_alias_swap_cannot_change_pinned_release(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    replacement = tmp_path / "replacement-release"
    shutil.copytree(fixture.repo, replacement)
    hook = _hook(
        tmp_path / "swap-alias",
        f"rm {fixture.repo_alias}\nln -s {replacement} {fixture.repo_alias}",
    )
    fixture.env["HAPAX_ROOT_REQUIRED_DEFERRED_INSTALL_AFTER_SUDO_HOOK"] = str(hook)

    result = fixture.run()

    assert result.returncode == 0, result.stderr
    assert fixture.installer_marker.exists()


def test_missing_explicit_test_defer_root_cannot_self_anchor_to_drain(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture.env.pop("HAPAX_POST_MERGE_ROOT_DEFER_DIR")
    fixture.env["HAPAX_ROOT_REQUIRED_DRAIN_DIR"] = str(fixture.stage)

    result = fixture.run()

    assert result.returncode == 1
    assert "HAPAX_POST_MERGE_ROOT_DEFER_DIR must be an explicit absolute test path" in result.stderr
    assert not fixture.sudo_calls.exists()
