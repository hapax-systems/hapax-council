"""Tests for ingest.py — pure-function tests that avoid heavy deps."""

import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from agents import ingest

# ── parse_frontmatter ────────────────────────────────────────────────────────


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        text = "---\ntitle: Hello World\nauthor: Operator\n---\nBody text here."
        meta, body = ingest.parse_frontmatter(text)
        assert meta["title"] == "Hello World"
        assert meta["author"] == "Operator"
        assert body == "Body text here."

    def test_list_values(self):
        text = "---\ntags: [foo, bar, baz]\n---\nContent."
        meta, body = ingest.parse_frontmatter(text)
        assert meta["tags"] == ["foo", "bar", "baz"]
        assert body == "Content."

    def test_quoted_values(self):
        text = '---\ntitle: "A title with: colons"\n---\nBody.'
        meta, body = ingest.parse_frontmatter(text)
        assert meta["title"] == "A title with: colons"

    def test_boolean_values(self):
        text = "---\nis_metadata_only: TRUE\nretrieval_eligible: False\n---\nBody."
        meta, body = ingest.parse_frontmatter(text)
        assert meta["is_metadata_only"] is True
        assert meta["retrieval_eligible"] is False
        assert body == "Body."

    def test_no_frontmatter(self):
        text = "Just plain text without any frontmatter."
        meta, body = ingest.parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_string(self):
        meta, body = ingest.parse_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_unclosed_frontmatter(self):
        text = "---\ntitle: Test\nNo closing delimiter"
        meta, body = ingest.parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_empty_frontmatter(self):
        text = "---\n---\nBody only."
        meta, body = ingest.parse_frontmatter(text)
        assert meta == {}
        assert body == "Body only."

    def test_value_with_colon(self):
        text = "---\nurl: http://example.com\n---\nBody."
        meta, body = ingest.parse_frontmatter(text)
        assert meta["url"] == "http://example.com"

    def test_empty_list(self):
        text = "---\ntags: []\n---\nBody."
        meta, body = ingest.parse_frontmatter(text)
        assert meta["tags"] == []

    def test_invalid_yaml_frontmatter_fails_closed(self):
        text = "---\ntitle: Good\nno-colon-here\nauthor: Also Good\n---\nBody."
        meta, body = ingest.parse_frontmatter(text)
        assert meta == {}
        assert body == text


# ── enrich_payload ───────────────────────────────────────────────────────────


class TestEnrichPayload:
    def test_known_keys_added(self):
        base = {"text": "hello", "source": "/file.md"}
        fm = {"content_type": "email", "timestamp": "2026-01-01"}
        result = ingest.enrich_payload(base, fm)
        assert result["content_type"] == "email"
        assert result["timestamp"] == "2026-01-01"
        assert result["text"] == "hello"

    def test_unknown_keys_ignored(self):
        base = {"text": "hello"}
        fm = {"random_key": "should_not_appear", "another": "nope"}
        result = ingest.enrich_payload(base, fm)
        assert "random_key" not in result
        assert "another" not in result

    def test_platform_normalized(self):
        base = {}
        fm = {"platform": "claude"}
        result = ingest.enrich_payload(base, fm)
        assert result["source_platform"] == "claude"
        assert "platform" not in result

    def test_service_normalized(self):
        base = {}
        fm = {"service": "gmail"}
        result = ingest.enrich_payload(base, fm)
        assert result["source_service"] == "gmail"
        assert "service" not in result

    def test_source_platform_direct(self):
        base = {}
        fm = {"source_platform": "gemini"}
        result = ingest.enrich_payload(base, fm)
        assert result["source_platform"] == "gemini"

    def test_modality_tags(self):
        base = {}
        fm = {"modality_tags": ["text", "temporal"]}
        result = ingest.enrich_payload(base, fm)
        assert result["modality_tags"] == ["text", "temporal"]

    def test_metadata_quality_gates(self):
        base = {}
        fm = {
            "service": "drive",
            "source_service": "gdrive",
            "content_tier": "metadata_only",
            "is_metadata_only": True,
            "retrieval_eligible": False,
        }
        result = ingest.enrich_payload(base, fm)
        assert result["source_service"] == "gdrive"
        assert result["content_tier"] == "metadata_only"
        assert result["is_metadata_only"] is True
        assert result["retrieval_eligible"] is False

    def test_people(self):
        base = {}
        fm = {"people": ["Alice", "Bob"]}
        result = ingest.enrich_payload(base, fm)
        assert result["people"] == ["Alice", "Bob"]

    def test_record_id(self):
        base = {}
        fm = {"record_id": "abc-123"}
        result = ingest.enrich_payload(base, fm)
        assert result["record_id"] == "abc-123"

    def test_categories(self):
        base = {}
        fm = {"categories": ["work", "personal"]}
        result = ingest.enrich_payload(base, fm)
        assert result["categories"] == ["work", "personal"]

    def test_location(self):
        base = {}
        fm = {"location": ", MN"}
        result = ingest.enrich_payload(base, fm)
        assert result["location"] == ", MN"

    def test_empty_frontmatter(self):
        base = {"text": "hello"}
        result = ingest.enrich_payload(base, {})
        assert result == {"text": "hello"}

    def test_does_not_mutate_original(self):
        """enrich_payload modifies base in place but also returns it."""
        base = {"text": "hello"}
        fm = {"content_type": "note"}
        result = ingest.enrich_payload(base, fm)
        # Returns the same dict (modified in place)
        assert result is base
        assert result["content_type"] == "note"


