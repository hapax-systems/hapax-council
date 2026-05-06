"""Tests for ``shared.research_registry_scanner``.

Pins the scan-and-register flow: dedup against existing journal,
multi-root traversal, dry-run separation of compute-vs-write, error
collection per file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from shared.research_registry_scanner import (
    ScanRoot,
    default_scan_roots,
    scan_and_register,
)
from shared.research_registry_writer import read_entries

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class TestScanAndRegister:
    def test_first_scan_appends_all(self, tmp_path: Path) -> None:
        specs = tmp_path / "docs/superpowers/specs"
        plans = tmp_path / "docs/superpowers/plans"
        _md(specs / "a.md", "# Spec A\n")
        _md(specs / "b.md", "# Spec B\n")
        _md(plans / "c.md", "# Plan C\n")
        registry = tmp_path / "registry.jsonl"

        result = scan_and_register(
            [
                ScanRoot(specs, "spec"),
                ScanRoot(plans, "plan"),
            ],
            registry_path=registry,
            repo_root=tmp_path,
            now=NOW,
        )

        assert result.scanned == 3
        assert result.new_entries == 3
        assert result.skipped_existing == 0
        assert result.errors == []
        assert len(list(read_entries(registry))) == 3

    def test_second_scan_dedups(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        _md(specs / "a.md", "# A\n")
        registry = tmp_path / "registry.jsonl"
        roots = [ScanRoot(specs, "spec")]

        first = scan_and_register(roots, registry_path=registry, repo_root=tmp_path, now=NOW)
        second = scan_and_register(roots, registry_path=registry, repo_root=tmp_path, now=NOW)

        assert first.new_entries == 1
        assert second.new_entries == 0
        assert second.skipped_existing == 1

    def test_content_change_triggers_new_entry(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        path = specs / "a.md"
        _md(path, "# Before\n")
        registry = tmp_path / "registry.jsonl"
        roots = [ScanRoot(specs, "spec")]

        first = scan_and_register(roots, registry_path=registry, repo_root=tmp_path, now=NOW)
        assert first.new_entries == 1

        path.write_text("# After\n", encoding="utf-8")
        second = scan_and_register(roots, registry_path=registry, repo_root=tmp_path, now=NOW)
        # Same kind + new sha => new entry_id => journal grows
        assert second.new_entries == 1
        assert len(list(read_entries(registry))) == 2

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        _md(specs / "a.md", "# A\n")
        registry = tmp_path / "registry.jsonl"

        result = scan_and_register(
            [ScanRoot(specs, "spec")],
            registry_path=registry,
            repo_root=tmp_path,
            now=NOW,
            dry_run=True,
        )

        assert result.new_entries == 1
        assert not registry.exists()

    def test_missing_root_dir_silent(self, tmp_path: Path) -> None:
        # Root path that doesn't exist — discover() should yield nothing
        registry = tmp_path / "registry.jsonl"
        result = scan_and_register(
            [ScanRoot(tmp_path / "absent", "spec")],
            registry_path=registry,
            repo_root=tmp_path,
            now=NOW,
        )
        assert result.scanned == 0
        assert result.new_entries == 0
        assert result.errors == []

    def test_glob_filters_non_matching_files(self, tmp_path: Path) -> None:
        specs = tmp_path / "specs"
        _md(specs / "a.md", "# A\n")
        _md(specs / "ignored.txt", "not markdown\n")
        registry = tmp_path / "registry.jsonl"

        result = scan_and_register(
            [ScanRoot(specs, "spec", glob="*.md")],
            registry_path=registry,
            repo_root=tmp_path,
            now=NOW,
        )
        assert result.scanned == 1
        assert result.new_entries == 1


class TestDefaultScanRoots:
    def test_six_roots_returned(self, tmp_path: Path) -> None:
        roots = default_scan_roots(tmp_path)
        assert len(roots) == 6
        assert {r.kind for r in roots} == {
            "spec",
            "plan",
            "research-drop",
            "audit",
            "voice-grounding",
            "bayesian-validation",
        }

    def test_paths_under_repo_root(self, tmp_path: Path) -> None:
        roots = default_scan_roots(tmp_path)
        for root in roots:
            # Each scan root path must be under the supplied repo root.
            root.path.resolve().relative_to(tmp_path.resolve())
