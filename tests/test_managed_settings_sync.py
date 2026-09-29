"""The root sync may only add released deny entries to a root-owned file.

Every unsafe case writes nothing (or keeps what is installed) and names a next action.
"""

from __future__ import annotations

import io
import json
import os
import pwd
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared import managed_settings_sync as sync_module
from shared.managed_settings_deny import render
from shared.managed_settings_sync import (
    DENY_FILE_REL,
    MAIN_REF,
    RELEASES_REL,
    STABLE_WORKTREE_REL,
    Outcome,
    Owner,
    git_argv,
    report,
    sync,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT = "/usr/bin/git"
A = "mcp__claude_ai_Gmail__send_message"
B = "mcp__playwright"
C = "mcp__claude-in-chrome"
TARGET_NAME = "50-hapax-communication-pathway.json"


def deny_doc(*entries: str, **extra: object) -> str:
    return json.dumps({"permissions": {"deny": list(entries), **extra}})


@dataclass
class Estate:
    home: Path
    canon: Path
    target: Path
    env: dict[str, str]

    @property
    def owner(self) -> Owner:
        return Owner(os.getuid(), os.getgid(), self.home)

    @property
    def link(self) -> Path:
        return self.home / STABLE_WORKTREE_REL

    def git(self, repo: Path, *args: str) -> str:
        done = subprocess.run(
            [GIT, "-C", str(repo), *args], check=True, capture_output=True, env=self.env
        )
        return done.stdout.decode().strip()

    def commit(self, text: str | None, *, symlink_to: str | None = None) -> str:
        path = self.canon / DENY_FILE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            path.unlink()
        if symlink_to is not None:
            path.symlink_to(symlink_to)
        elif text is not None:
            path.write_text(text)
        self.git(self.canon, "add", "-A")
        self.git(self.canon, "commit", "-q", "--allow-empty", "-m", "c")
        return self.git(self.canon, "rev-parse", "HEAD")

    def worktree_at(self, where: Path, sha: str) -> Path:
        where.parent.mkdir(parents=True, exist_ok=True)
        self.git(self.canon, "worktree", "add", "-q", "--detach", str(where), sha)
        return where

    def release(self, sha: str, *, main: str | None = None) -> Path:
        self.git(self.canon, "update-ref", MAIN_REF, main or sha)
        release = self.worktree_at(self.home / RELEASES_REL / sha, sha)
        self.point_link_at(release)
        return release

    def point_link_at(self, where: Path) -> None:
        if self.link.is_symlink() or self.link.exists():
            self.link.unlink()
        self.link.parent.mkdir(parents=True, exist_ok=True)
        self.link.symlink_to(where)


@pytest.fixture
def estate(tmp_path: Path) -> Estate:
    home = tmp_path / "home"
    canon = home / "projects" / "council"
    canon.mkdir(parents=True)
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
    target_dir = tmp_path / "etc" / "claude-code" / "managed-settings.d"
    target_dir.mkdir(parents=True)
    target_dir.chmod(0o755)
    return Estate(home=home, canon=canon, target=target_dir / TARGET_NAME, env=env)


def run(estate: Estate, **kwargs: object) -> Outcome:
    return sync(estate.owner, estate.target, root_uid=os.getuid(), euid=os.geteuid(), **kwargs)


def assert_refused(outcome: Outcome) -> None:
    assert not outcome.wrote
    assert outcome.refusals
    for refusal in outcome.refusals:
        assert "next action:" in refusal, refusal


def install(estate: Estate, *entries: str) -> str:
    text = render(entries)
    estate.target.write_text(text)
    estate.target.chmod(0o644)
    return text


def installed_deny(estate: Estate) -> list[str]:
    return json.loads(estate.target.read_text())["permissions"]["deny"]


# --- the released list reaches the target, add-only ---


def test_first_install_writes_the_released_list(estate: Estate) -> None:
    estate.release(estate.commit(deny_doc(B, A)))
    outcome = run(estate)
    assert outcome.wrote and outcome.refusals == []
    assert installed_deny(estate) == sorted([A, B])
    assert stat.S_IMODE(estate.target.stat().st_mode) == 0o644


def test_a_new_released_entry_is_added_to_the_installed_list(estate: Estate) -> None:
    install(estate, A)
    estate.release(estate.commit(deny_doc(A, C)))
    outcome = run(estate)
    assert outcome.wrote
    assert installed_deny(estate) == sorted([A, C])


def test_a_shortened_list_keeps_installed_entries_and_reports_removals(estate: Estate) -> None:
    before = install(estate, A, B)
    estate.release(estate.commit(deny_doc(A)))
    outcome = run(estate)
    assert outcome.refusals == []
    assert outcome.removal_requests == [B]
    assert estate.target.read_text() == before


def test_an_unchanged_list_is_not_rewritten(estate: Estate) -> None:
    install(estate, A)
    inode = estate.target.stat().st_ino
    estate.release(estate.commit(deny_doc(A)))
    outcome = run(estate)
    assert not outcome.wrote and outcome.refusals == []
    assert estate.target.stat().st_ino == inode


# --- a refused candidate writes nothing ---


def test_a_candidate_with_an_allow_rule_writes_nothing(estate: Estate) -> None:
    estate.release(estate.commit(json.dumps({"permissions": {"deny": [A], "allow": ["Bash"]}})))
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_candidate_with_a_permission_mode_writes_nothing(estate: Estate) -> None:
    before = install(estate, A)
    estate.release(estate.commit(deny_doc(A, B, defaultMode="bypassPermissions")))
    assert_refused(run(estate))
    assert estate.target.read_text() == before


def test_a_malformed_candidate_writes_nothing(estate: Estate) -> None:
    before = install(estate, A)
    estate.release(estate.commit("{not json"))
    assert_refused(run(estate))
    assert estate.target.read_text() == before


def test_an_invalid_installed_file_is_not_overwritten(estate: Estate) -> None:
    estate.target.write_text("hand edited")
    estate.target.chmod(0o644)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))
    assert estate.target.read_text() == "hand edited"