# ── collection config / schema ───────────────────────────────────────────────


class TestCollectionConfig:
    def test_default_collection_resolution_stays_documents(self):
        assert ingest.resolve_documents_collection({}) == "documents"

    def test_hapax_rag_collection_env_wins(self):
        assert (
            ingest.resolve_documents_collection({"HAPAX_RAG_COLLECTION": "documents_v2"})
            == "documents_v2"
        )

    def test_legacy_rag_documents_collection_env_supported(self):
        assert (
            ingest.resolve_documents_collection({"RAG_DOCUMENTS_COLLECTION": "documents_shadow"})
            == "documents_shadow"
        )

    def test_hapax_rag_collection_takes_precedence_over_legacy_env(self):
        assert (
            ingest.resolve_documents_collection(
                {
                    "HAPAX_RAG_COLLECTION": "documents_v2",
                    "RAG_DOCUMENTS_COLLECTION": "documents_shadow",
                }
            )
            == "documents_v2"
        )

    def test_dedup_key_preserves_default_documents_key(self, tmp_path):
        path = tmp_path / "doc.md"
        assert ingest._dedup_key(path, "documents") == str(path)

    def test_dedup_key_scopes_shadow_collections(self, tmp_path):
        path = tmp_path / "doc.md"
        assert ingest._dedup_key(path, "documents_v2") == f"documents_v2:{path}"

    def test_ensure_collection_creates_missing_collection_with_vector_size(self):
        class FakeClient:
            def __init__(self):
                self.created = None

            def get_collections(self):
                return SimpleNamespace(collections=[])

            def create_collection(self, collection_name, vectors_config, **kwargs):
                self.created = {
                    "collection_name": collection_name,
                    "vectors_config": vectors_config,
                    **kwargs,
                }

        client = FakeClient()
        created = ingest.ensure_collection("documents_v2", vector_size=1536, client=client)

        assert created is True
        assert client.created["collection_name"] == "documents_v2"
        assert client.created["vectors_config"].size == 1536
        assert client.created["vectors_config"].distance.name == "COSINE"

    def test_ensure_collection_leaves_existing_collection_alone(self):
        class FakeClient:
            def get_collections(self):
                return SimpleNamespace(collections=[SimpleNamespace(name="documents_v2")])

            def create_collection(self, collection_name, vectors_config, **kwargs):
                raise AssertionError("create_collection should not be called")

        assert (
            ingest.ensure_collection("documents_v2", vector_size=768, client=FakeClient()) is False
        )


