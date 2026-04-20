"""Tests for shared/attribution.py — Phase 1 of YouTube broadcast bundle.

Verifies AttributionEntry shape, AttributionRingBuffer TTL+cap, and
AttributionFileWriter atomic append + read_all roundtrip.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest  # noqa: TC002

from shared.attribution import (
    AttributionEntry,
    AttributionFileWriter,
    AttributionRingBuffer,
)


class TestAttributionEntryShape:
    def test_basic_entry(self) -> None:
        entry = AttributionEntry(
            kind="citation",
            url="https://nature.com/articles/123",
            title="Test article",
            source="chat:hash-of-author",
        )
        assert entry.kind == "citation"
        assert entry.title == "Test article"
        assert entry.source == "chat:hash-of-author"

    def test_dataclass_is_frozen(self) -> None:
        entry = AttributionEntry(kind="citation", url="https://x.com/y")
        with pytest.raises(Exception):  # noqa: B017 — frozen dataclass
            entry.url = "https://other.com"  # type: ignore[misc]

    def test_emitted_at_defaults_to_now(self) -> None:
        before = datetime.now(UTC)
        entry = AttributionEntry(kind="citation", url="https://x.com/y")
        after = datetime.now(UTC)
        assert before <= entry.emitted_at <= after

    def test_empty_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="url cannot be empty"):
            AttributionEntry(kind="citation", url="   ")

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="not in"):
            AttributionEntry(kind="bogus_kind", url="https://x.com")  # type: ignore[arg-type]


class TestDedupKey:
    def test_same_kind_same_url_same_key(self) -> None:
        a = AttributionEntry(kind="citation", url="https://x.com/y", title="A")
        b = AttributionEntry(kind="citation", url="https://x.com/y", title="B")
        assert a.dedup_key == b.dedup_key

    def test_different_url_different_key(self) -> None:
        a = AttributionEntry(kind="citation", url="https://x.com/y")
        b = AttributionEntry(kind="citation", url="https://x.com/z")
        assert a.dedup_key != b.dedup_key

    def test_different_kind_different_key(self) -> None:
        a = AttributionEntry(kind="citation", url="https://x.com/y")
        b = AttributionEntry(kind="album-ref", url="https://x.com/y")
        assert a.dedup_key != b.dedup_key


class TestAttributionRingBuffer:
    def test_add_and_snapshot(self) -> None:
        buf = AttributionRingBuffer()
        e1 = AttributionEntry(kind="citation", url="https://x.com/1")
        e2 = AttributionEntry(kind="citation", url="https://x.com/2")
        buf.add(e1)
        buf.add(e2)
        snapshot = buf.snapshot(kind="citation")
        assert len(snapshot) == 2

    def test_per_kind_isolation(self) -> None:
        buf = AttributionRingBuffer()
        buf.add(AttributionEntry(kind="citation", url="https://x.com/1"))
        buf.add(AttributionEntry(kind="album-ref", url="https://b.c/1"))
        assert len(buf.snapshot(kind="citation")) == 1
        assert len(buf.snapshot(kind="album-ref")) == 1

    def test_size_cap_evicts_oldest(self) -> None:
        buf = AttributionRingBuffer(max_per_kind=3)
        for i in range(5):
            buf.add(AttributionEntry(kind="citation", url=f"https://x.com/{i}"))
        snapshot = buf.snapshot(kind="citation")
        # Only last 3 survive; first two evicted
        assert len(snapshot) == 3
        urls = {e.url for e in snapshot}
        assert "https://x.com/0" not in urls
        assert "https://x.com/4" in urls

    def test_ttl_drops_stale_entries(self) -> None:
        buf = AttributionRingBuffer(ttl_seconds=60.0)
        old = AttributionEntry(
            kind="citation",
            url="https://x.com/old",
            emitted_at=datetime.now(UTC) - timedelta(seconds=120),
        )
        fresh = AttributionEntry(kind="citation", url="https://x.com/fresh")
        buf.add(old)
        buf.add(fresh)
        snapshot = buf.snapshot(kind="citation")
        assert len(snapshot) == 1
        assert snapshot[0].url == "https://x.com/fresh"

    def test_snapshot_all_kinds(self) -> None:
        buf = AttributionRingBuffer()
        buf.add(AttributionEntry(kind="citation", url="https://x.com/1"))
        buf.add(AttributionEntry(kind="album-ref", url="https://b.c/1"))
        snapshot = buf.snapshot()  # no kind filter
        assert len(snapshot) == 2

    def test_thread_safety(self) -> None:
        """Concurrent add() from multiple threads should not corrupt state."""
        buf = AttributionRingBuffer()

        def worker(start: int) -> None:
            for i in range(20):
                buf.add(AttributionEntry(kind="citation", url=f"https://x.com/{start}-{i}"))

        threads = [threading.Thread(target=worker, args=(s,)) for s in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 4 workers × 20 entries = 80 entries (default max=100 per kind, so all fit)
        assert len(buf.snapshot(kind="citation")) == 80


class TestAttributionFileWriter:
    def test_append_creates_file(self, tmp_path: Path) -> None:
        writer = AttributionFileWriter(root=tmp_path)
        entry = AttributionEntry(kind="citation", url="https://x.com/1")
        writer.append(entry)
        assert (tmp_path / "citation.jsonl").exists()

    def test_append_writes_jsonl_line(self, tmp_path: Path) -> None:
        writer = AttributionFileWriter(root=tmp_path)
        entry = AttributionEntry(
            kind="citation",
            url="https://x.com/1",
            title="Test",
            source="hashed-author",
        )
        writer.append(entry)
        content = (tmp_path / "citation.jsonl").read_text()
        assert content.endswith("\n")
        line = json.loads(content.strip())
        assert line["url"] == "https://x.com/1"
        assert line["title"] == "Test"
        assert line["source"] == "hashed-author"

    def test_per_kind_files(self, tmp_path: Path) -> None:
        writer = AttributionFileWriter(root=tmp_path)
        writer.append(AttributionEntry(kind="citation", url="https://x.com/1"))
        writer.append(AttributionEntry(kind="album-ref", url="https://b.c/1"))
        assert (tmp_path / "citation.jsonl").exists()
        assert (tmp_path / "album-ref.jsonl").exists()

    def test_read_all_roundtrip(self, tmp_path: Path) -> None:
        writer = AttributionFileWriter(root=tmp_path)
        e1 = AttributionEntry(kind="citation", url="https://x.com/1", title="A")
        e2 = AttributionEntry(kind="citation", url="https://x.com/2", title="B")
        writer.append(e1)
        writer.append(e2)
        loaded = writer.read_all("citation")
        assert len(loaded) == 2
        assert {e.url for e in loaded} == {"https://x.com/1", "https://x.com/2"}

    def test_read_all_missing_kind(self, tmp_path: Path) -> None:
        writer = AttributionFileWriter(root=tmp_path)
        assert writer.read_all("citation") == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "citation.jsonl"
        path.write_text(
            "{not valid json\n"
            + json.dumps(
                {
                    "kind": "citation",
                    "url": "https://x.com/ok",
                    "emitted_at": "2026-04-20T00:00:00+00:00",
                }
            )
            + "\n"
        )
        writer = AttributionFileWriter(root=tmp_path)
        loaded = writer.read_all("citation")
        # Only the valid entry survives
        assert len(loaded) == 1
        assert loaded[0].url == "https://x.com/ok"
