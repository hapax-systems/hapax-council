"""Tests for shared.takeout models, registry, and chunker."""
from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id
from shared.takeout.registry import SERVICE_REGISTRY, detect_services
from shared.takeout.chunker import (
    StructuredWriter,
    _yaml_list,
    record_to_markdown,
    record_to_jsonl,
    sanitize_filename,
    write_record,
)


# ── make_record_id ────────────────────────────────────────────────────────────

class TestMakeRecordId:
    def test_deterministic(self):
        id1 = make_record_id("google", "chrome", "abc")
        id2 = make_record_id("google", "chrome", "abc")
        assert id1 == id2

    def test_different_inputs(self):
        id1 = make_record_id("google", "chrome", "abc")
        id2 = make_record_id("google", "chrome", "def")
        assert id1 != id2

    def test_length(self):
        rid = make_record_id("google", "chrome", "abc")
        assert len(rid) == 16

    def test_hex_string(self):
        rid = make_record_id("google", "chrome", "abc")
        int(rid, 16)  # Should not raise


# ── ServiceConfig ─────────────────────────────────────────────────────────────

class TestServiceConfig:
    def test_defaults(self):
        cfg = ServiceConfig(parser="test", takeout_path="Test", tier=1)
        assert cfg.data_path == "unstructured"
        assert cfg.modality_defaults == []
        assert cfg.content_type == ""

    def test_full_config(self):
        cfg = ServiceConfig(
            parser="chrome",
            takeout_path="Chrome",
            tier=1,
            data_path="structured",
            modality_defaults=["text", "behavioral"],
            content_type="browser_history",
        )
        assert cfg.parser == "chrome"
        assert cfg.tier == 1
        assert cfg.data_path == "structured"


# ── NormalizedRecord ──────────────────────────────────────────────────────────

class TestNormalizedRecord:
    def test_minimal(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="chrome",
            title="Test",
            text="content",
            content_type="browser_history",
        )
        assert r.timestamp is None
        assert r.modality_tags == []
        assert r.people == []
        assert r.data_path == "unstructured"

    def test_full(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="gmail",
            title="Test Email",
            text="Hello world",
            content_type="email",
            timestamp=datetime(2025, 6, 15, 10, 30),
            modality_tags=["text", "social"],
            people=["alice@example.com"],
            location="San Francisco",
            categories=["inbox"],
            structured_fields={"subject": "Hello"},
            data_path="unstructured",
            source_path="Mail/All mail.mbox",
        )
        assert r.people == ["alice@example.com"]
        assert "social" in r.modality_tags


# ── SERVICE_REGISTRY ──────────────────────────────────────────────────────────

class TestServiceRegistry:
    def test_all_services_present(self):
        expected = {
            "chrome", "search", "keep", "youtube", "youtube_full", "calendar",
            "contacts", "tasks", "gmail", "drive", "chat", "maps", "photos",
            "purchases", "gemini",
        }
        assert set(SERVICE_REGISTRY.keys()) == expected

    def test_tiers(self):
        tier1 = [k for k, v in SERVICE_REGISTRY.items() if v.tier == 1]
        tier2 = [k for k, v in SERVICE_REGISTRY.items() if v.tier == 2]
        tier3 = [k for k, v in SERVICE_REGISTRY.items() if v.tier == 3]
        assert len(tier1) == 8
        assert len(tier2) == 3
        assert len(tier3) == 4

    def test_all_have_parser(self):
        for name, cfg in SERVICE_REGISTRY.items():
            assert cfg.parser, f"{name} missing parser"

    def test_all_have_modality_defaults(self):
        for name, cfg in SERVICE_REGISTRY.items():
            assert cfg.modality_defaults, f"{name} missing modality_defaults"

    def test_all_have_content_type(self):
        for name, cfg in SERVICE_REGISTRY.items():
            assert cfg.content_type, f"{name} missing content_type"


# ── detect_services ───────────────────────────────────────────────────────────

class TestDetectServices:
    def test_detect_chrome(self):
        names = ["Takeout/Chrome/BrowserHistory.json"]
        found = detect_services(names)
        assert "chrome" in found

    def test_detect_multiple(self):
        names = [
            "Takeout/Chrome/BrowserHistory.json",
            "Takeout/Keep/note1.json",
            "Takeout/Mail/All mail.mbox",
        ]
        found = detect_services(names)
        assert "chrome" in found
        assert "keep" in found
        assert "gmail" in found

    def test_detect_my_activity(self):
        names = [
            "Takeout/My Activity/Search/MyActivity.json",
            "Takeout/My Activity/YouTube/MyActivity.json",
        ]
        found = detect_services(names)
        assert "search" in found
        assert "youtube" in found

    def test_empty_zip(self):
        found = detect_services([])
        assert found == {}

    def test_no_takeout_prefix(self):
        """Some exports may not have the Takeout/ prefix."""
        names = ["Chrome/BrowserHistory.json"]
        found = detect_services(names)
        assert "chrome" in found

    def test_detect_youtube_full(self):
        """YouTube and YouTube Music folder maps to youtube_full service."""
        names = ["Takeout/YouTube and YouTube Music/history/watch-history.html"]
        found = detect_services(names)
        assert "youtube_full" in found
        assert found["youtube_full"].takeout_path == "YouTube and YouTube Music"

    def test_detect_alt_path_timeline(self):
        """Timeline folder maps to maps service via alt_paths."""
        names = ["Takeout/Timeline/Settings.json"]
        found = detect_services(names)
        assert "maps" in found
        assert found["maps"].takeout_path == "Timeline"

    def test_detect_primary_path_preferred(self):
        """Primary takeout_path is matched when present, even if alt exists."""
        names = ["Takeout/Location History/Records.json"]
        found = detect_services(names)
        assert "maps" in found
        assert found["maps"].takeout_path == "Location History"


