from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "rag_golden_query_eval.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_rag_golden_query_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_label_matching_and_metadata_detection() -> None:
    module = _load_module()
    hit = {
        "source": "/vault/audit/2026-05-12-full-corpus-hardening-audit.md",
        "source_service": "obsidian",
        "content_type": "note",
        "text": "RAG metadata contamination",
    }

    assert module.label_matches_hit({"source_contains": "full-corpus"}, hit)
    assert module.label_matches_hit({"text_contains": "metadata contamination"}, hit)
    assert not module.label_matches_hit({"source_service": "gdrive"}, hit)
    assert module.is_metadata_hit({"source": "/gdrive/.meta/file.md", "text": "x"})
    assert module.is_metadata_hit({"content_tier": "metadata_only"})
    assert module.is_metadata_hit({"text": "**Drive link:** https://drive.google.com/file/d/x"})


def test_query_metrics_precision_recall_mrr_ndcg_and_metadata_rate() -> None:
    module = _load_module()
    labels = [
        {"source_contains": "target-a", "grade": 3},
        {"source_contains": "target-b", "grade": 2},
    ]
    hits = [
        {"source": "/tmp/wrong.md", "text": "", "is_metadata_hit": True},
        {"source": "/tmp/target-b.md", "text": "", "is_metadata_hit": False},
        {"source": "/tmp/target-a.md", "text": "", "is_metadata_hit": False},
    ]

    metrics = module.query_metrics(hits, labels, precision_k=5, recall_k=3, ndcg_k=3)

    assert metrics["precision_at_5"] == 0.4
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 0.5
    assert metrics["ndcg_at_k"] is not None
    assert metrics["metadata_hit_rate"] == 0.3333
    assert metrics["no_relevant_evidence"] is False


def test_aggregate_metrics_reports_no_evidence_and_utilization() -> None:
    module = _load_module()
    query_reports = [
        {
            "retrieval_metrics": {
                "precision_at_5": 0.2,
                "recall_at_k": 1.0,
                "mrr": 1.0,
                "ndcg_at_k": 1.0,
                "metadata_hit_rate": 0.0,
                "no_hits": False,
                "no_relevant_evidence": False,
            },
            "hits": [{"source": "/tmp/a.md", "source_service": "obsidian"}],
        },
        {
            "retrieval_metrics": {
                "precision_at_5": 0.0,
                "recall_at_k": 0.0,
                "mrr": 0.0,
                "ndcg_at_k": 0.0,
                "metadata_hit_rate": 0.5,
                "no_hits": False,
                "no_relevant_evidence": True,
            },
            "hits": [{"source": "/tmp/b.md", "source_service": "gdrive"}],
        },
    ]

    summary = module.aggregate_metrics(query_reports)

    assert summary["mean_precision_at_5"] == 0.1
    assert summary["no_relevant_evidence_rate"] == 0.5
    assert summary["unique_source_count"] == 2
    assert summary["source_service_distribution"] == {"obsidian": 1, "gdrive": 1}


def test_run_suite_with_fake_client_separates_faithfulness() -> None:
    module = _load_module()
    suite = {
        "suite_id": "test-suite",
        "version": 1,
        "queries": [
            {
                "id": "q1",
                "topic": "rag",
                "query": "where is target",
                "expected_sources": [{"source_contains": "target", "grade": 3}],
            }
        ],
    }

    class FakeClient:
        def query_points(self, **_kwargs):
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id=1,
                        score=0.9,
                        payload={
                            "source": "/tmp/target.md",
                            "source_service": "obsidian",
                            "text": "target text",
                        },
                    )
                ]
            )

    report = module.run_suite(
        suite,
        collection="documents",
        limit=5,
        precision_k=5,
        qdrant_url="http://localhost:6333",
        embedding_model="nomic-embed-cpu",
        ollama_url="http://localhost:11434",
        client=FakeClient(),
        embedder=lambda _query: [0.1, 0.2],
    )

    assert report["retrieval_summary"]["mean_recall_at_k"] == 1.0
    assert report["answer_faithfulness"]["status"] == "not_evaluated"


def test_exclude_inventory_overfetches_and_drops_legacy_metadata_stubs() -> None:
    module = _load_module()
    calls = []

    class FakeClient:
        def query_points(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id=1,
                        score=0.99,
                        payload={
                            "source": "/home/hapax/documents/rag-sources/gdrive/.meta/kick.wav.md",
                            "source_service": "drive",
                            "text": "**Drive link:** https://drive.google.com/file/d/abc",
                        },
                    ),
                    SimpleNamespace(
                        id=2,
                        score=0.88,
                        payload={
                            "source": "/home/hapax/projects/hapax-council/docs/target.md",
                            "source_service": "git",
                            "text": "substantive evidence",
                        },
                    ),
                ]
            )

    hits = module.query_qdrant(
        FakeClient(),
        "documents",
        "target",
        limit=1,
        embedder=lambda _query: [0.1, 0.2],
        exclude_inventory=True,
    )

    assert [hit["source"] for hit in hits] == ["/home/hapax/projects/hapax-council/docs/target.md"]
    assert calls[0]["limit"] == 10
    query_filter = calls[0]["query_filter"]
    excluded_keys = {condition.key for condition in query_filter.must_not}
    assert {"retrieval_eligible", "is_metadata_only", "content_tier"} <= excluded_keys


def test_compare_reports_returns_metric_deltas() -> None:
    module = _load_module()
    baseline = {
        "generated_at": "before",
        "retrieval_summary": {
            "mean_precision_at_5": 0.1,
            "mean_metadata_hit_rate": 0.8,
        },
    }
    current = {
        "generated_at": "after",
        "retrieval_summary": {
            "mean_precision_at_5": 0.3,
            "mean_metadata_hit_rate": 0.2,
        },
    }

    comparison = module.compare_reports(current, baseline)

    assert comparison["metric_deltas"]["mean_precision_at_5"] == 0.2
    assert comparison["metric_deltas"]["mean_metadata_hit_rate"] == -0.6
