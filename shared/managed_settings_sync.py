"""Root sync for the Claude Code managed-settings deny list.

A system timer runs this as root. It reads the deny file from the active source release and
applies ``managed_settings_deny.plan`` to the installed file under
``/etc/claude-code/managed-settings.d/``: deny-only and add-only, so the sync can narrow what
sessions may do but never widen it. Removal requests are logged for the operator, who removes
an entry by a root act outside this code.

The sync refuses, writing nothing, unless:

- the source is the active release: ``~/.cache/hapax/source-activation/worktree`` is a link to
  ``releases/<commit>``, with no symlinked component, and the release's HEAD is that commit;
- that commit is an ancestor of ``origin/main``;
- the deny file is read from that commit, never from the working tree, and passes ``plan()``;
- the target directory and any installed file are root-owned, not symlinks, and not writable
  by group or others.

Git runs as the owner of the repository it reads, never as root, with a clean environment, so
the repository's own configuration cannot run anything with root authority.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import pwd
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from shared.managed_settings_deny import plan

STABLE_WORKTREE_REL = Path(".cache/hapax/source-activation/worktree")
RELEASES_REL = Path(".cache/hapax/source-activation/releases")
DENY_FILE_REL = "config/claude-code-managed-settings-communication-pathway.json"
MAIN_REF = "refs/remotes/origin/main"
GIT = "/usr/bin/git"
SETPRIV = "/usr/bin/setpriv"
_INSTALLER_HINT = (
    "next action: rerun scripts/install-claude-code-managed-settings from the active release"
)

Runner = Callable[[list[str], Mapping[str, str]], "subprocess.CompletedProcess[bytes]"]


@dataclass(frozen=True)
class Owner:
    uid: int
    gid: int
    home: Path


@dataclass(frozen=True)
class Outcome:
    wrote: bool
    refusals: list[str] = field(default_factory=list)
    removal_requests: list[str] = field(default_factory=list)


def git_argv(owner: Owner, repo: Path, args: list[str], *, euid: int) -> list[str]:
    """The git command line, dropped to the repository owner when the caller is root."""
    command = [GIT, "-C", str(repo), *args]
    if euid == 0:
        return [
            SETPRIV,
            f"--reuid={owner.uid}",
            f"--regid={owner.gid}",
            "--init-groups",
            "--",
            *command,
        ]
    return command


def _git_env(owner: Owner) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(owner.home),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
    }


def _run(argv: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, env=dict(env), capture_output=True, timeout=60, check=False)


def release_source(
    owner: Owner, *, runner: Runner | None = None, euid: int | None = None
) -> tuple[bytes | None, list[str]]:
    """The deny file's bytes at the active release's commit, or refusals."""
    runner = runner or _run
    euid = os.geteuid() if euid is None else euid
    link = owner.home / STABLE_WORKTREE_REL
    releases = owner.home / RELEASES_REL
    try:
        release = Path(os.readlink(link))
    except OSError as exc:
        return None, [
            f"{link} is not a link to a release ({exc.strerror}); "
            "next action: let source activation repoint it at releases/<commit>"
        ]
    if release.parent != releases or os.path.realpath(release) != str(release):
        return None, [
            f"{link} points at {release}, not a release directly under {releases} with no "
            "symlinked component; next action: let source activation repoint it"
        ]

    def git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return runner(git_argv(owner, release, list(args), euid=euid), _git_env(owner))

    sha = git("rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip()
    if sha != release.name:
        return None, [
            f"{release} is at {sha or 'no commit'}, not its named commit; "
            "next action: rebuild the release from source activation"
        ]
    if git("merge-base", "--is-ancestor", sha, MAIN_REF).returncode:
        return None, [
            f"release {sha} is not an ancestor of {MAIN_REF}; "
            "next action: activate a released main commit"
        ]
    # Committed bytes only: the working tree is never read. Anything but a deny document (a
    # symlink's target text, an unreadable tree or submodule) fails plan()'s validation.
    entry = git("ls-tree", sha, "--", DENY_FILE_REL).stdout.decode().split()
    if not entry:
        return None, [
            f"{DENY_FILE_REL} is absent at {sha}; next action: land the deny file on main"
        ]
    return git("cat-file", "blob", entry[2]).stdout, []


def _writable_by_others(mode: int) -> bool:
    return bool(mode & (stat.S_IWGRP | stat.S_IWOTH))


def check_target(
    target: Path, *, root_uid: int = 0, lstat: Callable[..., Any] | None = None
) -> list[str]:
    """Refusals unless the target is a root-owned regular file (or absent) in a safe directory."""
    lstat = lstat or os.lstat
    parent = target.parent
    if os.path.realpath(parent) != str(parent):
        return [f"{parent} has a symlinked component; {_INSTALLER_HINT}"]
    try:
        st = lstat(parent)
    except FileNotFoundError:
        return [f"{parent} does not exist; {_INSTALLER_HINT} (it creates the directory)"]
    if not stat.S_ISDIR(st.st_mode):
        return [f"{parent} is not a directory; {_INSTALLER_HINT}"]
    if st.st_uid != root_uid:
        return [f"{parent} is not owned by uid {root_uid}; {_INSTALLER_HINT}"]
    if _writable_by_others(st.st_mode):
        return [f"{parent} is writable by group or others; {_INSTALLER_HINT}"]
    try:
        st = lstat(target)
    except FileNotFoundError:
        return []
    if not stat.S_ISREG(st.st_mode):
        return [f"{target} is not a regular file; next action: the operator removes it as root"]
    if st.st_uid != root_uid:
        return [f"{target} is not owned by uid {root_uid}; next action: the operator reviews it"]
    if _writable_by_others(st.st_mode):
        return [f"{target} is writable by group or others; next action: the operator reviews it"]
    return []


def _read_installed(target: Path) -> str | None:
    # check_target has already required a root-owned directory nobody else can write.
    try:
        return target.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None


def _write_atomic(target: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fchmod(fh.fileno(), 0o644)
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def sync(
    owner: Owner,
    target: Path,
    *,
    root_uid: int = 0,
    euid: int | None = None,
    runner: Runner | None = None,
    lstat: Callable[..., Any] | None = None,
) -> Outcome:
    """Add the released deny entries to the installed file; refuse, writing nothing, otherwise."""
    refusals = check_target(target, root_uid=root_uid, lstat=lstat)
    if refusals:
        return Outcome(False, refusals)
    candidate, refusals = release_source(owner, runner=runner, euid=euid)
    if candidate is None:
        return Outcome(False, refusals)
    try:
        candidate_text = candidate.decode("utf-8")
        installed_text = _read_installed(target)
    except UnicodeDecodeError:
        return Outcome(False, ["deny file is not UTF-8; next action: fix it on main"])
    result = plan(installed_text, candidate_text)
    if result.errors:
        return Outcome(
            False,
            [
                f"{e}; next action: fix the deny file on main, or the operator reviews {target}"
                for e in result.errors
            ],
        )
    if result.write_text is not None:
        _write_atomic(target, result.write_text)
    return Outcome(result.write_text is not None, [], result.removal_requests)


def report(outcome: Outcome, stream: TextIO) -> int:
    """Log refusals and removal requests for the operator; nonzero fails the unit."""
    for refusal in outcome.refusals:
        print(f"refused: {refusal}", file=stream)
    for entry in outcome.removal_requests:
        print(
            f"removal requested, entry kept: {entry}; next action: removing a deny entry "
            "is an operator root act",
            file=stream,
        )
    if outcome.wrote:
        print("installed the released deny entries", file=stream)
    return 1 if outcome.refusals else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner-uid", type=int, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv)
    entry = pwd.getpwuid(args.owner_uid)
    owner = Owner(entry.pw_uid, entry.pw_gid, Path(entry.pw_dir))
    return report(sync(owner, args.target), sys.stderr)
