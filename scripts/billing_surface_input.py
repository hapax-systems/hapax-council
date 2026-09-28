"""Git-owned input validation for the billing surface scan.

Callers may inspect added lines only after ``materialise_post_image`` has
validated the input against the named base. The next layer regenerates a diff
from the temporary index yielded here.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class GitUnavailable(RuntimeError):
    """Git is missing, so input validation cannot proceed."""


class UnusableInput(RuntimeError):
    """The input does not apply to the named base."""


def _run_git(
    args: list[str],
    *,
    repo: Path,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise GitUnavailable(str(exc)) from exc


def _git_out(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()


def _resolve_base(base: str, *, repo: Path) -> str:
    proc = _run_git(["rev-parse", "--verify", f"{base}^{{commit}}"], repo=repo)
    if proc.returncode != 0:
        raise UnusableInput(
            f"~base '{base}' is not a commit git can resolve here ({_git_out(proc)}). Next action: "
            "pass --base as the PR's base revision (or a commit sha) in this repository"
        )
    return proc.stdout.strip()


@contextmanager
def materialise_post_image(
    diff_text: str, *, repo: Path, base: str
) -> Iterator[tuple[Path, dict[str, str]]]:
    """Yield a temporary index containing the validated post-image, then clean it."""
    resolved = _resolve_base(base, repo=repo)
    with tempfile.TemporaryDirectory(prefix="billing-scan-index-") as index_dir:
        index_path = Path(index_dir) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
        read = _run_git(["read-tree", resolved], repo=repo, env=env)
        if read.returncode != 0:
            raise UnusableInput(
                f"git could not seed a temporary index from {resolved[:12]}: {_git_out(read)}. Next "
                "action: run this scanner inside the repository whose base it names"
            )
        # The temporary index holds the base tree. --cached checks against that tree,
        # even when the caller's worktree is already at the post-image.
        check = _run_git(
            ["apply", "--cached", "--check", "--unidiff-zero", "--whitespace=nowarn", "-"],
            repo=repo,
            env=env,
            stdin=diff_text,
        )
        if check.returncode != 0:
            raise UnusableInput(
                f"git will not apply this input to {resolved[:12]}: {_git_out(check)}. Next action: "
                "regenerate the diff with `git diff <base>...HEAD` in this repository (or fix the "
                "input); a diff git cannot apply is billing-scan-unusable-input and is never scanned"
            )
        applied = _run_git(
            ["apply", "--cached", "--unidiff-zero", "--whitespace=nowarn", "-"],
            repo=repo,
            env=env,
            stdin=diff_text,
        )
        if applied.returncode != 0:
            raise UnusableInput(
                "git accepted the input with --check but could not apply it to the index: "
                f"{_git_out(applied)}. Next action: regenerate the diff from the same repository "
                "state and rerun"
            )
        yield index_path, env
