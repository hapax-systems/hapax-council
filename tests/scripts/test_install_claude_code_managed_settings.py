"""The managed-settings installer installs committed bytes from the active release, as root only.

Every unsafe case installs nothing and names a next action.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "config/root-required/claude-code-managed-settings.files"
INSTALLER_REL = "scripts/install-claude-code-managed-settings"
GIT = "/usr/bin/git"
MAIN_REF = "refs/remotes/origin/main"
LIB = "usr/local/lib/hapax/claude-code-managed-settings/shared"
UNIT = "hapax-claude-code-managed-settings-sync"


def package_files() -> list[str]:
    return [
        line
        for line in MANIFEST.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


@dataclass
class Box:
    home: Path
    canon: Path
    dest: Path
    systemctl_log: Path
    systemctl: Path
    tmp: Path
    env: dict[str, str]

    def git(self, repo: Path, *args: str) -> str:
        done = subprocess.run(
            [GIT, "-C", str(repo), *args], check=True, capture_output=True, env=self.env
        )
        return done.stdout.decode().strip()

    def commit(self, extra: str = "") -> str:
        for rel in package_files():
            path = self.canon / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((REPO_ROOT / rel).read_bytes())
            path.chmod((REPO_ROOT / rel).stat().st_mode & 0o777)
        (self.canon / "extra").write_text(extra)
        self.git(self.canon, "add", "-A")
        self.git(self.canon, "commit", "-q", "--allow-empty", "-m", "c")
        return self.git(self.canon, "rev-parse", "HEAD")

    def release(self, sha: str, *, main: str | None = None) -> Path:
        self.git(self.canon, "update-ref", MAIN_REF, main or sha)
        release = self.home / ".cache/hapax/source-activation/releases" / sha
        release.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.canon, "worktree", "add", "-q", "--detach", str(release), sha)
        link = self.home / ".cache/hapax/source-activation/worktree"
        if link.is_symlink():
            link.unlink()
        link.symlink_to(release)
        return release

    @property
    def receipt(self) -> Path:
        return (
            self.home
            / ".local/state/hapax/root-required/installed-receipts"
            / "claude-code-managed-settings.sha"
        )

    def install(self, source: Path, *, as_root: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "TMPDIR": str(self.tmp),
            "HAPAX_CCMS_OWNER_UID": str(os.getuid()),
            "HAPAX_CCMS_OWNER_GID": str(os.getgid()),
            "HAPAX_CCMS_OWNER_HOME": str(self.home),
            "HAPAX_CCMS_DEST_ROOT": str(self.dest),
            "HAPAX_CCMS_ROOT_UID": str(os.getuid()),
            "HAPAX_CCMS_ROOT_GID": str(os.getgid()),
            "HAPAX_CCMS_SYSTEMCTL": str(self.systemctl),
        }
        if as_root:
            env["HAPAX_CCMS_TEST_ACTUAL_UID"] = "0"
        return subprocess.run(
            ["/usr/bin/bash", str(source / INSTALLER_REL)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def installed_nothing(self) -> bool:
        return list(self.dest.rglob("*")) == [] and not self.systemctl_log.exists()


def make_box(tmp_path: Path, *, fail_start: bool = False) -> Box:
    home = tmp_path / "home"
    canon = home / "projects" / "council"
    canon.mkdir(parents=True)
    dest = tmp_path / "root"
    dest.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    log = tmp_path / "systemctl.log"
    systemctl = tmp_path / "systemctl"
    fail = '[ "$1" = start ] && exit 1\n' if fail_start else ""
    systemctl.write_text(f'#!/usr/bin/bash\nprintf "%s\\n" "$*" >> "{log}"\n{fail}exit 0\n')
    systemctl.chmod(0o755)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.org",
    }
    subprocess.run([GIT, "init", "-q", "-b", "main", str(canon)], check=True, env=env)
    return Box(home, canon, dest, log, systemctl, scratch, env)


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return make_box(tmp_path)


def assert_refused(done: subprocess.CompletedProcess[str], box: Box) -> None:
    assert done.returncode != 0
    assert "next action:" in done.stderr, done.stderr
    assert box.installed_nothing()
    assert not box.receipt.exists()


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_installs_committed_package_files_with_exact_modes(box: Box) -> None:
    head = box.commit()
    release = box.release(head)
    done = box.install(release)
    assert done.returncode == 0, done.stderr
    expected = {
        f"{LIB}/managed_settings_deny.py": ("shared/managed_settings_deny.py", 0o644),
        f"{LIB}/managed_settings_sync.py": ("shared/managed_settings_sync.py", 0o644),
        f"usr/local/sbin/{UNIT}": (f"scripts/{UNIT}", 0o755),
        f"etc/systemd/system/{UNIT}.service": (f"systemd/units/{UNIT}.service", 0o644),
        f"etc/systemd/system/{UNIT}.timer": (f"systemd/units/{UNIT}.timer", 0o644),
    }
    for installed, (rel, want_mode) in expected.items():
        path = box.dest / installed
        assert path.read_bytes() == (REPO_ROOT / rel).read_bytes(), installed
        assert mode(path) == want_mode, installed
    assert (box.dest / LIB / "__init__.py").read_bytes() == b""
    assert mode(box.dest / LIB / "__init__.py") == 0o644
    for directory in ("etc/claude-code", "etc/claude-code/managed-settings.d", LIB):
        assert mode(box.dest / directory) == 0o755, directory
    assert box.systemctl_log.read_text().splitlines() == [
        "daemon-reload",
        f"start {UNIT}.service",
        f"enable --now {UNIT}.timer",
    ]
    assert box.receipt.read_text().strip() == head


def test_the_installed_library_imports_without_the_repository(box: Box, tmp_path: Path) -> None:
    release = box.release(box.commit())
    assert box.install(release).returncode == 0
    library = box.dest / LIB.removesuffix("/shared")
    probe = (
        f"import sys; sys.path.insert(0, {str(library)!r}); "
        "import shared.managed_settings_sync as m; print(m.__file__)"
    )
    done = subprocess.run(
        ["/usr/bin/python3", "-I", "-c", probe],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(box.dest / LIB / "managed_settings_sync.py")


def test_refuses_without_root(box: Box) -> None:
    release = box.release(box.commit())
    assert_refused(box.install(release, as_root=False), box)


def test_refuses_a_release_that_is_not_the_active_one(box: Box) -> None:
    older = box.release(box.commit())
    box.release(box.commit(extra="newer"))
    assert_refused(box.install(older), box)


def test_refuses_a_checkout_that_is_not_a_release(box: Box) -> None:
    box.release(box.commit())
    assert_refused(box.install(box.canon), box)


def test_refuses_a_head_that_is_not_an_ancestor_of_origin_main(box: Box) -> None:
    base = box.commit()
    lane = box.commit(extra="lane change")
    release = box.release(lane, main=base)
    assert_refused(box.install(release), box)


def test_refuses_a_release_not_at_its_named_commit(box: Box) -> None:
    first = box.commit()
    second = box.commit(extra="second")
    release = box.release(second)
    box.git(release, "checkout", "-q", "--detach", first)
    assert_refused(box.install(release), box)


def test_installs_committed_bytes_not_working_tree_edits(box: Box) -> None:
    release = box.release(box.commit())
    (release / "shared/managed_settings_sync.py").write_text("raise SystemExit('lane edit')\n")
    (release / f"systemd/units/{UNIT}.service").write_text("[Service]\nExecStart=/bin/sh\n")
    done = box.install(release)
    assert done.returncode == 0, done.stderr
    assert (box.dest / LIB / "managed_settings_sync.py").read_bytes() == (
        REPO_ROOT / "shared/managed_settings_sync.py"
    ).read_bytes()
    assert (box.dest / f"etc/systemd/system/{UNIT}.service").read_bytes() == (
        REPO_ROOT / f"systemd/units/{UNIT}.service"
    ).read_bytes()


def test_a_failing_first_sync_enables_no_timer_and_leaves_no_receipt(tmp_path: Path) -> None:
    box = make_box(tmp_path, fail_start=True)
    release = box.release(box.commit())
    done = box.install(release)
    assert done.returncode != 0
    assert "next action:" in done.stderr
    assert not any("enable" in line for line in box.systemctl_log.read_text().splitlines())
    assert not box.receipt.exists()