# ── record_to_markdown ────────────────────────────────────────────────────────

class TestRecordToMarkdown:
    def test_minimal(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="chrome",
            title="Browser History",
            text="Visited example.com",
            content_type="browser_history",
        )
        md = record_to_markdown(r)
        assert "---" in md
        assert "platform: google" in md
        assert "service: chrome" in md
        assert "record_id: abc123" in md
        assert "# Browser History" in md
        assert "Visited example.com" in md

    def test_with_timestamp(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="keep",
            title="Note",
            text="Hello",
            content_type="note",
            timestamp=datetime(2025, 6, 15, 10, 30),
        )
        md = record_to_markdown(r)
        assert "timestamp: 2025-06-15T10:30:00" in md

    def test_with_modality_tags(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="gmail",
            title="Email",
            text="Hi",
            content_type="email",
            modality_tags=["text", "social"],
        )
        md = record_to_markdown(r)
        assert "modality_tags: [text, social]" in md

    def test_with_people(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="gmail",
            title="Email",
            text="Hi",
            content_type="email",
            people=["alice@example.com"],
        )
        md = record_to_markdown(r)
        assert "people: [alice@example.com]" in md

    def test_no_timestamp_field_when_none(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="chrome",
            title="Test",
            text="test",
            content_type="browser_history",
        )
        md = record_to_markdown(r)
        assert "timestamp:" not in md


# ── record_to_jsonl ───────────────────────────────────────────────────────────

class TestRecordToJsonl:
    def test_roundtrip(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="chrome",
            title="Test",
            text="content",
            content_type="browser_history",
            timestamp=datetime(2025, 6, 15, 10, 30),
            modality_tags=["text"],
            structured_fields={"url": "https://example.com"},
        )
        line = record_to_jsonl(r)
        data = json.loads(line)
        assert data["record_id"] == "abc123"
        assert data["platform"] == "google"
        assert data["timestamp"] == "2025-06-15T10:30:00"
        assert data["structured_fields"]["url"] == "https://example.com"

    def test_none_timestamp(self):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="chrome",
            title="Test",
            text="content",
            content_type="browser_history",
        )
        line = record_to_jsonl(r)
        data = json.loads(line)
        assert data["timestamp"] is None


# ── sanitize_filename ─────────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_basic(self):
        assert sanitize_filename("hello-world") == "hello-world"

    def test_special_chars(self):
        assert sanitize_filename("hello world!") == "hello-world"

    def test_truncation(self):
        long = "a" * 100
        result = sanitize_filename(long)
        assert len(result) <= 64

    def test_empty(self):
        assert sanitize_filename("") == "untitled"

    def test_collapse_hyphens(self):
        assert sanitize_filename("a---b") == "a-b"


# ── write_record ──────────────────────────────────────────────────────────────

class TestWriteRecord:
    def test_unstructured_write(self, tmp_path):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="keep",
            title="My Note",
            text="Hello world",
            content_type="note",
            data_path="unstructured",
        )
        path = write_record(r, output_dir=tmp_path)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".md"
        content = path.read_text()
        assert "platform: google" in content
        assert "# My Note" in content

    def test_structured_write(self, tmp_path):
        jsonl_path = tmp_path / "structured.jsonl"
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="chrome",
            title="Visit",
            text="example.com",
            content_type="browser_history",
            data_path="structured",
        )
        result = write_record(r, output_dir=tmp_path, structured_path=jsonl_path)
        assert result is None
        assert jsonl_path.exists()
        line = jsonl_path.read_text().strip()
        data = json.loads(line)
        assert data["record_id"] == "abc123"

    def test_dry_run(self, tmp_path):
        r = NormalizedRecord(
            record_id="abc123",
            platform="google",
            service="keep",
            title="Note",
            text="content",
            content_type="note",
            data_path="unstructured",
        )
        path = write_record(r, output_dir=tmp_path, dry_run=True)
        assert path is not None
        assert not path.exists()  # dry run — file not created


# ── _yaml_list tests ────────────────────────────────────────────────────────

