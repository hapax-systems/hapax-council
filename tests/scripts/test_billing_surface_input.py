"""Git validation must finish before the billing scanner reads added lines."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import billing_surface_input as source


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("first\n")
    _git(repo, "add", "app.py")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "app.py").write_text("first\nsecond\n")
    diff = _git(repo, "diff", "--unified=0", base)
    return repo, base, diff


def test_git_validates_a_zero_context_diff_against_the_base_tree(tmp_path: Path) -> None:
    repo, base, diff = _repo(tmp_path)
    with source.materialise_post_image(diff, repo=repo, base=base) as (index, env):
        assert index.exists()
        assert env["GIT_INDEX_FILE"] == str(index)
        assert _git_with_env(repo, env, "show", ":app.py") == "first\nsecond"
    assert not index.parent.exists()


def test_validation_reads_the_base_index_even_when_worktree_is_at_head(tmp_path: Path) -> None:
    repo, base, _diff = _repo(tmp_path)
    (repo / "app.py").write_text("changed\n")
    diff = _git(repo, "diff", base)
    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        assert _git_with_env(repo, env, "show", ":app.py") == "changed"


def _git_with_env(repo: Path, env: dict[str, str], *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.parametrize("bad_diff", ["", "not a diff\n", "diff --git a/app.py b/app.py\n"])
def test_missing_or_truncated_diff_never_materialises(tmp_path: Path, bad_diff: str) -> None:
    repo, base, _diff = _repo(tmp_path)
    with pytest.raises(source.UnusableInput, match="Next action"):
        with source.materialise_post_image(bad_diff, repo=repo, base=base):
            pytest.fail("unusable input was admitted")


def test_unresolvable_base_has_a_next_action(tmp_path: Path) -> None:
    repo, _base, diff = _repo(tmp_path)
    with pytest.raises(source.UnusableInput, match="Next action"):
        with source.materialise_post_image(diff, repo=repo, base="not-a-commit"):
            pytest.fail("unresolvable base was admitted")


def test_target_must_be_a_repository(tmp_path: Path) -> None:
    repo, base, diff = _repo(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(source.UnusableInput, match="Next action"):
        with source.materialise_post_image(diff, repo=plain, base=base):
            pytest.fail("non-repository was admitted")


def test_git_unavailable_raises_a_named_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, diff = _repo(tmp_path)

    def absent_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(source.subprocess, "run", absent_git)
    with pytest.raises(source.GitUnavailable, match="git unavailable"):
        with source.materialise_post_image(diff, repo=repo, base=base):
            pytest.fail("missing git was admitted")
