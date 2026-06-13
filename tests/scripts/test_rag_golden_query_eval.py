from __future__ import annotations

import importlib.util
import json
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


def test_query_metrics_ndcg_deduplicates_repeated_label_hits() -> None:
    module = _load_module()
    labels = [{"source_contains": "target", "grade": 3}]
    hits = [
        {"source": "/tmp/target.md", "text": "", "is_metadata_hit": False},
        {"source": "/tmp/target.md", "text": "", "is_metadata_hit": False},
        {"source": "/tmp/target.md", "text": "", "is_metadata_hit": False},
    ]

    metrics = module.query_metrics(hits, labels, precision_k=5, recall_k=3, ndcg_k=3)

    assert metrics["ndcg_at_k"] == 1.0
    assert metrics["recall_at_k"] == 1.0


def test_aggregate_metrics_reports_no_evidence_and_utilization() -> None:
    module = _load_module()
    query_reports = [
        {
            "expected_sources": [{"source_contains": "a.md", "grade": 3}],
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
            "expected_sources": [{"source_contains": "missing.md", "grade": 3}],
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
    assert summary["source_label_utilization_numerator"] == 1
    assert summary["source_label_utilization_denominator"] == 2
    assert summary["source_label_utilization_rate"] == 0.5
    assert summary["corpus_utilization"]["unmatched_expected_source_labels"] == [
        {"source_contains": "missing.md"}
    ]


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
    assert report["retrieval_summary"]["golden_label_utilization_rate"] == 1.0
    assert report["answer_faithfulness"]["status"] == "not_evaluated"


def test_corpus_utilization_metrics_use_explicit_label_denominator() -> None:
    module = _load_module()
    suite = {
        "suite_id": "test-suite",
        "version": 1,
        "queries": [
            {
                "id": "q1",
                "topic": "rag",
                "query": "target a",
                "expected_sources": [
                    {"source_contains": "target-a", "grade": 3},
                    {"text_contains": "target text", "grade": 2},
                ],
            },
            {
                "id": "q2",
                "topic": "rag",
                "query": "target b",
                "expected_sources": [{"source_contains": "target-b", "grade": 3}],
            },
        ],
    }

    class FakeClient:
        def __init__(self) -> None:
            self.responses = [
                [
                    SimpleNamespace(
                        id=1,
                        score=0.9,
                        payload={
                            "source": "/tmp/target-a.md",
                            "text": "prefix target text suffix",
                        },
                    )
                ],
                [
                    SimpleNamespace(
                        id=2,
                        score=0.8,
                        payload={
                            "source": "/tmp/wrong.md",
                            "text": "wrong text",
                        },
                    )
                ],
            ]

        def query_points(self, **_kwargs):
            return SimpleNamespace(points=self.responses.pop(0))

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
    serialized = json.loads(json.dumps(report))

    assert "text" not in serialized["queries"][0]["hits"][0]
    utilization = module.aggregate_metrics(serialized["queries"])["corpus_utilization"]

    assert utilization["matched_label_numerator"] == 2
    assert utilization["expected_label_denominator"] == 3
    assert utilization["golden_label_utilization_rate"] == 0.6667
    assert utilization["matched_source_label_numerator"] == 1
    assert utilization["expected_source_label_denominator"] == 2


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


def test_run_embedding_health_preflight_delegates_to_guardrail(monkeypatch) -> None:
    module = _load_module()
    calls = []

    class FakeSpec:
        name = "_nomic_embedding_health_check"
        loader = None

    class FakeLoader:
        def exec_module(self, loaded_module):
            loaded_module.run_health_check = lambda **kwargs: calls.append(kwargs) or {"ok": True}

    FakeSpec.loader = FakeLoader()
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args: FakeSpec)
    monkeypatch.setattr(
        module.importlib.util, "module_from_spec", lambda _spec: type("M", (), {})()
    )

    report = module.run_embedding_health_preflight(
        ollama_url="http://ollama.test",
        embedding_model="nomic-embed-cpu",
        embedding_base_model="nomic-embed-text-v2-moe",
        expected_dimensions=768,
    )

    assert report == {"ok": True}
    assert calls == [
        {
            "ollama_url": "http://ollama.test",
            "model_alias": "nomic-embed-cpu",
            "base_model": "nomic-embed-text-v2-moe",
            "expected_dimensions": 768,
        }
    ]


def test_run_suite_with_faithfulness_suite_produces_evaluated_status() -> None:
    """When a faithfulness suite with required_claims is provided, the
    answer_faithfulness status flips from not_evaluated to evaluated and
    per-query answer_metrics are populated."""
    module = _load_module()
    suite = {
        "suite_id": "test-suite",
        "version": 1,
        "queries": [
            {
                "id": "q1",
                "topic": "rag",
                "query": "what is the RAG compounding failure",
                "expected_sources": [{"source_contains": "target", "grade": 3}],
            },
            {
                "id": "q2",
                "topic": "rag",
                "query": "unrelated query",
                "expected_sources": [{"source_contains": "other", "grade": 2}],
            },
        ],
    }
    faithfulness_suite = {
        "suite_id": "faith-test",
        "version": 1,
        "queries": [
            {
                "id": "q1",
                "query": "what is the RAG compounding failure",
                "required_claims": [
                    {
                        "id": "c1",
                        "answer_terms": ["metadata", "contamination"],
                        "support_terms": ["metadata", "contamination"],
                    }
                ],
            },
            # q2 deliberately has no required_claims → not scored.
        ],
    }

    class FakeClient:
        def query_points(self, **kwargs):
            return SimpleNamespace(
                points=[
                    SimpleNamespace(
                        id=1,
                        score=0.9,
                        payload={
                            "source": "/tmp/target.md",
                            "source_service": "obsidian",
                            "text": "RAG metadata contamination found in audit",
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
        faithfulness_suite=faithfulness_suite,
    )

    af = report["answer_faithfulness"]
    assert af["status"] == "evaluated"
    assert af["queries_scored"] == 1
    assert af["queries_total"] == 2
    assert af["mean_required_claim_recall"] is not None
    assert af["mean_supported_required_claim_rate"] is not None

    # q1 has answer_metrics, q2 does not.
    q1 = next(q for q in report["queries"] if q["id"] == "q1")
    q2 = next(q for q in report["queries"] if q["id"] == "q2")
    assert "answer_metrics" in q1
    assert "answer_metrics" not in q2
    assert q1["answer_metrics"]["required_claim_recall"] is not None
    assert q1["answer_metrics"]["supported_required_claim_rate"] is not None


def test_run_suite_without_faithfulness_suite_stays_not_evaluated() -> None:
    """Without a faithfulness suite, answer_faithfulness remains not_evaluated."""
    module = _load_module()
    suite = {
        "suite_id": "test-suite",
        "version": 1,
        "queries": [
            {
                "id": "q1",
                "topic": "rag",
                "query": "test",
                "expected_sources": [{"source_contains": "x", "grade": 1}],
            }
        ],
    }

    class FakeClient:
        def query_points(self, **_kwargs):
            return SimpleNamespace(points=[])

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

    assert report["answer_faithfulness"]["status"] == "not_evaluated"


def test_render_markdown_with_faithfulness_evaluated() -> None:
    """render_markdown handles evaluated faithfulness status correctly."""
    module = _load_module()
    report = {
        "generated_at": "2026-06-13T00:00:00Z",
        "suite_id": "test",
        "suite_version": 1,
        "collection": "docs",
        "limit": 10,
        "exclude_inventory": False,
        "retrieval_summary": {},
        "answer_faithfulness": {
            "status": "evaluated",
            "queries_scored": 3,
            "queries_total": 5,
            "mean_required_claim_recall": 0.8,
            "mean_supported_required_claim_rate": 0.6,
            "mean_answer_faithfulness": 0.75,
            "mean_contribution_score": 0.6,
            "total_forbidden_claim_hits": 0,
        },
        "queries": [],
    }
    md = module.render_markdown(report)
    assert "Status: `evaluated`" in md
    assert "Queries scored: `3/5`" in md
    assert "Mean required-claim recall: `0.8`" in md
    assert "Mean supported-claim rate: `0.6`" in md
