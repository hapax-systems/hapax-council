"""The pre-push principal-name scan: registry-fed, fragment-aware, name-withholding.

Every fixture here is a SYNTHETIC token. No test in this file may carry a real registered name, and
the scan's own output must never contain one either — that is asserted, not assumed.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-principal-names-diff.py"

#: Synthetic registry tokens. Deliberately not names of anyone.
NAME_A = "Zqxvbn"
NAME_B = "Mrtplq"
#: A longer synthetic token, for the short-literal bound.
NAME_LONG = "Qwrtplzxcv"
#: A three-character token, below the substring threshold.
NAME_SHORT = "Qxv"
#: A four-character token, at the substring threshold.
NAME_SUB = "Qxvb"
PY = "python3"


def _refusal(path: str, line: int) -> str:
    return f"path_sha256={hashlib.sha256(path.encode('utf-8')).hexdigest()}:{line}"


def _registry(tmp_path: Path, text: str, name: str = "principals.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _valid_registry(tmp_path: Path) -> Path:
    return _registry(tmp_path, f"principal-a1: {NAME_A}\nprincipal-b2: {NAME_B}\n")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ("git", "-C", str(repo), *args), capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    return repo


def _commit(repo: Path, name: str, text: str, message: str = "c") -> tuple[str, str]:
    """Write a file, commit it, and return (parent_sha, head_sha)."""
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD^"), _git(repo, "rev-parse", "HEAD")


def _run(
    repo: Path, registry: Path | None, base: str, head: str
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(repo.parent / "home")}
    if registry is not None:
        env["HAPAX_PRINCIPAL_NAME_MAP"] = str(registry)
    return subprocess.run(
        [PY, str(SCRIPT), "--base", base, "--head", head, "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_env(repo: Path, registry: Path, base: str, head: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
        "PRE_COMMIT": "1",
        "PRE_COMMIT_FROM_REF": base,
        "PRE_COMMIT_TO_REF": head,
    }
    return subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_a_direct_name_in_an_added_line_refuses_and_withholds_the_name(tmp_path: Path):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "note.txt", f"author: {NAME_A}\n")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    # The whole point: the refuse path never echoes the name it found.
    assert NAME_A not in result.stderr and NAME_B not in result.stderr


def test_a_matched_path_containing_a_registry_token_is_not_printed(tmp_path: Path):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    path = f"{NAME_A}.txt"
    parent, head = _commit(repo, path, f"author: {NAME_A}\n")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal(path, 1) in result.stderr
    assert path not in result.stderr
    assert NAME_A not in result.stderr


def test_the_precommit_range_environment_is_honoured(tmp_path: Path):
    """pre-commit consumes git's stdin, then exposes the selected push range through env vars."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "note.txt", f"author: {NAME_A}\n")
    result = _run_env(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    assert NAME_A not in result.stderr and NAME_B not in result.stderr


def test_a_first_push_without_remote_history_scans_the_whole_tree(tmp_path: Path):
    """pre-commit's all-files path supplies no refs; a new root push is still scanned."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    _commit(repo, "note.txt", f"author: {NAME_A}\n")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
        "PRE_COMMIT": "1",
    }
    result = subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    assert NAME_A not in result.stderr and NAME_B not in result.stderr


@pytest.mark.parametrize(
    ("text", "case_id"),
    [
        (f'x = "{NAME_A[:4]}" "{NAME_A[4:]}"\n', "adjacent-literals"),
        (f'x = "{NAME_A[:4]}" + "{NAME_A[4:]}"\n', "plus-joined"),
        (f'x = "".join(["{NAME_B[:3]}", "{NAME_B[3:]}"]) \n', "short-literal-join"),
        (f"x = '{NAME_A[:4]}' + f'{NAME_A[4:]}' \n", "f-string-joined"),
    ],
    ids=["adjacent-literals", "plus-joined", "short-literal-join", "f-string-joined"],
)
def test_a_joined_fragment_name_refuses(tmp_path: Path, text: str, case_id: str):
    """Rule 2: the literals on the added line, concatenated in source order, contain the name."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "split.py", text)
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, f"{case_id}: {result.stderr}"
    assert _refusal("split.py", 1) in result.stderr


def test_long_literals_are_not_assembled_into_a_name(tmp_path: Path):
    """The short-literal bound: a name split across LONG prose literals is not manufactured."""
    repo = _repo(tmp_path)
    registry = _registry(tmp_path, f"principal-a1: {NAME_LONG}\n")
    parent, head = _commit(repo, "prose.py", f'x = "{NAME_LONG[:9]}" + "v"\n')
    assert _run(repo, registry, parent, head).returncode == 0


def test_a_clean_diff_passes(tmp_path: Path):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "clean.py", "print('an ordinary line')\n")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_an_absent_registry_means_no_names(tmp_path: Path):
    """The map's own absent-means-none contract, inherited rather than re-implemented."""
    repo = _repo(tmp_path)
    parent, head = _commit(repo, "note.txt", f"author: {NAME_A}\n")
    assert _run(repo, None, parent, head).returncode == 0