# --- the target must be a root-owned regular file in a root-owned directory ---


def test_a_symlinked_target_is_refused(estate: Estate, tmp_path: Path) -> None:
    elsewhere = tmp_path / "lane-owned.json"
    elsewhere.write_text(render([A]))
    estate.target.symlink_to(elsewhere)
    estate.release(estate.commit(deny_doc(A, B)))
    assert_refused(run(estate))
    assert estate.target.is_symlink()
    assert elsewhere.read_text() == render([A])


def test_a_target_that_is_not_a_regular_file_is_refused(estate: Estate) -> None:
    estate.target.mkdir(mode=0o755)
    estate.target.chmod(0o755)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))
    assert estate.target.is_dir()


def _lstat_reporting_foreign(path_to_fake: Path):
    real = os.lstat

    def lstat(path: str | os.PathLike[str]) -> object:
        st = real(path)
        if Path(path) == path_to_fake:
            return SimpleNamespace(st_mode=st.st_mode, st_uid=st.st_uid + 1)
        return st

    return lstat


def test_a_target_owned_by_another_user_is_refused(estate: Estate) -> None:
    before = install(estate, A)
    estate.release(estate.commit(deny_doc(A, B)))
    assert_refused(run(estate, lstat=_lstat_reporting_foreign(estate.target)))
    assert estate.target.read_text() == before


def test_a_target_directory_owned_by_another_user_is_refused(estate: Estate) -> None:
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate, lstat=_lstat_reporting_foreign(estate.target.parent)))
    assert not estate.target.exists()


@pytest.mark.parametrize("mode", [0o664, 0o646])
def test_a_target_writable_by_others_is_refused(estate: Estate, mode: int) -> None:
    before = install(estate, A)
    estate.target.chmod(mode)
    estate.release(estate.commit(deny_doc(A, B)))
    assert_refused(run(estate))
    assert estate.target.read_text() == before


@pytest.mark.parametrize("mode", [0o775, 0o757])
def test_a_target_directory_writable_by_others_is_refused(estate: Estate, mode: int) -> None:
    estate.target.parent.chmod(mode)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_symlinked_target_directory_is_refused(estate: Estate, tmp_path: Path) -> None:
    lane_dir = tmp_path / "lane-dir"
    lane_dir.mkdir(mode=0o755)
    estate.target.parent.rmdir()
    estate.target.parent.symlink_to(lane_dir)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))
    assert list(lane_dir.iterdir()) == []


