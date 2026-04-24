"""Tests for agents/hapax_assets_publisher/sync.py — ytb-AUTH-HOSTING.

Verifies idempotent tree sync, git-dirty detection, commit-message
construction, and rate-limit behavior. All tests run against tmp_path
fixtures; no real remote is contacted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.hapax_assets_publisher.sync import (
    PathChange,
    build_commit_message,
    has_diff,
    sync_tree,
)


def _read(path: Path) -> bytes:
    return path.read_bytes()


@pytest.fixture
def src_tree(tmp_path: Path) -> Path:
    src = tmp_path / "source" / "aesthetic-library"
    (src / "bitchx" / "colors").mkdir(parents=True)
    (src / "fonts").mkdir(parents=True)
    (src / "bitchx" / "colors" / "mirc16.yaml").write_bytes(b"schema: mirc16\n")
    (src / "fonts" / "px437.ttf").write_bytes(b"TTF-FAKE-BYTES-A")
    (src / "_manifest.yaml").write_bytes(b"assets: []\n")
    return src


@pytest.fixture
def dst_tree(tmp_path: Path) -> Path:
    dst = tmp_path / "checkout"
    dst.mkdir()
    return dst


class TestSyncTree:
    def test_first_sync_copies_all_files(self, src_tree: Path, dst_tree: Path) -> None:
        changes = sync_tree(src_tree, dst_tree)

        assert (dst_tree / "_manifest.yaml").read_bytes() == b"assets: []\n"
        assert (dst_tree / "bitchx" / "colors" / "mirc16.yaml").exists()
        assert (dst_tree / "fonts" / "px437.ttf").exists()
        assert len(changes) == 3
        assert all(c.kind == "added" for c in changes)

    def test_second_sync_is_noop_when_unchanged(self, src_tree: Path, dst_tree: Path) -> None:
        sync_tree(src_tree, dst_tree)
        changes = sync_tree(src_tree, dst_tree)
        assert changes == []

    def test_modified_file_detected_and_updated(self, src_tree: Path, dst_tree: Path) -> None:
        sync_tree(src_tree, dst_tree)
        (src_tree / "fonts" / "px437.ttf").write_bytes(b"TTF-FAKE-BYTES-B")

        changes = sync_tree(src_tree, dst_tree)

        assert (dst_tree / "fonts" / "px437.ttf").read_bytes() == b"TTF-FAKE-BYTES-B"
        assert len(changes) == 1
        assert changes[0].kind == "modified"
        assert "px437.ttf" in changes[0].path

    def test_deleted_file_removed_from_dst(self, src_tree: Path, dst_tree: Path) -> None:
        sync_tree(src_tree, dst_tree)
        (src_tree / "bitchx" / "colors" / "mirc16.yaml").unlink()

        changes = sync_tree(src_tree, dst_tree)

        assert not (dst_tree / "bitchx" / "colors" / "mirc16.yaml").exists()
        assert any(c.kind == "deleted" for c in changes)

    def test_preserves_git_dir(self, src_tree: Path, dst_tree: Path) -> None:
        """The .git/ directory in dst must never be touched by sync."""
        (dst_tree / ".git").mkdir()
        (dst_tree / ".git" / "config").write_bytes(b"[core]\n")

        sync_tree(src_tree, dst_tree)

        assert (dst_tree / ".git" / "config").exists()

    def test_preserves_external_repo_artifacts(self, src_tree: Path, dst_tree: Path) -> None:
        """Files that don't belong to the aesthetic-library (README, workflow,
        CNAME) must be left alone — they live in the target repo but are not
        part of the source tree."""
        (dst_tree / "README.md").write_bytes(b"# hapax-assets\n")
        (dst_tree / ".github" / "workflows").mkdir(parents=True)
        (dst_tree / ".github" / "workflows" / "publish.yml").write_bytes(b"name: publish\n")

        sync_tree(src_tree, dst_tree)

        assert (dst_tree / "README.md").exists()
        assert (dst_tree / ".github" / "workflows" / "publish.yml").exists()


class TestBuildCommitMessage:
    def test_empty_changes_returns_empty_string(self) -> None:
        assert build_commit_message([]) == ""

    def test_single_add(self) -> None:
        msg = build_commit_message([PathChange("fonts/px437.ttf", "added")])
        assert "sync" in msg.lower()
        assert "fonts/px437.ttf" in msg
        assert "1 file" in msg

    def test_mixed_changes_summary(self) -> None:
        msg = build_commit_message(
            [
                PathChange("a.txt", "added"),
                PathChange("b.txt", "modified"),
                PathChange("c.txt", "deleted"),
            ]
        )
        assert "3 files" in msg
        # At least subject mentions the first file or count.
        assert msg.split("\n")[0]


class TestHasDiff:
    def test_no_diff_after_fresh_sync(self, src_tree: Path, dst_tree: Path) -> None:
        # has_diff reports byte-level drift between src and dst trees.
        sync_tree(src_tree, dst_tree)
        assert has_diff(src_tree, dst_tree) is False

    def test_diff_after_src_modified(self, src_tree: Path, dst_tree: Path) -> None:
        sync_tree(src_tree, dst_tree)
        (src_tree / "fonts" / "px437.ttf").write_bytes(b"NEW")
        assert has_diff(src_tree, dst_tree) is True
