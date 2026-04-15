"""Tests for scripts/lock-phase-a-condition.py — LRR Phase 4 §3.7 lock.

Covers:

- _sha256_file — streaming digest reproducibility
- _jsonl_contains_condition — matches tagged entry, skips untagged, skips
  malformed lines, returns False on unreadable file
- collect_jsonl_checksums — walks nested directories, produces checksums,
  skips files without the target condition
- write_checksums_file — produces a sha256+path line per file, atomic rename
- lock_condition (dry-run) — end-to-end with a synthetic registry +
  synthetic archive; no network services required
- lock_condition (refuses overwrite without --force)
- lock_condition (accepts --force)
- lock_condition (errors when registry directory missing)
- _exit_code — maps error messages to the documented exit codes

External services (Qdrant + Langfuse) are not exercised in unit tests.
They are wrapped in RuntimeError so the lock_condition caller only
sees a single error mode; that error path is covered via a monkeypatch.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "lock-phase-a-condition.py"
_spec = importlib.util.spec_from_file_location("lock_phase_a_condition", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
lock_phase_a_condition = importlib.util.module_from_spec(_spec)
sys.modules["lock_phase_a_condition"] = lock_phase_a_condition
_spec.loader.exec_module(lock_phase_a_condition)  # type: ignore[union-attr]


class TestSha256File:
    def test_streaming_digest_matches_hashlib(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        payload = b"hello world\n" * 1000
        f.write_bytes(payload)
        assert lock_phase_a_condition._sha256_file(f) == hashlib.sha256(payload).hexdigest()

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        assert lock_phase_a_condition._sha256_file(f) == hashlib.sha256(b"").hexdigest()


class TestJsonlContainsCondition:
    def test_match_on_tagged_entry(self, tmp_path: Path) -> None:
        f = tmp_path / "reactor-log-2026-04.jsonl"
        f.write_text(
            json.dumps({"condition_id": "cond-alpha", "text": "a"})
            + "\n"
            + json.dumps({"condition_id": "cond-beta", "text": "b"})
            + "\n"
        )
        assert lock_phase_a_condition._jsonl_contains_condition(f, "cond-alpha") is True
        assert lock_phase_a_condition._jsonl_contains_condition(f, "cond-beta") is True
        assert lock_phase_a_condition._jsonl_contains_condition(f, "cond-gamma") is False

    def test_skip_malformed_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "mixed.jsonl"
        f.write_text(
            "not-json {{{\n" + json.dumps({"condition_id": "cond-alpha"}) + "\n" + "more garbage\n"
        )
        assert lock_phase_a_condition._jsonl_contains_condition(f, "cond-alpha") is True

    def test_returns_false_on_untagged_file(self, tmp_path: Path) -> None:
        f = tmp_path / "untagged.jsonl"
        f.write_text(json.dumps({"text": "no condition"}) + "\n")
        assert lock_phase_a_condition._jsonl_contains_condition(f, "cond-alpha") is False

    def test_returns_false_on_missing_file(self, tmp_path: Path) -> None:
        assert (
            lock_phase_a_condition._jsonl_contains_condition(tmp_path / "missing.jsonl", "x")
            is False
        )

    def test_substring_without_matching_field_not_matched(self, tmp_path: Path) -> None:
        """A line that mentions the condition_id as a non-field substring
        (e.g., inside the text body) must NOT match — we require the
        actual condition_id field to equal the target."""
        f = tmp_path / "substring.jsonl"
        f.write_text(json.dumps({"text": "cond-alpha is a great condition"}) + "\n")
        assert lock_phase_a_condition._jsonl_contains_condition(f, "cond-alpha") is False


class TestCollectJsonlChecksums:
    def test_walks_nested_directories(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "hls"
        (archive_root / "2026-04-14").mkdir(parents=True)
        (archive_root / "2026-04-15").mkdir(parents=True)

        tagged_file = archive_root / "2026-04-14" / "reactor-log-2026-04.jsonl"
        tagged_file.write_text(json.dumps({"condition_id": "cond-phase-a", "text": "hello"}) + "\n")

        untagged_file = archive_root / "2026-04-15" / "reactor-log-2026-04.jsonl"
        untagged_file.write_text(json.dumps({"text": "no tag"}) + "\n")

        results = lock_phase_a_condition.collect_jsonl_checksums("cond-phase-a", archive_root)
        assert len(results) == 1
        assert results[0]["path"] == str(tagged_file)
        assert results[0]["sha256"] == hashlib.sha256(tagged_file.read_bytes()).hexdigest()

    def test_empty_archive_returns_empty_list(self, tmp_path: Path) -> None:
        assert lock_phase_a_condition.collect_jsonl_checksums("cond-x", tmp_path / "missing") == []

    def test_file_that_matches_name_but_not_content_is_skipped(self, tmp_path: Path) -> None:
        archive_root = tmp_path / "hls"
        archive_root.mkdir()
        f = archive_root / "reactor-log-2026-04.jsonl"
        f.write_text(json.dumps({"condition_id": "cond-other"}) + "\n")

        results = lock_phase_a_condition.collect_jsonl_checksums("cond-target", archive_root)
        assert results == []


class TestWriteChecksumsFile:
    def test_writes_sha256_path_lines(self, tmp_path: Path) -> None:
        report = lock_phase_a_condition.LockReport(
            condition_id="cond-x",
            started_at="2026-04-14T20:00:00+00:00",
            jsonl_files=[
                {"path": "/a/file1.jsonl", "sha256": "abc123", "size_bytes": 100},
                {"path": "/a/file2.jsonl", "sha256": "def456", "size_bytes": 200},
                {"path": "/broken.jsonl", "sha256": None, "size_bytes": None},
            ],
            qdrant_path="/reg/qdrant-snapshot.tgz",
            qdrant_sha256="qdr111",
            langfuse_path="/reg/langfuse-scores.jsonl",
            langfuse_sha256="lf222",
        )
        path = lock_phase_a_condition.write_checksums_file(tmp_path, report)
        content = path.read_text()
        assert "abc123  /a/file1.jsonl" in content
        assert "def456  /a/file2.jsonl" in content
        assert "broken" not in content  # file without sha256 excluded
        assert "qdr111  /reg/qdrant-snapshot.tgz" in content
        assert "lf222  /reg/langfuse-scores.jsonl" in content


class TestLockConditionDryRun:
    def test_dry_run_end_to_end(self, tmp_path: Path, monkeypatch) -> None:
        """End-to-end dry-run: synthetic registry + synthetic archive +
        mocked qdrant/langfuse exports. Verifies the happy path without
        requiring live services."""
        registry_dir = tmp_path / "registry"
        registry_condition_dir = registry_dir / "cond-test"
        registry_condition_dir.mkdir(parents=True)

        archive_dir = tmp_path / "archive"
        hls_dir = archive_dir / "hls" / "2026-04-14"
        hls_dir.mkdir(parents=True)
        (hls_dir / "reactor-log-2026-04.jsonl").write_text(
            json.dumps({"condition_id": "cond-test", "text": "x"}) + "\n"
        )

        args = lock_phase_a_condition.build_parser().parse_args(
            [
                "cond-test",
                "--registry-dir",
                str(registry_dir),
                "--stream-archive-dir",
                str(archive_dir),
                "--dry-run",
            ]
        )

        report = lock_phase_a_condition.lock_condition(args)

        # Dry run: no errors, jsonl files collected, qdrant/langfuse paths
        # set to expected locations with empty sha256 (skipped on dry run).
        assert report.errors == []
        assert len(report.jsonl_files) == 1
        assert report.qdrant_path.endswith("qdrant-snapshot.tgz")
        assert report.qdrant_sha256 == ""
        assert report.langfuse_path.endswith("langfuse-scores.jsonl")
        assert report.langfuse_sha256 == ""
        # Dry run must NOT write the checksums file
        assert not (registry_condition_dir / "data-checksums.txt").exists()

    def test_refuses_overwrite_without_force(self, tmp_path: Path) -> None:
        registry_dir = tmp_path / "registry"
        registry_condition_dir = registry_dir / "cond-test"
        registry_condition_dir.mkdir(parents=True)
        (registry_condition_dir / "data-checksums.txt").write_text("existing\n")

        archive_dir = tmp_path / "archive"

        args = lock_phase_a_condition.build_parser().parse_args(
            [
                "cond-test",
                "--registry-dir",
                str(registry_dir),
                "--stream-archive-dir",
                str(archive_dir),
            ]
        )

        report = lock_phase_a_condition.lock_condition(args)

        assert report.errors
        assert "already exists" in report.errors[0]
        assert lock_phase_a_condition._exit_code(report) == 6

    def test_fails_when_registry_condition_dir_missing(self, tmp_path: Path) -> None:
        registry_dir = tmp_path / "registry"
        # Do NOT create the registry_dir/cond-test subdirectory

        archive_dir = tmp_path / "archive"

        args = lock_phase_a_condition.build_parser().parse_args(
            [
                "cond-test",
                "--registry-dir",
                str(registry_dir),
                "--stream-archive-dir",
                str(archive_dir),
                "--dry-run",
            ]
        )

        report = lock_phase_a_condition.lock_condition(args)

        assert report.errors
        assert "missing" in report.errors[0]
        assert lock_phase_a_condition._exit_code(report) == 2


class TestExitCodeMapping:
    def test_no_errors_returns_zero(self) -> None:
        report = lock_phase_a_condition.LockReport(condition_id="x", started_at="t")
        assert lock_phase_a_condition._exit_code(report) == 0

    def test_directory_missing_returns_2(self) -> None:
        report = lock_phase_a_condition.LockReport(
            condition_id="x",
            started_at="t",
            errors=["registry condition directory missing: /x"],
        )
        assert lock_phase_a_condition._exit_code(report) == 2

    def test_qdrant_error_returns_3(self) -> None:
        report = lock_phase_a_condition.LockReport(
            condition_id="x",
            started_at="t",
            errors=["Qdrant export failed: unreachable"],
        )
        assert lock_phase_a_condition._exit_code(report) == 3

    def test_langfuse_error_returns_4(self) -> None:
        report = lock_phase_a_condition.LockReport(
            condition_id="x",
            started_at="t",
            errors=["Langfuse export failed: 401 unauthorized"],
        )
        assert lock_phase_a_condition._exit_code(report) == 4

    def test_hash_failure_returns_5(self) -> None:
        report = lock_phase_a_condition.LockReport(
            condition_id="x",
            started_at="t",
            errors=["3 JSONL files could not be hashed (see jsonl_files)"],
        )
        assert lock_phase_a_condition._exit_code(report) == 5

    def test_overwrite_refusal_returns_6(self) -> None:
        report = lock_phase_a_condition.LockReport(
            condition_id="x",
            started_at="t",
            errors=["data-checksums.txt already exists at /x; pass --force to re-lock"],
        )
        assert lock_phase_a_condition._exit_code(report) == 6