def test_a_symlinked_ancestor_of_the_target_directory_is_refused(
    estate: Estate, tmp_path: Path
) -> None:
    real_parent = tmp_path / "lane-etc" / "claude-code"
    (real_parent / "managed-settings.d").mkdir(parents=True, mode=0o755)
    (real_parent / "managed-settings.d").chmod(0o755)
    claude_code = estate.target.parent.parent
    estate.target.parent.rmdir()
    claude_code.rmdir()
    claude_code.symlink_to(real_parent)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))
    assert list((real_parent / "managed-settings.d").iterdir()) == []


def test_a_missing_target_directory_is_refused(estate: Estate) -> None:
    estate.target.parent.rmdir()
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))
    assert not estate.target.parent.exists()


def test_a_target_directory_that_is_a_file_is_refused(estate: Estate) -> None:
    estate.target.parent.rmdir()
    estate.target.parent.write_text("")
    estate.target.parent.chmod(0o644)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(run(estate))


# --- the source must be the active release, at its named commit, on released main ---


def test_a_worktree_link_outside_the_releases_directory_is_refused(
    estate: Estate, tmp_path: Path
) -> None:
    sha = estate.commit(deny_doc(A))
    estate.git(estate.canon, "update-ref", MAIN_REF, sha)
    lane_clone = estate.worktree_at(tmp_path / "lane" / sha, sha)
    estate.point_link_at(lane_clone)
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_worktree_that_is_not_a_link_is_refused(estate: Estate) -> None:
    sha = estate.commit(deny_doc(A))
    estate.git(estate.canon, "update-ref", MAIN_REF, sha)
    estate.worktree_at(estate.link, sha)
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_release_with_a_symlinked_component_is_refused(estate: Estate, tmp_path: Path) -> None:
    sha = estate.commit(deny_doc(A))
    estate.git(estate.canon, "update-ref", MAIN_REF, sha)
    other = tmp_path / "other-releases"
    estate.worktree_at(other / sha, sha)
    releases = estate.home / RELEASES_REL
    releases.parent.mkdir(parents=True, exist_ok=True)
    releases.symlink_to(other)
    estate.point_link_at(releases / sha)
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_release_whose_head_is_not_its_named_commit_is_refused(estate: Estate) -> None:
    first = estate.commit(deny_doc(A))
    second = estate.commit(deny_doc(A, B))
    release = estate.release(second)
    estate.git(release, "checkout", "-q", "--detach", first)
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_head_that_is_not_an_ancestor_of_origin_main_is_refused(estate: Estate) -> None:
    base = estate.commit(deny_doc(A))
    lane = estate.commit(deny_doc(A, B))
    estate.release(lane, main=base)
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_missing_origin_main_is_refused(estate: Estate) -> None:
    estate.release(estate.commit(deny_doc(A)))
    estate.git(estate.canon, "update-ref", "-d", MAIN_REF)
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_working_tree_edit_is_not_installed(estate: Estate) -> None:
    release = estate.release(estate.commit(deny_doc(A)))
    (release / DENY_FILE_REL).write_text(deny_doc(A, B))
    outcome = run(estate)
    assert outcome.wrote
    assert installed_deny(estate) == [A]


def test_a_deny_file_committed_as_a_symlink_is_refused(estate: Estate) -> None:
    estate.release(estate.commit(None, symlink_to="/etc/hostname"))
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_release_without_the_deny_file_is_refused(estate: Estate) -> None:
    estate.release(estate.commit(None))
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_a_deny_file_that_is_not_utf8_is_refused(estate: Estate) -> None:
    path = estate.canon / DENY_FILE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"permissions": {"deny": ["mcp__\xff"]}}')
    estate.git(estate.canon, "add", "-A")
    estate.git(estate.canon, "commit", "-q", "-m", "c")
    estate.release(estate.git(estate.canon, "rev-parse", "HEAD"))
    assert_refused(run(estate))
    assert not estate.target.exists()