def test_an_unreadable_registry_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path)
    parent, head = _commit(repo, "note.txt", "harmless\n")
    broken = tmp_path / "as-a-directory.yaml"
    broken.mkdir()
    result = _run(repo, broken, parent, head)
    assert result.returncode == 2
    assert "REFUSED" in result.stderr


def test_an_invalid_registry_line_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path)
    parent, head = _commit(repo, "note.txt", "harmless\n")
    registry = _registry(tmp_path, "principal-a1: 1234\n")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 2
    assert "line 1" in result.stderr  # the map names the line, never the value


def test_the_pre_push_stdin_protocol_is_honoured(tmp_path: Path):
    """git hands a pre-push hook `local_ref local_sha remote_ref remote_sha` lines on stdin."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "note.txt", f"author: {NAME_B}\n")
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
    }
    refs = f"refs/heads/x {head} refs/heads/x {parent}\n"
    result = subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        input=refs,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    # A deletion pushes no content.
    deletion = subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        input=f"refs/heads/x {'0' * 40} refs/heads/x {head}\n",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert deletion.returncode == 0


def test_a_file_header_that_looks_like_an_added_line_is_not_scanned(tmp_path: Path):
    """`+++ b/…` headers are structure, not content: a name in a PATH is out of this rule's scope."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    path = f"{NAME_A}.txt"
    parent, head = _commit(repo, path, "ordinary body\n")
    assert _run(repo, registry, parent, head).returncode == 0


def test_non_utf8_added_content_does_not_crash_the_scan(tmp_path: Path):
    """A repository may carry non-UTF-8 text; refusal must still name only file and line."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    (repo / "mixed.txt").write_bytes(b"\xa9 ordinary\n" + f"author: {NAME_A}\n".encode())
    _git(repo, "add", "mixed.txt")
    _git(repo, "commit", "-qm", "mixed")
    parent, head = _git(repo, "rev-parse", "HEAD^"), _git(repo, "rev-parse", "HEAD")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("mixed.txt", 2) in result.stderr
    assert NAME_A not in result.stderr and NAME_B not in result.stderr


def test_a_two_commit_new_branch_scans_before_its_first_commit(tmp_path: Path):
    """A new ref with two commits must not lose the first commit's added lines."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    seed = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "split.py", f'x = "".join(["{NAME_A[:4]}", "{NAME_A[4:]}"])\n')
    _git(repo, "update-ref", "refs/remotes/origin/main", seed)
    head = _commit(repo, "later.txt", "ordinary\n")[1]
    refs = f"refs/heads/x {head} refs/heads/x {'0' * 40}\n"
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
    }
    result = subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        input=refs,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 1, result.stderr
    assert _refusal("split.py", 1) in result.stderr
    assert NAME_A not in result.stderr


def test_a_name_added_then_removed_in_a_later_commit_still_refuses(tmp_path: Path):
    """The aggregate range would be clean; each commit's own diff must still be scanned."""
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    seed = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "note.txt", f"author: {NAME_A}\n")
    _commit(repo, "note.txt", "ordinary\n")
    head = _git(repo, "rev-parse", "HEAD")
    result = _run(repo, registry, seed, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    assert NAME_A not in result.stderr


def test_case_insensitive_direct_match_refuses(tmp_path: Path):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "note.txt", f"author: {NAME_A.lower()}\n")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    assert NAME_A.lower() not in result.stderr