class TestYamlList:
    def test_simple_items(self):
        assert _yaml_list(["alice", "bob"]) == "[alice, bob]"

    def test_item_with_comma(self):
        result = _yaml_list(["Smith, John", "Jane"])
        assert result == '["Smith, John", Jane]'

    def test_item_with_colon(self):
        result = _yaml_list(["key:value"])
        assert result == '["key:value"]'

    def test_item_with_brackets(self):
        result = _yaml_list(["[test]"])
        assert result == '["[test]"]'

    def test_item_with_ampersand(self):
        result = _yaml_list(["R&D"])
        assert result == '["R&D"]'

    def test_email_not_quoted(self):
        result = _yaml_list(["alice@example.com"])
        assert result == "[alice@example.com]"

    def test_empty_list(self):
        assert _yaml_list([]) == "[]"

    def test_no_special_chars(self):
        result = _yaml_list(["Alice Smith", "Bob Jones"])
        assert result == "[Alice Smith, Bob Jones]"

    def test_embedded_double_quotes_escaped(self):
        """F-5.3: Double quotes inside items are escaped."""
        result = _yaml_list(['He said "hello"'])
        assert result == r'["He said \"hello\""]'

    def test_backslash_with_special_chars_escaped(self):
        """Backslash is escaped when item also has YAML special chars."""
        result = _yaml_list([r'path\to\file: "test"'])
        assert r'\\' in result
        assert r'\"' in result


class TestRecordToMarkdownYamlEscaping:
    def test_people_with_comma_escaped(self):
        r = NormalizedRecord(
            record_id="test1",
            platform="google",
            service="gmail",
            title="Test",
            text="content",
            content_type="email",
            people=["Smith, John", "Jane Doe"],
        )
        md = record_to_markdown(r)
        assert '"Smith, John"' in md
        assert "Jane Doe" in md

    def test_categories_with_special_chars_escaped(self):
        r = NormalizedRecord(
            record_id="test2",
            platform="google",
            service="keep",
            title="Test",
            text="content",
            content_type="note",
            categories=["tech:ai", "normal"],
        )
        md = record_to_markdown(r)
        assert '"tech:ai"' in md
        assert "normal" in md


# ── Experimental flag tests ─────────────────────────────────────────────────

class TestExperimentalFlag:
    def test_service_config_default_not_experimental(self):
        cfg = ServiceConfig(parser="test", takeout_path="Test", tier=1)
        assert cfg.experimental is False

    def test_service_config_experimental_set(self):
        cfg = ServiceConfig(parser="test", takeout_path="Test", tier=1, experimental=True)
        assert cfg.experimental is True

    def test_gemini_is_experimental(self):
        assert SERVICE_REGISTRY["gemini"].experimental is True

    def test_chrome_is_not_experimental(self):
        assert SERVICE_REGISTRY["chrome"].experimental is False


# ── StructuredWriter tests ─────────────────────────────────────────────────

def _make_record(record_id: str = "abc123", service: str = "chrome") -> NormalizedRecord:
    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service=service,
        title="Test",
        text="content",
        content_type="browser_history",
        data_path="structured",
    )


class TestStructuredWriter:
    def test_write_creates_file(self, tmp_path):
        jsonl = tmp_path / "out.jsonl"
        with StructuredWriter(jsonl) as sw:
            assert sw.write(_make_record())
        assert jsonl.exists()
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["record_id"] == "abc123"

    def test_dedup_within_session(self, tmp_path):
        jsonl = tmp_path / "out.jsonl"
        with StructuredWriter(jsonl) as sw:
            assert sw.write(_make_record("r1"))
            assert sw.write(_make_record("r2"))
            assert not sw.write(_make_record("r1"))  # duplicate
        assert sw.written == 2
        assert sw.deduped == 1
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_dedup_across_sessions(self, tmp_path):
        jsonl = tmp_path / "out.jsonl"
        # First session
        with StructuredWriter(jsonl) as sw:
            sw.write(_make_record("r1"))
            sw.write(_make_record("r2"))
        # Second session — r1 should be deduped
        with StructuredWriter(jsonl) as sw:
            assert not sw.write(_make_record("r1"))
            assert sw.write(_make_record("r3"))
        assert sw.deduped == 1
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_dry_run_no_file(self, tmp_path):
        jsonl = tmp_path / "out.jsonl"
        with StructuredWriter(jsonl, dry_run=True) as sw:
            assert sw.write(_make_record())
        assert not jsonl.exists()
        assert sw.written == 1

    def test_empty_file(self, tmp_path):
        jsonl = tmp_path / "out.jsonl"
        jsonl.write_text("")
        with StructuredWriter(jsonl) as sw:
            assert sw.write(_make_record())
        assert sw.written == 1

    def test_write_record_uses_writer(self, tmp_path):
        """write_record should delegate to StructuredWriter when provided."""
        jsonl = tmp_path / "out.jsonl"
        r = _make_record()
        with StructuredWriter(jsonl) as sw:
            write_record(r, output_dir=tmp_path, structured_writer=sw)
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_write_record_dedupes_via_writer(self, tmp_path):
        """Duplicate records should be skipped when using StructuredWriter."""
        jsonl = tmp_path / "out.jsonl"
        r = _make_record()
        with StructuredWriter(jsonl) as sw:
            write_record(r, output_dir=tmp_path, structured_writer=sw)
            write_record(r, output_dir=tmp_path, structured_writer=sw)
        assert sw.deduped == 1
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 1