class TestPlainTextSourceChunking:
    def test_text_and_python_sources_are_supported_for_shadow_ingest(self):
        assert ".md" in ingest.CFG.supported_extensions
        assert ".py" in ingest.CFG.supported_extensions
        assert {".html", ".md", ".py", ".txt"} == ingest.PLAIN_TEXT_SOURCE_EXTENSIONS

    def test_plain_text_chunks_preserve_line_content_without_docling(self):
        text = "def a():\n    return 1\n\n" + "x" * 20

        chunks = ingest.plain_text_chunks(text, max_chars=24)

        assert [chunk.text for chunk in chunks] == ["def a():\n    return 1", "x" * 20]

    def test_default_chunk_budget_moves_to_1024_tokens(self):
        assert ingest.Config().chunk_max_tokens == 1024


# ── point_id ─────────────────────────────────────────────────────────────────


class TestPointId:
    def test_deterministic(self, tmp_path):
        path = tmp_path / "test.md"
        path.touch()
        id1 = ingest.point_id(path, 0)
        id2 = ingest.point_id(path, 0)
        assert id1 == id2

    def test_different_chunks_different_ids(self, tmp_path):
        path = tmp_path / "test.md"
        path.touch()
        id0 = ingest.point_id(path, 0)
        id1 = ingest.point_id(path, 1)
        assert id0 != id1

    def test_different_paths_different_ids(self, tmp_path):
        p1 = tmp_path / "a.md"
        p2 = tmp_path / "b.md"
        p1.touch()
        p2.touch()
        assert ingest.point_id(p1, 0) != ingest.point_id(p2, 0)

    def test_returns_int(self, tmp_path):
        path = tmp_path / "test.md"
        path.touch()
        result = ingest.point_id(path, 0)
        assert isinstance(result, int)

    def test_matches_manual_computation(self, tmp_path):
        path = tmp_path / "test.md"
        path.touch()
        raw = f"{path.resolve()}:0"
        expected = int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16)
        assert ingest.point_id(path, 0) == expected


# ── retry queue ──────────────────────────────────────────────────────────────


