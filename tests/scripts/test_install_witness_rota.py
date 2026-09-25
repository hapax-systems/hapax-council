"""The O3 installer installs the signing holder and the witness rota as root-owned copies.

It pins a root-owned agy copy, records its sha256 and version, and runs only as root from the
active release. Every unsafe case installs nothing and names a next action.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_REL = "scripts/install-witness-rota"
GIT = "/usr/bin/git"
MAIN_REF = "refs/remotes/origin/main"
HOLDER_LIB = "usr/local/lib/hapax/signing-holder/shared"
ROTA = "usr/local/lib/hapax/witness-rota"
ROTA_LIB = f"{ROTA}/shared"
CRED = "etc/credstore.encrypted/hapax-public-gate-authority-hmac-key"
PACKAGE = (
    "shared/public_gate_receipts.py",
    "shared/signing_holder.py",
    "shared/witness_receipt.py",
    "shared/witness_rota.py",
    "scripts/hapax-agy-reviewer",
    "scripts/hapax-signing-holder",
    "scripts/hapax-witness-rota",
    INSTALLER_REL,
    "systemd/units/hapax-signing-holder.socket",
    "systemd/units/hapax-signing-holder@.service",
    "systemd/units/hapax-witness-rota@.service",
    "systemd/units/hapax-witness-rota.timer",
)
AGY = b"#!/bin/sh\necho 1.2.11\n"


@dataclass
class Box:
    home: Path
    canon: Path
    dest: Path
    log: Path
    systemctl: Path
    scratch: Path
    env: dict[str, str]

    def git(self, repo: Path, *args: str) -> str:
        done = subprocess.run(
            [GIT, "-C", str(repo), *args], check=True, capture_output=True, env=self.env
        )
        return done.stdout.decode().strip()

    def commit(self, extra: str = "") -> str:
        for rel in PACKAGE:
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
        return self.home / ".local/state/hapax/root-required/installed-receipts/witness-rota.sha"

    def install(self, source: Path, *, as_root: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "TMPDIR": str(self.scratch),
            "HAPAX_WR_OWNER_UID": str(os.getuid()),
            "HAPAX_WR_OWNER_GID": str(os.getgid()),
            "HAPAX_WR_OWNER_HOME": str(self.home),
            "HAPAX_WR_DEST_ROOT": str(self.dest),
            "HAPAX_WR_ROOT_UID": str(os.getuid()),
            "HAPAX_WR_ROOT_GID": str(os.getgid()),
            "HAPAX_WR_SYSTEMCTL": str(self.systemctl),
        }
        if as_root:
            env["HAPAX_WR_TEST_ACTUAL_UID"] = "0"
        return subprocess.run(
            ["/usr/bin/bash", str(source / INSTALLER_REL)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def installed(self) -> list[Path]:
        return sorted(p for p in self.dest.rglob("*") if p.is_file() and not str(p).endswith(CRED))


@pytest.fixture
def box(tmp_path: Path) -> Box:
    home = tmp_path / "home"
    canon = home / "projects" / "council"
    canon.mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "agy").write_bytes(AGY)
    (home / ".local" / "bin" / "agy").chmod(0o755)
    dest = tmp_path / "root"
    (dest / CRED).parent.mkdir(parents=True)
    (dest / CRED).write_text("encrypted")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    log = tmp_path / "systemctl.log"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f'#!/usr/bin/bash\nprintf "%s\\n" "$*" >> "{log}"\n')
    systemctl.chmod(0o755)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.org",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.org",
    }
    subprocess.run([GIT, "init", "-q", "-b", "main", str(canon)], check=True, env=env)
    return Box(home, canon, dest, log, systemctl, scratch, env)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def assert_refused(done: subprocess.CompletedProcess[str], box: Box) -> None:
    assert done.returncode != 0
    assert "next action:" in done.stderr, done.stderr
    assert box.installed() == []
    assert not box.log.exists() and not box.receipt.exists()


def test_installs_the_holder_and_rota_as_root_owned_copies(box: Box) -> None:
    head = box.commit()
    done = box.install(box.release(head))
    assert done.returncode == 0, done.stderr
    expected = {
        f"{HOLDER_LIB}/public_gate_receipts.py": ("shared/public_gate_receipts.py", 0o644),
        f"{HOLDER_LIB}/signing_holder.py": ("shared/signing_holder.py", 0o644),
        f"{ROTA_LIB}/public_gate_receipts.py": ("shared/public_gate_receipts.py", 0o644),
        f"{ROTA_LIB}/signing_holder.py": ("shared/signing_holder.py", 0o644),
        f"{ROTA_LIB}/witness_receipt.py": ("shared/witness_receipt.py", 0o644),
        f"{ROTA_LIB}/witness_rota.py": ("shared/witness_rota.py", 0o644),
        f"{ROTA}/hapax-agy-reviewer": ("scripts/hapax-agy-reviewer", 0o755),
        "usr/local/sbin/hapax-signing-holder": ("scripts/hapax-signing-holder", 0o755),
        "usr/local/sbin/hapax-witness-rota": ("scripts/hapax-witness-rota", 0o755),
        "etc/systemd/system/hapax-signing-holder.socket": (
            "systemd/units/hapax-signing-holder.socket",
            0o644,
        ),
        "etc/systemd/system/hapax-signing-holder@.service": (
            "systemd/units/hapax-signing-holder@.service",
            0o644,
        ),
        "etc/systemd/system/hapax-witness-rota@.service": (
            "systemd/units/hapax-witness-rota@.service",
            0o644,
        ),
        "etc/systemd/system/hapax-witness-rota.timer": (
            "systemd/units/hapax-witness-rota.timer",
            0o644,
        ),
    }
    for installed, (rel, want) in expected.items():
        assert (box.dest / installed).read_bytes() == (REPO_ROOT / rel).read_bytes(), installed
        assert mode(box.dest / installed) == want, installed
    for lib in (HOLDER_LIB, ROTA_LIB):
        assert (box.dest / lib / "__init__.py").read_bytes() == b""
    assert box.log.read_text().splitlines() == [
        "daemon-reload",
        "enable --now hapax-signing-holder.socket",
        "enable --now hapax-witness-rota.timer",
    ]
    assert box.receipt.read_text().strip() == head


def test_pins_a_root_owned_agy_copy_with_its_sha256_and_version(box: Box) -> None:
    done = box.install(box.release(box.commit()))
    assert done.returncode == 0, done.stderr
    agy = box.dest / ROTA / "agy"
    assert agy.read_bytes() == AGY and mode(agy) == 0o755
    pin = json.loads((box.dest / ROTA / "agy.pin").read_text())
    assert pin["sha256"] == hashlib.sha256(AGY).hexdigest()
    assert pin["version"] == "1.2.11"


def test_a_re_pin_is_announced_with_the_characterization_row(box: Box) -> None:
    (box.dest / ROTA).mkdir(parents=True)
    (box.dest / ROTA / "agy.pin").write_text(json.dumps({"sha256": "0" * 64, "version": "1.1.13"}))
    done = box.install(box.release(box.commit()))
    assert done.returncode == 0, done.stderr
    assert "re-pin" in done.stdout
    assert "capability-work-specification-characterization-20260925" in done.stdout


def test_refuses_without_root(box: Box) -> None:
    assert_refused(box.install(box.release(box.commit()), as_root=False), box)


def test_refuses_without_the_encrypted_credential(box: Box) -> None:
    (box.dest / CRED).unlink()
    done = box.install(box.release(box.commit()))
    assert_refused(done, box)
    assert "systemd-creds encrypt" in done.stderr


def test_refuses_a_release_that_is_not_the_active_one(box: Box) -> None:
    older = box.release(box.commit())
    box.release(box.commit(extra="newer"))
    assert_refused(box.install(older), box)


def test_refuses_a_head_that_is_not_an_ancestor_of_origin_main(box: Box) -> None:
    base = box.commit()
    lane = box.commit(extra="lane")
    assert_refused(box.install(box.release(lane, main=base)), box)


def test_refuses_a_release_not_at_its_named_commit(box: Box) -> None:
    first = box.commit()
    release = box.release(box.commit(extra="second"))
    box.git(release, "checkout", "-q", "--detach", first)
    assert_refused(box.install(release), box)


def test_refuses_an_agy_that_does_not_run(box: Box) -> None:
    agy = box.home / ".local" / "bin" / "agy"
    agy.unlink()
    agy.symlink_to("/etc/hostname")
    assert_refused(box.install(box.release(box.commit())), box)


def test_refuses_a_missing_agy(box: Box) -> None:
    (box.home / ".local" / "bin" / "agy").unlink()
    assert_refused(box.install(box.release(box.commit())), box)


def test_installs_committed_bytes_not_working_tree_edits(box: Box) -> None:
    release = box.release(box.commit())
    (release / "shared/witness_rota.py").write_text("raise SystemExit('lane edit')\n")
    done = box.install(release)
    assert done.returncode == 0, done.stderr
    assert (box.dest / ROTA_LIB / "witness_rota.py").read_bytes() == (
        REPO_ROOT / "shared/witness_rota.py"
    ).read_bytes()


def test_the_installed_rota_library_imports_alone(box: Box, tmp_path: Path) -> None:
    assert box.install(box.release(box.commit())).returncode == 0
    probe = (
        f"import sys; sys.path.insert(0, {str(box.dest / ROTA)!r}); "
        "import shared.witness_rota as m; print(m.__file__)"
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
    assert done.stdout.strip() == str(box.dest / ROTA_LIB / "witness_rota.py")


def test_the_manifest_lists_every_package_file() -> None:
    manifest = REPO_ROOT / "config/root-required/witness-rota.files"
    entries = [
        line
        for line in manifest.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(entries) == sorted([*PACKAGE, "config/root-required/witness-rota.files"])
    assert all((REPO_ROOT / entry).is_file() for entry in entries)