@pytest.mark.parametrize(
    "text",
    [
        f"user{NAME_A}Field = 1\n",
        f"user_{NAME_A.lower()}_field = 1\n",
        f"pre{NAME_A.lower()}post = 1\n",
        f"pre{NAME_A.lower()}Post = 1\n",
    ],
    ids=["camel-case", "snake-case", "run-together", "camel-tail"],
)
def test_an_embedded_name_in_an_identifier_refuses(tmp_path: Path, text: str):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    parent, head = _commit(repo, "embedded.py", text)
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("embedded.py", 1) in result.stderr
    assert NAME_A.lower() not in result.stderr


def test_a_short_registered_name_is_not_substring_matched(tmp_path: Path):
    repo = _repo(tmp_path)
    registry = _registry(tmp_path, f"principal-s1: {NAME_SHORT}\n")
    parent, head = _commit(repo, "note.txt", f"unrelated{NAME_SHORT.lower()}thing\n")
    assert _run(repo, registry, parent, head).returncode == 0


@pytest.mark.parametrize(
    "text",
    [
        f"user{NAME_SHORT}Field = 1\n",
        f"user_{NAME_SHORT.lower()}_field = 1\n",
        f"user2{NAME_SHORT}Field = 1\n",
    ],
    ids=["camel-case", "snake-case", "letter-digit"],
)
def test_a_short_registered_name_embedded_as_a_subtoken_refuses(tmp_path: Path, text: str):
    repo = _repo(tmp_path)
    registry = _registry(tmp_path, f"principal-s1: {NAME_SHORT}\n")
    parent, head = _commit(repo, "embedded.py", text)
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("embedded.py", 1) in result.stderr
    assert NAME_SHORT.lower() not in result.stderr


def test_a_four_character_registered_name_is_substring_matched(tmp_path: Path):
    repo = _repo(tmp_path)
    registry = _registry(tmp_path, f"principal-s2: {NAME_SUB}\n")
    parent, head = _commit(repo, "note.txt", f"pre{NAME_SUB.lower()}post\n")
    result = _run(repo, registry, parent, head)
    assert result.returncode == 1, result.stderr
    assert _refusal("note.txt", 1) in result.stderr
    assert NAME_SUB.lower() not in result.stderr


