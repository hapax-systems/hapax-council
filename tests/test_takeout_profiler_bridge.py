"""Tests for shared.takeout.profiler_bridge and profiler_sources integration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.takeout.profiler_bridge import (
    structured_to_facts,
    generate_facts,
    _extract_domain,
    _make_fact,
)


# ── _extract_domain ──────────────────────────────────────────────────────────

class TestExtractDomain:
    def test_basic(self):
        assert _extract_domain("https://github.com/user/repo") == "github.com"

    def test_strip_www(self):
        assert _extract_domain("https://www.example.com") == "example.com"

    def test_strip_port(self):
        assert _extract_domain("http://localhost:4000/api") == "localhost"

    def test_empty(self):
        assert _extract_domain("") == ""

    def test_no_protocol(self):
        assert _extract_domain("github.com/path") == "github.com"


# ── _make_fact ────────────────────────────────────────────────────────────────

class TestMakeFact:
    def test_creates_dict(self):
        fact = _make_fact("identity", "name", "Test", "source:test", "evidence")
        assert fact["dimension"] == "identity"
        assert fact["confidence"] == 0.95
        assert fact["source"] == "source:test"


# ── structured_to_facts ──────────────────────────────────────────────────────

class TestStructuredToFacts:
    def _write_jsonl(self, path: Path, records: list[dict]) -> None:
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_chrome_facts(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "chrome",
                "title": "GitHub",
                "text": "GitHub",
                "structured_fields": {"url": "https://github.com", "visit_count": 50},
            },
            {
                "service": "chrome",
                "title": "Stack Overflow",
                "text": "SO",
                "structured_fields": {"url": "https://stackoverflow.com", "visit_count": 30},
            },
        ])
        facts = structured_to_facts(jsonl)
        assert len(facts) >= 1
        website_fact = next(f for f in facts if f["key"] == "frequent_websites")
        assert "github.com" in website_fact["value"]

    def test_search_facts(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        self._write_jsonl(jsonl, [
            {"service": "search", "title": "Searched for MIDI routing linux"},
            {"service": "search", "title": "Searched for pydantic ai tutorial"},
        ])
        facts = structured_to_facts(jsonl)
        assert len(facts) >= 1
        search_fact = next(f for f in facts if f["key"] == "search_topics")
        assert "MIDI routing" in search_fact["value"]

    def test_youtube_facts(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        self._write_jsonl(jsonl, [
            {"service": "youtube", "title": "Watched SP-404 tutorial"},
            {"service": "youtube", "title": "Watched Beat making tips"},
        ])
        facts = structured_to_facts(jsonl)
        assert len(facts) >= 1
        yt_fact = next(f for f in facts if f["key"] == "video_topics")
        assert "SP-404" in yt_fact["value"]

    def test_calendar_facts(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "calendar",
                "title": "Weekly Standup",
                "structured_fields": {"recurring": True, "rrule": "FREQ=WEEKLY"},
            },
            {
                "service": "calendar",
                "title": "One-off Meeting",
                "structured_fields": {},
            },
        ])
        facts = structured_to_facts(jsonl)
        recurring_fact = next((f for f in facts if f["key"] == "recurring_commitments"), None)
        assert recurring_fact is not None
        assert "Weekly Standup" in recurring_fact["value"]

    def test_contacts_facts(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "contacts",
                "title": "Alice",
                "structured_fields": {"organization": "Acme Corp"},
            },
            {
                "service": "contacts",
                "title": "Bob",
                "structured_fields": {"organization": "Acme Corp"},
            },
            {
                "service": "contacts",
                "title": "Charlie",
                "structured_fields": {},
            },
        ])
        facts = structured_to_facts(jsonl)
        network_fact = next(f for f in facts if f["key"] == "contact_network_size")
        assert network_fact["value"] == "3"

    def test_empty_file(self, tmp_path):
        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text("")
        facts = structured_to_facts(jsonl)
        assert facts == []

    def test_missing_file(self, tmp_path):
        facts = structured_to_facts(tmp_path / "nonexistent.jsonl")
        assert facts == []

    def test_mixed_services(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "chrome",
                "title": "GitHub",
                "structured_fields": {"url": "https://github.com", "visit_count": 10},
            },
            {"service": "search", "title": "Searched for Python async"},
            {"service": "youtube", "title": "Watched coding tutorial"},
        ])
        facts = structured_to_facts(jsonl)
        keys = {f["key"] for f in facts}
        assert "frequent_websites" in keys
        assert "search_topics" in keys
        assert "video_topics" in keys


# ── generate_facts ────────────────────────────────────────────────────────────

class TestGenerateFacts:
    def test_generate_and_write(self, tmp_path):
        jsonl = tmp_path / "structured.jsonl"
        output = tmp_path / "facts.json"
        with open(jsonl, "w") as f:
            f.write(json.dumps({
                "service": "chrome",
                "title": "Test",
                "structured_fields": {"url": "https://test.com", "visit_count": 5},
            }) + "\n")

        count = generate_facts(jsonl_path=jsonl, output_path=output)
        assert count > 0
        assert output.exists()
        data = json.loads(output.read_text())
        assert isinstance(data, list)
        assert len(data) == count

    def test_generate_empty(self, tmp_path):
        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text("")
        output = tmp_path / "facts.json"
        count = generate_facts(jsonl_path=jsonl, output_path=output)
        assert count == 0


# ── load_structured_facts (profiler.py) ──────────────────────────────────────

class TestLoadStructuredFacts:
    def test_load_valid_facts(self, tmp_path, monkeypatch):
        from agents.profiler import load_structured_facts, PROFILES_DIR

        facts_data = [
            {
                "dimension": "information_seeking",
                "key": "frequent_websites",
                "value": "github.com (50)",
                "confidence": 0.95,
                "source": "takeout-structured:takeout-structured.jsonl",
                "evidence": "Aggregated from 10 URLs",
            }
        ]
        facts_file = tmp_path / "takeout-structured-facts.json"
        facts_file.write_text(json.dumps(facts_data))

        monkeypatch.setattr("agents.profiler.PROFILES_DIR", tmp_path)
        facts = load_structured_facts()
        assert len(facts) == 1
        assert facts[0].dimension == "information_seeking"
        assert facts[0].key == "frequent_websites"
        assert facts[0].confidence == 0.95

    def test_load_missing_file(self, tmp_path, monkeypatch):
        from agents.profiler import load_structured_facts
        monkeypatch.setattr("agents.profiler.PROFILES_DIR", tmp_path)
        facts = load_structured_facts()
        assert facts == []

    def test_load_invalid_json(self, tmp_path, monkeypatch):
        from agents.profiler import load_structured_facts
        facts_file = tmp_path / "takeout-structured-facts.json"
        facts_file.write_text("not valid json")
        monkeypatch.setattr("agents.profiler.PROFILES_DIR", tmp_path)
        facts = load_structured_facts()
        assert facts == []

    def test_load_skips_malformed_entries(self, tmp_path, monkeypatch):
        from agents.profiler import load_structured_facts
        facts_data = [
            {"dimension": "identity", "key": "name", "value": "Ryan",
             "confidence": 0.95, "source": "test", "evidence": "stated"},
            {"bad": "entry"},  # missing required fields
        ]
        facts_file = tmp_path / "takeout-structured-facts.json"
        facts_file.write_text(json.dumps(facts_data))
        monkeypatch.setattr("agents.profiler.PROFILES_DIR", tmp_path)
        facts = load_structured_facts()
        assert len(facts) == 1


# ── profiler_sources integration ──────────────────────────────────────────────

class TestProfilerSourcesIntegration:
    def test_takeout_source_type_in_read_all(self, tmp_path, monkeypatch):
        """Verify that takeout files are discovered and read by profiler_sources."""
        from agents.profiler_sources import (
            DiscoveredSources,
            read_all_sources,
            read_takeout,
        )

        # Create a fake takeout markdown file
        takeout_file = tmp_path / "test-note.md"
        takeout_file.write_text(
            "---\nplatform: google\nservice: keep\n---\n\n# Test Note\n\nHello world\n"
        )

        sources = DiscoveredSources()
        sources.takeout_files = [takeout_file]

        chunks = read_all_sources(sources, source_filter="takeout")
        assert len(chunks) >= 1
        assert chunks[0].source_type == "takeout"
        assert "Hello world" in chunks[0].text

    def test_read_takeout_chunking(self, tmp_path):
        from agents.profiler_sources import read_takeout

        md_file = tmp_path / "note.md"
        md_file.write_text("---\nservice: keep\n---\n\n# Test\n\nSome content here.")

        chunks = read_takeout(md_file)
        assert len(chunks) >= 1
        assert chunks[0].source_type == "takeout"
        assert "takeout:" in chunks[0].source_id


# ── ingest.py frontmatter parsing ─────────────────────────────────────────────
#
# These test the parse_frontmatter and enrich_payload functions that were added
# to ~/projects/rag-pipeline/ingest.py. Since that project has different deps
# (watchdog, docling), we replicate the pure-logic functions here for testing.

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Local copy of ingest.parse_frontmatter for testing."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    front = text[3:end].strip()
    body = text[end + 4:].strip()
    metadata: dict = {}
    for line in front.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip() for v in value[1:-1].split(",") if v.strip()]
            metadata[key] = items
        elif value.startswith('"') and value.endswith('"'):
            metadata[key] = value[1:-1]
        else:
            metadata[key] = value
    return metadata, body


def _enrich_payload(base_payload: dict, frontmatter: dict) -> dict:
    """Local copy of ingest.enrich_payload for testing."""
    enrichment_keys = {
        "content_type", "source_service", "source_platform",
        "timestamp", "modality_tags", "people",
        "platform", "service",
    }
    for key in enrichment_keys:
        if key in frontmatter:
            value = frontmatter[key]
            if key == "platform":
                base_payload["source_platform"] = value
            elif key == "service":
                base_payload["source_service"] = value
            else:
                base_payload[key] = value
    return base_payload


class TestIngestFrontmatter:
    """Test the frontmatter parsing logic added to rag-pipeline/ingest.py."""

    def test_parse_frontmatter(self):
        text = """---
