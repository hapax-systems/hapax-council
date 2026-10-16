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


def test_regenerated_diff_reports_added_post_image_lines(tmp_path: Path) -> None:
    repo, base, diff = _repo(tmp_path)
    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        files, error = source.regenerated_added_lines(repo=repo, base=base, env=env)
        assert error is None
        assert files == {"app.py": {2: "second"}}
        assert source.post_image_blob("app.py", repo=repo, env=env) == "first\nsecond\n"


@pytest.mark.parametrize(
    "shape",
    [
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,0 +2,1 @@\n+second\nUNKNOWN\n",
        "diff --git a/app.py b/app.py\nUNKNOWN\n@@ -1,0 +2,1 @@\n+second\n",
        "diff --git a/app.py b/app.py\n@@ -1,0 +2,1 @@\n+a\ndiff --git a/x b/x\n@@ -0,0 +1 @@\n+b\n",
        "diff --git a/app.py b/app.py\n@@ not a hunk header\n+second\n",
    ],
)
def test_unknown_shape_in_one_paths_diff_is_rejected(shape: str) -> None:
    added, error = source.parse_path_added_lines(shape)
    assert added == {}
    assert error is not None


def test_a_binary_note_is_opaque() -> None:
    with pytest.raises(source.UnusableInput, match="opaque change cannot be scanned"):
        source.parse_path_added_lines(
            "diff --git a/blob.bin b/blob.bin\nindex 123..456 100644\n"
            "Binary files a/blob.bin and b/blob.bin differ\n"
        )


def test_binary_post_image_is_opaque(tmp_path: Path) -> None:
    repo, _base, _diff = _repo(tmp_path)
    _git(repo, "checkout", "-q", "HEAD")
    (repo / "blob.bin").write_bytes(b"text\x00binary")
    _git(repo, "add", "blob.bin")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "binary base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "app.py").write_text("changed\n")
    diff = _git(repo, "diff", base)
    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        assert source.post_image_blob("blob.bin", repo=repo, env=env) is None


def test_regeneration_error_has_a_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base, diff = _repo(tmp_path)
    original = source._run_git

    def fail_diff(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[0][0] == "diff":  # type: ignore[index]
            return subprocess.CompletedProcess(["git", "diff"], 1, "", "failed")
        return original(*args, **kwargs)  # type: ignore[arg-type]

    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        monkeypatch.setattr(source, "_run_git", fail_diff)
        files, error = source.regenerated_added_lines(repo=repo, base=base, env=env)
    assert files == {}
    assert error is not None and "Next action" in error


def test_deletion_has_no_added_lines(tmp_path: Path) -> None:
    repo, base, _diff = _repo(tmp_path)
    (repo / "app.py").unlink()
    diff = _git(repo, "diff", base)
    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        files, error = source.regenerated_added_lines(repo=repo, base=base, env=env)
    assert error is None
    assert files == {}


def test_renamed_file_uses_its_post_image_path(tmp_path: Path) -> None:
    repo, base, _diff = _repo(tmp_path)
    _git(repo, "mv", "app.py", "renamed.py")
    (repo / "renamed.py").write_text("first\nsecond\nthird\n")
    # Stage both the renamed path and its added lines in the input.
    _git(repo, "add", "renamed.py")
    diff = _git(repo, "diff", "--cached", "--find-renames", base)
    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        files, error = source.regenerated_added_lines(repo=repo, base=base, env=env)
    assert error is None
    assert "app.py" not in files
    # Git may render the rename as delete + add; scanning the entire new path is conservative.
    assert files["renamed.py"] == {1: "first", 2: "second", 3: "third"}


KEY_LINE = 'client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])'


def _added_after(tmp_path: Path, files: dict[str, tuple[str, str]]) -> dict[str, dict[int, str]]:
    """Commit each path's base text, write its head text, and read Git's added lines."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name, (before, _after) in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(before)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    for name, (_before, after) in files.items():
        (repo / name).write_text(after)
    diff = _git(repo, "diff", "--unified=0", base)
    with source.materialise_post_image(diff, repo=repo, base=base) as (_index, env):
        added, error = source.regenerated_added_lines(repo=repo, base=base, env=env)
    assert error is None, error
    return added


def test_an_added_line_shaped_like_a_header_cannot_hide_a_later_hunk(tmp_path: Path) -> None:
    """codex (#4844 round 4): `++ b/docs/hidden.py` renders `+++ b/docs/hidden.py`; read as a header
    it attributed the later credential hunk to a skipped docs path, a false pass."""
    before = 'import os\nNOTE = """\nfirst\n"""\n\nvalue = 1\n'
    after = f'import os\nNOTE = """\nfirst\n++ b/docs/hidden.py\n"""\n\nvalue = 1\n{KEY_LINE}\n'
    added = _added_after(tmp_path, {"app.py": (before, after)})
    assert added == {"app.py": {4: "++ b/docs/hidden.py", 8: KEY_LINE}}


@pytest.mark.parametrize(
    "shaped",
    [
        "++ b/x",
        "++ b/docs/hidden.py",
        "++ /dev/null",
        "++ c/x",
        "+++ b/x",
        "--- a/x",
        "-- a/x",
        "diff --git a/x b/x",
        "@@ -1 +1 @@",
        "index 0000000..1111111 100644",
        "new file mode 100644",
        "Binary files a/x and b/x differ",
        "\\ No newline at end of file",
    ],
)
def test_no_header_shaped_added_line_moves_a_later_hunk(tmp_path: Path, shaped: str) -> None:
    before = "a\nb\nc\nd\n"
    after = f"a\n{shaped}\nb\nc\nd\n{KEY_LINE}\n"
    added = _added_after(tmp_path, {"app.py": (before, after)})
    assert added == {"app.py": {2: shaped, 6: KEY_LINE}}


@pytest.mark.parametrize("shaped", ["-- a/x", "++ b/docs/hidden.py", "- removed"])
def test_a_header_shaped_removed_line_does_not_drop_the_next_hunk(
    tmp_path: Path, shaped: str
) -> None:
    before = f"a\n{shaped}\nb\nc\nd\n"
    after = f"a\nb\nc\nd\n{KEY_LINE}\n"
    added = _added_after(tmp_path, {"app.py": (before, after)})
    assert added == {"app.py": {5: KEY_LINE}}


def test_each_file_is_attributed_by_its_own_git_path(tmp_path: Path) -> None:
    added = _added_after(
        tmp_path,
        {
            "x.py": ("one\n", f"one\n{KEY_LINE}\n"),
            "[x].py": ("one\n", "one\n++ b/x.py\n"),
            "docs/notes.md": ("n\n", "n\n++ b/app.py\n"),
        },
    )
    assert added == {
        "x.py": {2: KEY_LINE},
        "[x].py": {2: "++ b/x.py"},
        "docs/notes.md": {2: "++ b/app.py"},
    }


def test_context_line_in_closed_grammar_is_not_added() -> None:
    added, error = source.parse_path_added_lines(
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
        "@@ -1,1 +1,2 @@\n first\n+second\n"
    )
    assert error is None
    assert added == {2: "second"}
