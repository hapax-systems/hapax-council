"""Git-owned input validation for the billing surface scan.

Callers may inspect added lines only after ``materialise_post_image`` has
validated the input against the named base. Git then regenerates a diff from
that temporary index; a closed grammar reads only its added lines.
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


def parse_git_added_lines(text: str) -> tuple[dict[str, dict[int, str]], str | None]:
    """Read added lines from Git's own zero-context diff, rejecting unknown shapes."""
    files: dict[str, dict[int, str]] = {}
    pending_path: str | None = None
    path: str | None = None
    new_line = 0
    in_hunk = False
    deleted_file = False
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            pending_path = None
            path = None
            in_hunk = False
            deleted_file = False
            continue
        if raw.startswith(_SECTION_META_PREFIXES):
            continue
        if raw.startswith("--- ") or raw.startswith("+++ "):
            candidate = raw[4:].strip()
            if raw.startswith("--- "):
                continue
            if candidate == "/dev/null":
                pending_path = None
                deleted_file = True
            elif candidate.startswith("b/"):
                pending_path = candidate[2:]
                deleted_file = False
            else:
                return {}, f"a '+++ ' header git would not emit: {raw!r}"
            continue
        if raw.startswith(("Binary files ", "GIT binary patch")):
            pending_path = None
            in_hunk = False
            continue
        header = _HUNK_HEADER_RE.match(raw)
        if header is not None:
            if pending_path is None and not deleted_file:
                return {}, "a hunk header arrived before any '+++ b/<path>' header"
            path = pending_path
            new_line = int(header.group(3))
            in_hunk = True
            continue
        if raw.startswith("\\"):
            continue
        if in_hunk and raw.startswith("+"):
            if path is None:
                return {}, "an added line arrived with no post-image path"
            files.setdefault(path, {})[new_line] = raw[1:]
            new_line += 1
            continue
        if in_hunk and raw.startswith(("-", " ")):
            if raw.startswith(" "):
                new_line += 1
            continue
        return {}, f"an unrecognised line in git's own diff output: {raw!r}"
    return files, None


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
    """Ask Git for the validated index diff, then read only its added lines."""
    regenerated = _run_git(
        ["diff", "--cached", "--no-color", "--no-ext-diff", "--unified=0", f"{base}^{{commit}}"],
        repo=repo,
        env=env,
    )
    if regenerated.returncode != 0:
        return {}, (
            "FAIL-CLOSED: git could not regenerate the diff from the validated index: "
            f"{_git_out(regenerated)}. Next action: rerun in the repository whose base it names"
        )
    files, error = parse_git_added_lines(regenerated.stdout)
    if error is not None:
        return {}, (
            f"FAIL-CLOSED: {error}. Next action: this shape is not one git emits for a text diff, "
            "so nothing is scanned; regenerate the input with `git diff <base>...HEAD` and rerun"
        )
    return files, None
