"""Tests for ``scripts/rag_baseline_report.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "rag_baseline_report.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("_rag_baseline_report", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_payload_detects_gdrive_metadata_stub() -> None:
    report = _load_script_module()
    cls = report.classify_payload(
        {
            "text": "# Studio.mov\n\n**Drive link:** https://drive.example/file",
            "source": "/home/hapax/documents/rag-sources/gdrive/.meta/Studio.mov_abc.md",
            "source_service": "gdrive",
            "content_type": "video",
            "gdrive_id": "abc",
            "mime_type": "video/quicktime",
            "file_size": 100,
        }
    )

    assert cls.likely_metadata_stub is True
    assert cls.is_metadata_only is False
    assert "gdrive_meta_path" in cls.metadata_indicators
    assert "drive_link_stub_body" in cls.metadata_indicators


def test_classify_payload_honors_explicit_quality_fields() -> None:
    report = _load_script_module()
    cls = report.classify_payload(
        {
            "text": "inventory",
            "source": "/x/y.md",
            "is_metadata_only": True,
            "content_tier": "metadata_only",
            "retrieval_eligible": False,
        }
    )

    assert cls.is_metadata_only is True
    assert cls.likely_metadata_stub is True
    assert "is_metadata_only=true" in cls.metadata_indicators
    assert "content_tier=metadata_only" in cls.metadata_indicators
    assert "retrieval_eligible=false" in cls.metadata_indicators


def test_aggregate_classifications_reports_contamination_rate() -> None:
    report = _load_script_module()
    items = [
        report.classify_payload({"text": "a" * 100, "source_service": "obsidian"}),
        report.classify_payload(
            {
                "text": "stub",
                "source_service": "gdrive",
                "is_metadata_only": True,
                "content_tier": "metadata_only",
                "retrieval_eligible": False,
                "chunk_index": 0,
                "chunk_count": 1,
            }
        ),
    ]

    data = report.stats_to_dict(report.aggregate_classifications(items))

    assert data["sampled_points"] == 2
    assert data["source_service_distribution"] == {"obsidian": 1, "gdrive": 1}
    assert data["metadata_only_count"] == 1
    assert data["likely_metadata_stub_count"] == 1
    assert data["likely_metadata_contamination_rate"] == 0.5
    assert data["estimated_token_length"]["max"] == 25


def test_vector_size_handles_single_and_named_vectors() -> None:
    report = _load_script_module()
    single = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=768)))
    )
    named = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={
                    "dense": SimpleNamespace(size=768),
                    "sparse": {"size": 256},
                }
            )
        )
    )

    assert report._vector_size(single) == 768
    assert report._vector_size(named) == {"dense": 768, "sparse": 256}


def test_render_markdown_documents_reindexing_gate() -> None:
    report = _load_script_module()
    data = {
        "generated_at": "2026-05-12T00:00:00+00:00",
        "collection": "documents",
        "qdrant_available": False,
        "collection_point_count": None,
        "vector_size": None,
        "sample_size_requested": 10,
        "payload_schema_keys": [],
        "sample": report.stats_to_dict(report.CorpusStats()),
        "errors": ["qdrant_unavailable: refused"],
    }

    markdown = report.render_markdown(data)

    assert "Run this before reindexing" in markdown
    assert "qdrant_unavailable" in markdown


def test_collect_payload_sample_uses_scroll_read_only() -> None:
    report = _load_script_module()
    first = SimpleNamespace(payload={"text": "one"})
    second = SimpleNamespace(payload={"text": "two"})

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def scroll(self, **kwargs):
            self.calls += 1
            assert kwargs["with_vectors"] is False
            assert kwargs["with_payload"] is True
            if self.calls == 1:
                return [first], "offset-2"
            return [second], None

    assert report.collect_payload_sample(FakeClient(), "documents", 2) == [
        {"text": "one"},
        {"text": "two"},
    ]


def test_query_smoke_uses_supplied_collection(monkeypatch) -> None:
    report = _load_script_module()
    monkeypatch.setattr(report, "_embed_query", lambda *a, **kw: [0.1, 0.2])

    class FakeClient:
        def __init__(self) -> None:
            self.collection = None

        def query_points(self, collection, **kwargs):
            self.collection = collection
            return SimpleNamespace(points=[])

    client = FakeClient()
    smoke = report.run_query_smoke(
        client,
        "documents_v2",
        ["constitutional memory"],
        limit=3,
        model="nomic-embed-cpu",
        ollama_url="http://ollama",
    )

    assert client.collection == "documents_v2"
    assert smoke[0]["query"] == "constitutional memory"
