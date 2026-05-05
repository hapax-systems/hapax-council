"""Tests for ``shared.research_registry_writer``.

Pins the JSONL append semantics, content-hashed entry_id derivation,
and dedup-friendly read path that downstream consumers (the braid
witness probe, the producer scanner) rely on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.research_registry_writer import (
    ResearchRegistryEntry,
    append_entry,
    build_entry,
    compute_sha256,
    derive_entry_id,
    derive_title,
    known_entry_ids,
    read_entries,
)

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _md(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ── Content hashing ─────────────────────────────────────────────────────


class TestComputeSha256:
    def test_empty_file_hashes_to_canonical_empty(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "empty.md", "")
        result = compute_sha256(path)
        assert result == hashlib.sha256(b"").hexdigest()

    def test_known_content_round_trips(self, tmp_path: Path) -> None:
        body = "# Hello\n\nbody.\n"
        path = _md(tmp_path / "x.md", body)
        result = compute_sha256(path)
        assert result == hashlib.sha256(body.encode("utf-8")).hexdigest()

    def test_large_file_streams(self, tmp_path: Path) -> None:
        # 256KB > HASH_CHUNK_BYTES — ensures streaming path is exercised
        body = "x" * (256 * 1024)
        path = _md(tmp_path / "big.md", body)
        result = compute_sha256(path)
        assert result == hashlib.sha256(body.encode("utf-8")).hexdigest()


# ── entry_id derivation ─────────────────────────────────────────────────


class TestDeriveEntryId:
    def test_format_kind_dash_sha_prefix(self) -> None:
        sha = "a" * 64
        result = derive_entry_id("spec", sha)
        assert result == "spec-aaaaaaaaaaaa"

    def test_different_kind_changes_id(self) -> None:
        sha = "0123456789ab" + "f" * 52
        spec_id = derive_entry_id("spec", sha)
        plan_id = derive_entry_id("plan", sha)
        assert spec_id != plan_id


# ── derive_title ────────────────────────────────────────────────────────


class TestDeriveTitle:
    def test_first_h1_wins(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "x.md", "# Real Title\n\nBody\n")
        assert derive_title(path) == "Real Title"

    def test_falls_back_to_stem_when_no_h1(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "no-heading.md", "Just body text\n")
        assert derive_title(path) == "no-heading"

    def test_skips_h2_for_h1(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "x.md", "## Subhead\n\n# Actual Title\n")
        assert derive_title(path) == "Actual Title"

    def test_truncates_after_50_lines(self, tmp_path: Path) -> None:
        body = "\n".join("blank" for _ in range(60)) + "\n# Late Title\n"
        path = _md(tmp_path / "late.md", body)
        # H1 appears past line 50 → falls back to stem
        assert derive_title(path) == "late"

    def test_handles_unreadable_file(self, tmp_path: Path) -> None:
        # Path that doesn't exist
        result = derive_title(tmp_path / "missing.md")
        assert result == "missing"


# ── build_entry ─────────────────────────────────────────────────────────


class TestBuildEntry:
    def test_canonical_fields_populated(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "specs/2026-05-04-design.md", "# Design\n\nBody\n")
        entry = build_entry(path, kind="spec", repo_root=tmp_path, now=NOW)
        assert entry.kind == "spec"
        assert entry.title == "Design"
        assert entry.source_path == "specs/2026-05-04-design.md"
        assert entry.byte_size == path.stat().st_size
        assert entry.registered_at == NOW
        assert entry.entry_id.startswith("spec-")
        assert len(entry.sha256) == 64

    def test_entry_id_stable_across_calls(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "x.md", "# Stable\n")
        a = build_entry(path, kind="spec", now=NOW)
        b = build_entry(path, kind="spec", now=NOW)
        assert a.entry_id == b.entry_id
        assert a.sha256 == b.sha256

    def test_content_change_changes_entry_id(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "x.md", "# Original\n")
        a = build_entry(path, kind="spec", now=NOW)
        path.write_text("# Edited\n", encoding="utf-8")
        b = build_entry(path, kind="spec", now=NOW)
        assert a.entry_id != b.entry_id

    def test_absolute_path_when_outside_repo_root(self, tmp_path: Path) -> None:
        # File outside repo_root → absolute path string
        outside = _md(tmp_path / "elsewhere.md", "# Outside\n")
        entry = build_entry(outside, kind="spec", repo_root=tmp_path / "subdir")
        assert Path(entry.source_path).is_absolute()

    def test_tags_round_trip(self, tmp_path: Path) -> None:
        path = _md(tmp_path / "x.md", "# T\n")
        entry = build_entry(path, kind="spec", tags=["braid", "wsjf"])
        assert entry.tags == ["braid", "wsjf"]


# ── append + read round-trip ────────────────────────────────────────────


class TestAppendAndRead:
    def _entry(self, suffix: str = "0") -> ResearchRegistryEntry:
        sha = (suffix * 12).ljust(64, "0")
        return ResearchRegistryEntry(
            entry_id=f"spec-{sha[:12]}",
            kind="spec",
            title="Test",
            source_path=f"docs/{suffix}.md",
            registered_at=NOW,
            byte_size=42,
            sha256=sha,
        )

    def test_append_creates_parent_dir(self, tmp_path: Path) -> None:
        registry = tmp_path / "nested/sub/registry.jsonl"
        append_entry(self._entry(), registry)
        assert registry.exists()

    def test_append_then_read_round_trip(self, tmp_path: Path) -> None:
        registry = tmp_path / "registry.jsonl"
        e1 = self._entry("a")
        e2 = self._entry("b")
        append_entry(e1, registry)
        append_entry(e2, registry)
        result = list(read_entries(registry))
        assert [r.entry_id for r in result] == [e1.entry_id, e2.entry_id]

    def test_read_skips_malformed_lines(self, tmp_path: Path) -> None:
        registry = tmp_path / "registry.jsonl"
        append_entry(self._entry("a"), registry)
        # Manually corrupt: append a bad line
        with registry.open("a", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write("\n")  # blank line
        append_entry(self._entry("b"), registry)
        result = list(read_entries(registry))
        assert len(result) == 2

    def test_read_skips_schema_violations(self, tmp_path: Path) -> None:
        registry = tmp_path / "registry.jsonl"
        # Valid entry
        append_entry(self._entry("a"), registry)
        # Schema-violating row (missing required field)
        with registry.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"entry_id": "broken"}) + "\n")
        result = list(read_entries(registry))
        assert len(result) == 1

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = list(read_entries(tmp_path / "absent.jsonl"))
        assert result == []


# ── known_entry_ids ─────────────────────────────────────────────────────


class TestKnownEntryIds:
    def _write(self, registry: Path, entries: list[ResearchRegistryEntry]) -> None:
        for entry in entries:
            append_entry(entry, registry)

    def _entry(self, suffix: str = "0", kind: str = "spec") -> ResearchRegistryEntry:
        sha = (suffix * 12).ljust(64, "0")
        return ResearchRegistryEntry(
            entry_id=f"{kind}-{sha[:12]}",
            kind=kind,  # type: ignore[arg-type]
            title="T",
            source_path=f"docs/{suffix}.md",
            registered_at=NOW,
            byte_size=1,
            sha256=sha,
        )

    def test_known_entry_ids_returns_set(self, tmp_path: Path) -> None:
        registry = tmp_path / "registry.jsonl"
        self._write(registry, [self._entry("a"), self._entry("b", kind="plan")])
        ids = known_entry_ids(registry)
        assert len(ids) == 2
        assert {i.split("-")[0] for i in ids} == {"spec", "plan"}

    def test_known_entry_ids_empty_when_no_file(self, tmp_path: Path) -> None:
        assert known_entry_ids(tmp_path / "absent.jsonl") == set()


# ── ResearchRegistryEntry validation ────────────────────────────────────


class TestEntryValidation:
    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValueError, match="Extra inputs"):
            ResearchRegistryEntry(
                entry_id="spec-aaaaaaaaaaaa",
                kind="spec",
                title="T",
                source_path="x.md",
                registered_at=NOW,
                byte_size=1,
                sha256="a" * 64,
                bogus="value",  # type: ignore[call-arg]
            )

    def test_invalid_sha256_rejected(self) -> None:
        with pytest.raises(ValueError):
            ResearchRegistryEntry(
                entry_id="spec-aaaaaaaaaaaa",
                kind="spec",
                title="T",
                source_path="x.md",
                registered_at=NOW,
                byte_size=1,
                sha256="not-hex",
            )

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(ValueError):
            ResearchRegistryEntry(
                entry_id="invalid-aaaaaaaaaaaa",
                kind="bogus",  # type: ignore[arg-type]
                title="T",
                source_path="x.md",
                registered_at=NOW,
                byte_size=1,
                sha256="a" * 64,
            )

    def test_negative_byte_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            ResearchRegistryEntry(
                entry_id="spec-aaaaaaaaaaaa",
                kind="spec",
                title="T",
                source_path="x.md",
                registered_at=NOW,
                byte_size=-1,
                sha256="a" * 64,
            )