def test_empty_push_range_is_a_clean_noop(tmp_path: Path):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
    }
    result = subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        input="",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_a_partial_precommit_range_fails_closed(tmp_path: Path):
    repo, registry = _repo(tmp_path), _valid_registry(tmp_path)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
        "PRE_COMMIT": "1",
        "PRE_COMMIT_FROM_REF": "origin/main",
    }
    result = subprocess.run(
        [PY, str(SCRIPT), "--root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2
    assert "REFUSED" in result.stderr


def _wrapper_repo(
    tmp_path: Path, *, with_secret: bool, with_name: bool = True
) -> tuple[Path, Path]:
    repo = tmp_path / "wrapper-repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "hooks" / "scripts").mkdir(parents=True)
    if with_name:
        shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    shutil.copy2(REPO_ROOT / "scripts" / "pre-push", repo / "scripts" / "pre-push")
    shutil.copy2(
        REPO_ROOT / "hooks" / "scripts" / "principal-name-map.sh",
        repo / "hooks" / "scripts" / "principal-name-map.sh",
    )
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    log = tmp_path / "secret-scan.log"
    if with_secret:
        (repo / "scripts" / "hapax-prepush-secret-scan").write_text(
            f"#!/usr/bin/env python3\nfrom pathlib import Path\n"
            f'Path({str(log)!r}).write_text("secret\\n", encoding="utf-8")\n',
            encoding="utf-8",
        )
        (repo / "scripts" / "hapax-prepush-secret-scan").chmod(0o755)
    return repo, log


def _run_wrapper(repo: Path, registry: Path, refs: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo.parent / "home"),
        "HAPAX_PRINCIPAL_NAME_MAP": str(registry),
    }
    return subprocess.run(
        ["bash", str(repo / "scripts" / "pre-push"), "origin", "file:///dev/null"],
        input=refs,
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env=env,
    )


def test_tracked_pre_push_chains_the_secret_scan_after_a_clean_name_scan(tmp_path: Path):
    repo, log = _wrapper_repo(tmp_path, with_secret=True)
    registry = _valid_registry(tmp_path)
    parent, head = _commit(repo, "clean.txt", "ordinary\n")
    refs = f"refs/heads/x {head} refs/heads/x {parent}\n"
    result = _run_wrapper(repo, registry, refs)
    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8") == "secret\n"


def test_tracked_pre_push_stops_before_the_secret_scan_on_a_name_refusal(tmp_path: Path):
    repo, log = _wrapper_repo(tmp_path, with_secret=True)
    registry = _valid_registry(tmp_path)
    parent, head = _commit(repo, "note.txt", f"author: {NAME_A}\n")
    refs = f"refs/heads/x {head} refs/heads/x {parent}\n"
    result = _run_wrapper(repo, registry, refs)
    assert result.returncode == 1, result.stderr
    assert not log.exists()


def test_tracked_pre_push_passes_the_pushing_worktree_root_to_the_name_scan(tmp_path: Path):
    repo, _log = _wrapper_repo(tmp_path, with_secret=True)
    registry = _valid_registry(tmp_path)
    args_log = tmp_path / "name-args.log"
    (repo / "scripts" / "check-principal-names-diff.py").write_text(
        f"#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
        f'Path({str(args_log)!r}).write_text(" ".join(sys.argv[1:]), encoding="utf-8")\n',
        encoding="utf-8",
    )
    parent, head = _commit(repo, "clean.txt", "ordinary\n")
    refs = f"refs/heads/x {head} refs/heads/x {parent}\n"
    result = _run_wrapper(repo, registry, refs)
    assert result.returncode == 0, result.stderr
    assert args_log.read_text(encoding="utf-8") == f"--root {repo}"


def test_tracked_pre_push_refuses_when_the_secret_scan_is_missing(tmp_path: Path):
    repo, _log = _wrapper_repo(tmp_path, with_secret=False)
    registry = _valid_registry(tmp_path)
    parent, head = _commit(repo, "clean.txt", "ordinary\n")
    refs = f"refs/heads/x {head} refs/heads/x {parent}\n"
    result = _run_wrapper(repo, registry, refs)
    assert result.returncode == 3
    assert "hapax-prepush-secret-scan" in result.stderr


def test_tracked_pre_push_refuses_when_the_name_scan_is_missing(tmp_path: Path):
    repo, _log = _wrapper_repo(tmp_path, with_secret=True, with_name=False)
    registry = _valid_registry(tmp_path)
    result = _run_wrapper(repo, registry, "")
    assert result.returncode == 3
    assert "check-principal-names-diff.py" in result.stderr
    assert "Remedy:" in result.stderr


def _hook_repo(tmp_path: Path, hook: str) -> Path:
    repo = tmp_path / "hook-repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts" / hook, repo / "scripts" / hook)
    _git(repo, "init", "-q", ".")
    return repo


def test_tracked_pre_commit_delegates_to_the_pre_commit_framework(tmp_path: Path):
    repo = _hook_repo(tmp_path, "pre-commit")
    bin_dir = tmp_path / "precommit-bin"
    bin_dir.mkdir()
    log = tmp_path / "precommit-args.log"
    (bin_dir / "pre-commit").write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" > {log}\n",
        encoding="utf-8",
    )
    (bin_dir / "pre-commit").chmod(0o755)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "pre-commit"), "staged.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert (
        log.read_text(encoding="utf-8").strip()
        == "hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit -- staged.py"
    )


def test_tracked_pre_commit_refuses_when_the_framework_is_missing(tmp_path: Path):
    repo = _hook_repo(tmp_path, "pre-commit")
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "pre-commit")],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 1
    assert "pre-commit CLI is not on PATH" in result.stderr