class TestRetryQueue:
    def test_load_empty_queue(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "retry.jsonl"
        monkeypatch.setattr(ingest, "RETRY_QUEUE", fake_queue)
        entries = ingest.load_retry_queue()
        assert entries == []

    def test_queue_retry_roundtrip(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "retry.jsonl"
        monkeypatch.setattr(ingest, "RETRY_QUEUE", fake_queue)

        test_file = tmp_path / "doc.md"
        test_file.write_text("content")

        ingest.queue_retry(test_file, "connection error", attempts=0)
        entries = ingest.load_retry_queue()

        assert len(entries) == 1
        assert entries[0].path == str(test_file.resolve())
        assert entries[0].error == "connection error"
        assert entries[0].attempts == 1
        assert entries[0].next_retry > time.time() - 1

    def test_queue_retry_respects_max_retries(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "retry.jsonl"
        monkeypatch.setattr(ingest, "RETRY_QUEUE", fake_queue)

        test_file = tmp_path / "doc.md"
        test_file.write_text("content")

        # Attempt beyond MAX_RETRIES should not add to queue
        ingest.queue_retry(test_file, "fail", attempts=ingest.MAX_RETRIES)
        entries = ingest.load_retry_queue()
        assert len(entries) == 0

    def test_queue_retry_backoff_schedule(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "retry.jsonl"
        monkeypatch.setattr(ingest, "RETRY_QUEUE", fake_queue)

        test_file = tmp_path / "doc.md"
        test_file.write_text("content")

        before = time.time()
        ingest.queue_retry(test_file, "error", attempts=0)
        entries = ingest.load_retry_queue()

        assert len(entries) == 1
        # First retry delay is 30s
        assert entries[0].next_retry >= before + 30

    def test_load_corrupt_queue(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "retry.jsonl"
        monkeypatch.setattr(ingest, "RETRY_QUEUE", fake_queue)
        fake_queue.write_text("not json\n{bad\n")
        entries = ingest.load_retry_queue()
        assert entries == []

    def test_load_mixed_valid_invalid(self, tmp_path, monkeypatch):
        fake_queue = tmp_path / "retry.jsonl"
        monkeypatch.setattr(ingest, "RETRY_QUEUE", fake_queue)

        valid = json.dumps(
            {
                "path": "/tmp/test.md",
                "error": "err",
                "attempts": 1,
                "next_retry": time.time() + 100,
                "first_failed": time.time(),
            }
        )
        fake_queue.write_text(f"{valid}\nnot json\n")
        entries = ingest.load_retry_queue()
        assert len(entries) == 1
        assert entries[0].path == "/tmp/test.md"


# ── dedup tracker ────────────────────────────────────────────────────────────


class TestDedupTracker:
    def test_load_empty(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "processed.json"
        monkeypatch.setattr(ingest, "DEDUP_PATH", fake_path)
        tracker = ingest._load_dedup_tracker()
        assert tracker == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "subdir" / "processed.json"
        monkeypatch.setattr(ingest, "DEDUP_PATH", fake_path)

        tracker = {
            "/some/file.md": {"hash": "abc123", "mtime": 1234.0, "ingested_at": "2026-01-01"}
        }
        ingest._save_dedup_tracker(tracker)

        loaded = ingest._load_dedup_tracker()
        assert loaded == tracker

    def test_load_corrupt_json(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "processed.json"
        monkeypatch.setattr(ingest, "DEDUP_PATH", fake_path)
        fake_path.write_text("{bad json")
        tracker = ingest._load_dedup_tracker()
        assert tracker == {}

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        fake_path = tmp_path / "deep" / "nested" / "processed.json"
        monkeypatch.setattr(ingest, "DEDUP_PATH", fake_path)
        ingest._save_dedup_tracker({"key": "value"})
        assert fake_path.exists()


class TestShouldSkip:
    def test_new_file_not_skipped(self, tmp_path):
        f = tmp_path / "new.md"
        f.write_text("hello")
        tracker = {}
        assert ingest._should_skip(f, tracker) is False

    def test_unchanged_file_skipped(self, tmp_path):
        f = tmp_path / "existing.md"
        f.write_text("content")
        file_hash = ingest._file_hash(f)
        mtime = f.stat().st_mtime
        tracker = {str(f): {"hash": file_hash, "mtime": mtime}}
        assert ingest._should_skip(f, tracker) is True

    def test_modified_file_not_skipped(self, tmp_path):
        f = tmp_path / "changed.md"
        f.write_text("original")
        old_hash = ingest._file_hash(f)
        old_mtime = f.stat().st_mtime
        tracker = {str(f): {"hash": old_hash, "mtime": old_mtime}}

        # Modify the file
        time.sleep(0.05)  # Ensure mtime changes
        f.write_text("modified content")
        assert ingest._should_skip(f, tracker) is False

    def test_stale_mtime_triggers_hash_check(self, tmp_path):
        """If mtime differs, file is not skipped even if hash is same."""
        f = tmp_path / "test.md"
        f.write_text("content")
        file_hash = ingest._file_hash(f)
        tracker = {str(f): {"hash": file_hash, "mtime": 0.0}}  # Wrong mtime
        assert ingest._should_skip(f, tracker) is False

    def test_missing_hash_in_tracker(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content")
        tracker = {str(f): {"mtime": f.stat().st_mtime}}  # No hash
        assert ingest._should_skip(f, tracker) is False


class TestRecordIngested:
    def test_records_hash_and_mtime(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello world")
        tracker = {}
        ingest._record_ingested(f, tracker)

        key = str(f)
        assert key in tracker
        assert tracker[key]["hash"] == ingest._file_hash(f)
        assert tracker[key]["mtime"] == f.stat().st_mtime
        assert "ingested_at" in tracker[key]

    def test_overwrites_existing_entry(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("v1")
        tracker = {}
        ingest._record_ingested(f, tracker)
        old_hash = tracker[str(f)]["hash"]

        f.write_text("v2")
        ingest._record_ingested(f, tracker)
        assert tracker[str(f)]["hash"] != old_hash

    def test_shadow_collection_uses_collection_scoped_tracker_key(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello world")
        tracker = {}

        ingest._record_ingested(f, tracker, collection="documents_v2")

        assert f"documents_v2:{f}" in tracker
        assert ingest._should_skip(f, tracker, collection="documents_v2") is True
        assert ingest._should_skip(f, tracker, collection="documents") is False


# ── _file_hash ───────────────────────────────────────────────────────────────


class TestFileHash:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("deterministic content")
        h1 = ingest._file_hash(f)
        h2 = ingest._file_hash(f)
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("alpha")
        f2.write_text("beta")
        assert ingest._file_hash(f1) != ingest._file_hash(f2)

    def test_matches_hashlib_directly(self, tmp_path):
        f = tmp_path / "test.txt"
        content = b"test content for hashing"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert ingest._file_hash(f) == expected

    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("x")
        result = ingest._file_hash(f)
        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex digest length


# ── bulk_ingest with dedup ───────────────────────────────────────────────────


class TestBulkIngestDedup:
    def test_force_bypasses_dedup(self, tmp_path, monkeypatch):
        """With force=True, _load_dedup_tracker should not be called."""
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        (watch_dir / "a.md").write_text("hello")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
            ),
        )

        # Mock ingest_file to avoid heavy deps
        mock_ingest = MagicMock(return_value=(True, ""))
        monkeypatch.setattr(ingest, "ingest_file", mock_ingest)
        monkeypatch.setattr(ingest, "process_retries", lambda: None)

        # Mock dedup to track calls
        mock_load = MagicMock(return_value={})
        mock_save = MagicMock()
        monkeypatch.setattr(ingest, "_load_dedup_tracker", mock_load)
        monkeypatch.setattr(ingest, "_save_dedup_tracker", mock_save)

        ingest.bulk_ingest(force=True)

        mock_load.assert_not_called()
        mock_save.assert_not_called()
        mock_ingest.assert_called_once()

    def test_dedup_skips_unchanged(self, tmp_path, monkeypatch):
        """Unchanged files should be skipped."""
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        f = watch_dir / "a.md"
        f.write_text("hello")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
            ),
        )

        # Pre-populate tracker with current file state
        tracker = {str(f): {"hash": ingest._file_hash(f), "mtime": f.stat().st_mtime}}
        monkeypatch.setattr(ingest, "_load_dedup_tracker", lambda: tracker)
        mock_save = MagicMock()
        monkeypatch.setattr(ingest, "_save_dedup_tracker", mock_save)
        monkeypatch.setattr(ingest, "process_retries", lambda: None)

        mock_ingest = MagicMock(return_value=(True, ""))
        monkeypatch.setattr(ingest, "ingest_file", mock_ingest)

        total = ingest.bulk_ingest(force=False)

        mock_ingest.assert_not_called()
        assert total == 0  # Skipped files don't count as processed

    def test_dedup_records_after_success(self, tmp_path, monkeypatch):
        """Successfully ingested files should be recorded in the tracker."""
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        f = watch_dir / "new.md"
        f.write_text("brand new")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
            ),
        )

        saved_tracker = {}

        def fake_save(t):
            saved_tracker.update(t)

        monkeypatch.setattr(ingest, "_load_dedup_tracker", lambda: {})
        monkeypatch.setattr(ingest, "_save_dedup_tracker", fake_save)
        monkeypatch.setattr(ingest, "process_retries", lambda: None)
        monkeypatch.setattr(ingest, "ingest_file", MagicMock(return_value=(True, "")))

        ingest.bulk_ingest(force=False)

        assert str(f) in saved_tracker
        assert "hash" in saved_tracker[str(f)]
        assert "mtime" in saved_tracker[str(f)]

    def test_shadow_bulk_ingest_records_collection_scoped_dedup_key(self, tmp_path, monkeypatch):
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        f = watch_dir / "new.md"
        f.write_text("brand new")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
                collection="documents_v2",
            ),
        )

        saved_tracker = {}

        def fake_save(t):
            saved_tracker.update(t)

        monkeypatch.setattr(ingest, "_load_dedup_tracker", lambda: {})
        monkeypatch.setattr(ingest, "_save_dedup_tracker", fake_save)
        monkeypatch.setattr(ingest, "process_retries", lambda: None)
        monkeypatch.setattr(ingest, "ingest_file", MagicMock(return_value=(True, "")))

        ingest.bulk_ingest(force=False)

        assert str(f) not in saved_tracker
        assert f"documents_v2:{f}" in saved_tracker

    def test_dedup_does_not_record_on_failure(self, tmp_path, monkeypatch):
        """Failed ingestions should not be recorded in the tracker."""
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        f = watch_dir / "bad.md"
        f.write_text("will fail")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
            ),
        )

        saved_tracker = {}

        def fake_save(t):
            saved_tracker.update(t)

        monkeypatch.setattr(ingest, "_load_dedup_tracker", lambda: {})
        monkeypatch.setattr(ingest, "_save_dedup_tracker", fake_save)
        monkeypatch.setattr(ingest, "process_retries", lambda: None)
        monkeypatch.setattr(ingest, "queue_retry", lambda *a, **kw: None)
        monkeypatch.setattr(ingest, "ingest_file", MagicMock(return_value=(False, "error")))

        ingest.bulk_ingest(force=False)

        assert str(f) not in saved_tracker

    def test_dry_run_respects_max_files_without_ingesting(self, tmp_path, monkeypatch):
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        (watch_dir / "a.md").write_text("a")
        (watch_dir / "b.md").write_text("b")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
            ),
        )

        mock_ingest = MagicMock()
        monkeypatch.setattr(ingest, "ingest_file", mock_ingest)
        mock_save = MagicMock()
        monkeypatch.setattr(ingest, "_save_dedup_tracker", mock_save)
        mock_retries = MagicMock()
        monkeypatch.setattr(ingest, "process_retries", mock_retries)
        monkeypatch.setattr(ingest, "_load_dedup_tracker", lambda: {})

        total = ingest.bulk_ingest(max_files=1, dry_run=True)

        assert total == 1
        mock_ingest.assert_not_called()
        mock_save.assert_not_called()
        mock_retries.assert_not_called()

    def test_explicit_source_files_avoid_directory_scan(self, tmp_path, monkeypatch):
        watch_dir = tmp_path / "docs"
        watch_dir.mkdir()
        selected = tmp_path / "selected.md"
        skipped = tmp_path / "ignored.bin"
        selected.write_text("selected")
        skipped.write_text("ignored")

        monkeypatch.setattr(
            ingest,
            "CFG",
            ingest.Config(
                watch_dirs=[watch_dir],
                supported_extensions={".md"},
                collection="documents_v2",
            ),
        )

        saved_tracker = {}

        def fake_save(t):
            saved_tracker.update(t)

        mock_ingest = MagicMock(return_value=(True, ""))
        monkeypatch.setattr(ingest, "ingest_file", mock_ingest)
        monkeypatch.setattr(ingest, "_load_dedup_tracker", lambda: {})
        monkeypatch.setattr(ingest, "_save_dedup_tracker", fake_save)
        mock_retries = MagicMock()
        monkeypatch.setattr(ingest, "process_retries", mock_retries)

        total = ingest.bulk_ingest(source_files=[selected, skipped])

        assert total == 1
        mock_ingest.assert_called_once_with(selected)
        assert f"documents_v2:{selected}" in saved_tracker
        mock_retries.assert_not_called()


import pytest


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_load_dedup_tracker_non_dict_returns_empty(tmp_path, payload, kind, monkeypatch):
    """Pin _load_dedup_tracker against non-dict JSON. Tracker is
    consumed via tracker[key] and tracker[str(path)] = ... assignments
    — non-dict root crashed bulk_ingest."""
    dedup_path = tmp_path / "dedup.json"
    dedup_path.write_text(payload)
    monkeypatch.setattr(ingest, "DEDUP_PATH", dedup_path)
    assert ingest._load_dedup_tracker() == {}, f"non-dict root={kind} must yield empty"
