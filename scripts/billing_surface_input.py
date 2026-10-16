"""Git-owned input validation for the billing surface scan.

Callers may inspect added lines only after ``materialise_post_image`` has
validated the input against the named base. Git then lists the paths that
temporary index changes and regenerates one diff per path; a closed grammar
reads only each path's added lines, so no diff text can name a file.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class GitUnavailable(RuntimeError):
    """Git is missing, so input validation cannot proceed."""


class UnusableInput(RuntimeError):
    """The input does not apply to the named base."""


_SECTION_META_PREFIXES: tuple[str, ...] = (
    "index ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
    "dissimilarity index ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
)
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


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


_PREAMBLE_PREFIXES: tuple[str, ...] = ("diff --git ", "--- ", "+++ ", *_SECTION_META_PREFIXES)


def parse_path_added_lines(text: str) -> tuple[dict[int, str], str | None]:
    """Read one path's added lines from Git's zero-context diff of that path alone.

    The file is the path Git was asked about, never text in the output: before the first hunk
    header only Git's own preamble is accepted, and after it no header is recognised, so an
    added line shaped like one (`++ b/docs/x` renders `+++ b/docs/x`) is content. A binary note
    before any hunk is opaque; any other shape fails closed.
    """
    added: dict[int, str] = {}
    new_line = 0
    in_hunks = False
    for raw in text.splitlines():
        if raw.startswith("@@"):
            header = _HUNK_HEADER_RE.match(raw)
            if header is None:
                return {}, f"a malformed hunk header in git's own diff output: {raw!r}"
            new_line = int(header.group(3))
            in_hunks = True
        elif not in_hunks:
            if raw.startswith(("Binary files ", "GIT binary patch")):
                return {}, None
            if not raw.startswith(_PREAMBLE_PREFIXES):
                return {}, f"an unrecognised line before git's first hunk: {raw!r}"
        elif raw.startswith("+"):
            added[new_line] = raw[1:]
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1
        elif not raw.startswith(("-", "\\")):
            return {}, f"an unrecognised line in git's own diff output: {raw!r}"
    return added, None


def post_image_blob(path: str, *, repo: Path, env: dict[str, str]) -> str | None:
    """Read the indexed blob as text; a binary or unreadable blob is opaque."""
    try:
        proc = subprocess.run(
            ["git", "show", f":{path}"], cwd=str(repo), env=env, capture_output=True, check=False
        )
    except OSError as exc:
        raise GitUnavailable(str(exc)) from exc
    if proc.returncode != 0 or not proc.stdout:
        return None
    if b"\x00" in proc.stdout[:8192]:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def regenerated_added_lines(
    *, repo: Path, base: str, env: dict[str, str]
) -> tuple[dict[str, dict[int, str]], str | None]:
    """Ask Git which paths the validated index changes, then each path's own added lines.

    Attribution comes from Git's structure: the NUL-separated path list, then one diff per
    path with literal pathspecs. No line of diff text ever names a file.
    """
    literal = {**env, "GIT_LITERAL_PATHSPECS": "1"}
    commit = f"{base}^{{commit}}"
    listed = _run_git(
        ["diff", "--cached", "--no-renames", "--name-only", "-z", commit], repo=repo, env=literal
    )
    if listed.returncode != 0:
        return {}, (
            "FAIL-CLOSED: git could not list the paths the validated index changes: "
            f"{_git_out(listed)}. Next action: rerun in the repository whose base it names"
        )
    files: dict[str, dict[int, str]] = {}
    for path in (name for name in listed.stdout.split("\0") if name):
        regenerated = _run_git(
            [
                "diff",
                "--cached",
                "--no-renames",
                "--no-color",
                "--no-ext-diff",
                "--unified=0",
                commit,
                "--",
                path,
            ],
            repo=repo,
            env=literal,
        )
        if regenerated.returncode != 0:
            return {}, (
                f"FAIL-CLOSED: git could not regenerate the diff of {path!r} from the validated "
                f"index: {_git_out(regenerated)}. Next action: rerun in the repository whose base "
                "it names"
            )
        added, error = parse_path_added_lines(regenerated.stdout)
        if error is not None:
            return {}, (
                f"FAIL-CLOSED: {error} (path {path!r}). Next action: this shape is not one git "
                "emits for a text diff, so nothing is scanned; regenerate the input with "
                "`git diff <base>...HEAD` and rerun"
            )
        if added:
            files[path] = added
    return files, None
