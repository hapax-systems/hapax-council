from __future__ import annotations

from scripts import rag_corpus_baseline as baseline


def test_classify_payload_flags_metadata_only_records():
    payload = {
        "source": "/home/hapax/documents/rag-sources/gdrive/.meta/audio.md",
        "source_service": "gdrive",
        "is_metadata_only": True,
        "content_tier": "metadata_only",
        "retrieval_eligible": False,
        "text": "Drive inventory stub",
    }

    quality = baseline.classify_payload(payload)

    assert quality["metadata_only"] is True
    assert quality["content_tier"] == "metadata_only"
    assert quality["retrieval_eligible"] is False


def test_classify_payload_infers_low_and_full_content_tiers():
    low = baseline.classify_payload({"text": "short"})
    full = baseline.classify_payload({"text": "x" * 300})

    assert low["metadata_only"] is False
    assert low["content_tier"] == "low_content"
    assert full["metadata_only"] is False
    assert full["content_tier"] == "full_text"


def test_aggregate_payloads_reports_quality_distributions():
    report = baseline.aggregate_payloads(
        [
            {
                "source": "/docs/audio.md",
                "source_service": "gdrive",
                "extension": ".md",
                "is_metadata_only": True,
                "retrieval_eligible": False,
                "content_tier": "metadata_only",
                "text": "stub",
                "chunk_index": 0,
            },
            {
                "source": "/docs/note.md",
                "source_service": "obsidian",
                "extension": ".md",
                "text": "x" * 300,
                "chunk_index": 0,
                "chunk_count": 2,
            },
        ]
    )

    assert report["sample_count"] == 2
    assert report["metadata_only_count"] == 1
    assert report["metadata_only_rate"] == 0.5
    assert report["retrieval_ineligible_count"] == 1
    assert report["source_service_distribution"] == {"gdrive": 1, "obsidian": 1}
    assert report["content_tier_distribution"] == {"metadata_only": 1, "full_text": 1}
    assert report["chunk_index_coverage"] == 1.0
    assert report["chunk_count_coverage"] == 0.5


def test_render_markdown_marks_baseline_mandatory():
    markdown = baseline.render_markdown(
        {
            "generated_at": "2026-05-12T00:00:00Z",
            "collection": "documents",
            "available": False,
            "aggregate": baseline.aggregate_payloads([]),
        }
    )

    assert "Mandatory read-only baseline" in markdown
    assert "Metadata-only rate" in markdown