def test_the_callers_git_environment_is_not_inherited(
    estate: Estate, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    estate.release(estate.commit(deny_doc(A)))
    assert run(estate).wrote


# --- git runs as the owner of the repository it reads, never as root ---


def test_git_runs_as_the_worktree_owner_when_the_sync_is_root() -> None:
    owner = Owner(1000, 1001, Path("/home/x"))
    argv = git_argv(owner, Path("/r"), ["status"], euid=0)
    assert argv[0] == "/usr/bin/setpriv"
    assert {"--reuid=1000", "--regid=1001", "--init-groups"} <= set(argv)
    assert argv[argv.index("--") + 1 :] == [GIT, "-C", "/r", "status"]


def test_the_sync_drops_to_the_owner_by_default_when_root(
    estate: Estate, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def record(argv: list[str], env: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, b"", b"")

    monkeypatch.setattr(sync_module.os, "geteuid", lambda: 0)
    estate.release(estate.commit(deny_doc(A)))
    assert_refused(sync(estate.owner, estate.target, root_uid=os.getuid(), runner=record))
    assert calls and all(argv[0] == "/usr/bin/setpriv" for argv in calls)


def test_git_runs_directly_when_the_sync_is_not_root() -> None:
    owner = Owner(1000, 1000, Path("/home/x"))
    assert git_argv(owner, Path("/r"), ["status"], euid=1000) == [GIT, "-C", "/r", "status"]


# --- the operator sees refusals and removal requests ---


def test_a_refusal_is_reported_and_fails_the_unit() -> None:
    stream = io.StringIO()
    assert report(Outcome(False, ["x is wrong; next action: fix x"]), stream) == 1
    assert "x is wrong; next action: fix x" in stream.getvalue()


def test_each_removal_request_is_logged_for_the_operator() -> None:
    stream = io.StringIO()
    assert report(Outcome(False, [], [A, B]), stream) == 0
    lines = [line for line in stream.getvalue().splitlines() if "removal" in line]
    assert len(lines) == 2 and A in lines[0] and B in lines[1]
    assert all("next action:" in line for line in lines)


def test_main_syncs_for_the_named_owner_and_target(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_sync(owner: Owner, target: Path) -> Outcome:
        seen["owner"], seen["target"] = owner, target
        return Outcome(True)

    monkeypatch.setattr(sync_module, "sync", fake_sync)
    uid = os.getuid()
    assert sync_module.main(["--owner-uid", str(uid), "--target", "/x/y.json"]) == 0
    entry = pwd.getpwuid(uid)
    assert seen == {
        "owner": Owner(entry.pw_uid, entry.pw_gid, Path(entry.pw_dir)),
        "target": Path("/x/y.json"),
    }


# --- packaging: system scope, installed library, manifest ---

SERVICE = REPO_ROOT / "systemd/units/hapax-claude-code-managed-settings-sync.service"
TIMER = REPO_ROOT / "systemd/units/hapax-claude-code-managed-settings-sync.timer"
ENTRY = REPO_ROOT / "scripts/hapax-claude-code-managed-settings-sync"
MANIFEST = REPO_ROOT / "config/root-required/claude-code-managed-settings.files"


def test_the_units_are_system_scoped_and_run_the_installed_sync() -> None:
    service, timer = SERVICE.read_text(), TIMER.read_text()
    assert "# Hapax-Install-Scope: system" in service
    assert "# Hapax-Install-Scope: system" in timer
    assert (
        "ExecStart=/usr/local/sbin/hapax-claude-code-managed-settings-sync --owner-uid 1000 "
        f"--target /etc/claude-code/managed-settings.d/{TARGET_NAME}"
    ) in service
    assert "ReadWritePaths=/etc/claude-code/managed-settings.d" in service
    assert "OnFailure=hapax-root-failure-intake@%n.service" in service
    assert "Unit=hapax-claude-code-managed-settings-sync.service" in timer


def test_the_entry_script_imports_only_the_installed_library() -> None:
    lines = ENTRY.read_text().splitlines()
    assert lines[0] == "#!/usr/bin/python3 -I"
    text = "\n".join(lines)
    assert 'sys.path.insert(0, "/usr/local/lib/hapax/claude-code-managed-settings")' in text
    assert "from shared.managed_settings_sync import main" in text


def test_the_manifest_lists_every_package_file() -> None:
    entries = [
        line
        for line in MANIFEST.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(entries) == sorted(
        [
            "config/root-required/claude-code-managed-settings.files",
            "scripts/install-claude-code-managed-settings",
            "scripts/hapax-claude-code-managed-settings-sync",
            "shared/managed_settings_deny.py",
            "shared/managed_settings_sync.py",
            "systemd/units/hapax-claude-code-managed-settings-sync.service",
            "systemd/units/hapax-claude-code-managed-settings-sync.timer",
        ]
    )
    assert all((REPO_ROOT / entry).is_file() for entry in entries)