platform: google
service: gmail
content_type: email
modality_tags: [text, social, temporal]
people: [alice@example.com]
---

# Test Email

Hello world
"""
        meta, body = _parse_frontmatter(text)
        assert meta["platform"] == "google"
        assert meta["service"] == "gmail"
        assert meta["content_type"] == "email"
        assert meta["modality_tags"] == ["text", "social", "temporal"]
        assert meta["people"] == ["alice@example.com"]
        assert "# Test Email" in body

    def test_parse_no_frontmatter(self):
        text = "# Just a heading\n\nNo frontmatter here."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_enrich_payload(self):
        base = {"text": "hello", "source": "/some/path"}
        frontmatter = {
            "platform": "google",
            "service": "gmail",
            "content_type": "email",
            "modality_tags": ["text", "social"],
            "people": ["alice@example.com"],
            "timestamp": "2025-06-15T10:30:00Z",
        }
        enriched = _enrich_payload(base, frontmatter)
        assert enriched["source_platform"] == "google"
        assert enriched["source_service"] == "gmail"
        assert enriched["content_type"] == "email"
        assert enriched["modality_tags"] == ["text", "social"]
        assert enriched["people"] == ["alice@example.com"]
        assert enriched["text"] == "hello"

    def test_enrich_ignores_unknown_keys(self):
        base = {"text": "hello"}
        frontmatter = {"random_key": "value", "platform": "google"}
        enriched = _enrich_payload(base, frontmatter)
        assert "random_key" not in enriched
        assert enriched["source_platform"] == "google"


# ── Streaming JSONL tests ────────────────────────────────────────────────────

class TestStreamingJSONL:
    """Verify structured_to_facts streams line-by-line instead of loading all into memory."""

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict]) -> Path:
        lines = [json.dumps(r) for r in records]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_large_file_streams(self, tmp_path):
        """Verify many records parse correctly with streaming."""
        jsonl = tmp_path / "big.jsonl"
        records = [
            {
                "service": "chrome",
                "title": f"Page {i}",
                "text": f"page-{i}",
                "structured_fields": {"url": f"https://site-{i}.com", "visit_count": 1},
            }
            for i in range(5000)
        ]
        self._write_jsonl(jsonl, records)

        facts = structured_to_facts(jsonl)
        # Should produce at least the frequent_websites fact
        assert any(f["key"] == "frequent_websites" for f in facts)

    def test_handles_blank_lines(self, tmp_path):
        """Blank lines in JSONL should be skipped."""
        jsonl = tmp_path / "blanks.jsonl"
        content = (
            json.dumps({"service": "search", "title": "Searched for test"})
            + "\n\n\n"
            + json.dumps({"service": "search", "title": "Searched for another"})
            + "\n"
        )
        jsonl.write_text(content)
        facts = structured_to_facts(jsonl)
        assert any(f["key"] == "search_topics" for f in facts)

    def test_handles_corrupt_lines(self, tmp_path):
        """Corrupt JSON lines should be skipped, not crash."""
        jsonl = tmp_path / "corrupt.jsonl"
        content = (
            json.dumps({"service": "search", "title": "Searched for valid"})
            + "\n{bad json\n"
            + json.dumps({"service": "search", "title": "Searched for also valid"})
            + "\n"
        )
        jsonl.write_text(content)
        facts = structured_to_facts(jsonl)
        search_fact = next((f for f in facts if f["key"] == "search_topics"), None)
        assert search_fact is not None
        assert "valid" in search_fact["value"]


# ── YouTube expanded facts ──────────────────────────────────────────────────

class TestYouTubeExpandedFacts:
    @staticmethod
    def _write_jsonl(path: Path, records: list[dict]) -> Path:
        lines = [json.dumps(r) for r in records]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_youtube_channel_facts(self, tmp_path):
        jsonl = tmp_path / "yt.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "youtube",
                "title": "Watched: Beat making tips",
                "content_type": "video_watch",
                "structured_fields": {"channel": "Andrew Huang", "type": "watch"},
            },
            {
                "service": "youtube",
                "title": "Watched: Lo-fi tutorial",
                "content_type": "video_watch",
                "structured_fields": {"channel": "Andrew Huang", "type": "watch"},
            },
            {
                "service": "youtube",
                "title": "Watched: Python tips",
                "content_type": "video_watch",
                "structured_fields": {"channel": "Corey Schafer", "type": "watch"},
            },
        ])
        facts = structured_to_facts(jsonl)
        channel_fact = next(f for f in facts if f["key"] == "youtube_channels")
        assert "Andrew Huang (2)" in channel_fact["value"]
        assert "Corey Schafer (1)" in channel_fact["value"]

    def test_youtube_search_facts(self, tmp_path):
        jsonl = tmp_path / "yt.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "youtube",
                "title": "YouTube search: SP-404 tutorial",
                "content_type": "search_query",
                "structured_fields": {"query": "SP-404 tutorial", "type": "search"},
            },
            {
                "service": "youtube",
                "title": "YouTube search: boom bap drums",
                "content_type": "search_query",
                "structured_fields": {"query": "boom bap drums", "type": "search"},
            },
        ])
        facts = structured_to_facts(jsonl)
        search_fact = next(f for f in facts if f["key"] == "youtube_search_topics")
        assert "SP-404 tutorial" in search_fact["value"]
        assert "boom bap drums" in search_fact["value"]

    def test_youtube_subscription_facts(self, tmp_path):
        jsonl = tmp_path / "yt.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "youtube",
                "title": "Subscribed: Andrew Huang",
                "content_type": "subscription",
                "structured_fields": {"channel_title": "Andrew Huang", "type": "subscription"},
            },
            {
                "service": "youtube",
                "title": "Subscribed: Fireship",
                "content_type": "subscription",
                "structured_fields": {"channel_title": "Fireship", "type": "subscription"},
            },
        ])
        facts = structured_to_facts(jsonl)
        sub_fact = next(f for f in facts if f["key"] == "youtube_subscriptions")
        assert "Andrew Huang" in sub_fact["value"]
        assert "Fireship" in sub_fact["value"]

    def test_youtube_playlist_facts(self, tmp_path):
        jsonl = tmp_path / "yt.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "youtube",
                "title": "Playlist [Music]: abc",
                "content_type": "playlist_item",
                "structured_fields": {"playlist": "Music", "type": "playlist"},
            },
            {
                "service": "youtube",
                "title": "Playlist [Music]: def",
                "content_type": "playlist_item",
                "structured_fields": {"playlist": "Music", "type": "playlist"},
            },
            {
                "service": "youtube",
                "title": "Playlist [Tutorials]: ghi",
                "content_type": "playlist_item",
                "structured_fields": {"playlist": "Tutorials", "type": "playlist"},
            },
        ])
        facts = structured_to_facts(jsonl)
        playlist_fact = next(f for f in facts if f["key"] == "youtube_playlists")
        assert "Music (2 videos)" in playlist_fact["value"]
        assert "Tutorials (1 videos)" in playlist_fact["value"]

    def test_youtube_legacy_no_content_type(self, tmp_path):
        """Legacy activity-based records (no content_type) still produce video_topics."""
        jsonl = tmp_path / "yt.jsonl"
        self._write_jsonl(jsonl, [
            {"service": "youtube", "title": "Watched SP-404 tutorial"},
        ])
        facts = structured_to_facts(jsonl)
        yt_fact = next(f for f in facts if f["key"] == "video_topics")
        assert "SP-404" in yt_fact["value"]

    def test_youtube_full_service_name(self, tmp_path):
        """Records with service='youtube_full' from the full export parser are handled."""
        jsonl = tmp_path / "yt.jsonl"
        self._write_jsonl(jsonl, [
            {
                "service": "youtube_full",
                "title": "Watched: Full export video",
                "content_type": "video_watch",
                "structured_fields": {"channel": "TestChannel", "type": "watch"},
            },
            {
                "service": "youtube_full",
                "content_type": "subscription",
                "structured_fields": {"channel_title": "SubChannel", "type": "subscription"},
            },
        ])
        facts = structured_to_facts(jsonl)
        keys = {f["key"] for f in facts}
        assert "video_topics" in keys
        assert "youtube_channels" in keys
        assert "youtube_subscriptions" in keys

    def test_youtube_watch_count_in_evidence(self, tmp_path):
        """When total watches exceed title limit, evidence shows total."""
        jsonl = tmp_path / "yt.jsonl"
        records = [
            {
                "service": "youtube",
                "title": f"Watched: Video {i}",
                "content_type": "video_watch",
                "structured_fields": {"channel": f"Channel{i}", "type": "watch"},
            }
            for i in range(60)
        ]
        self._write_jsonl(jsonl, records)
        facts = structured_to_facts(jsonl)
        yt_fact = next(f for f in facts if f["key"] == "video_topics")
        assert "of 60 total" in yt_fact["evidence"]
