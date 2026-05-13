from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "rag_answer_faithfulness_eval.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_rag_answer_faithfulness_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _suite() -> dict:
    return {
        "suite_id": "test-answer-suite",
        "version": 1,
        "queries": [
            {
                "id": "q1",
                "topic": "rag",
                "query": "what happened",
                "reference_answer": "RAG repair requires faithfulness evidence.",
                "expected_sources": [{"source_contains": "target.md", "grade": 3}],
                "required_claims": [
                    {
                        "id": "faithfulness",
                        "terms": ["RAG", "faithfulness"],
                        "source_contains": ["target.md"],
                    }
                ],
                "forbidden_claims": [{"id": "proof", "terms": ["existence proof"]}],
                "expected_refusal_when_no_evidence": True,
                "insufficient_evidence_terms": ["insufficient evidence"],
            }
        ],
    }


def test_score_answer_separates_correctness_from_context_support() -> None:
    module = _load_module()
    item = _suite()["queries"][0]

    metrics = module.score_answer(
        item,
        "RAG faithfulness is solved.",
        [{"source": "/tmp/wrong.md", "text": "unrelated context"}],
    )

    assert metrics["required_claim_recall"] == 1.0
    assert metrics["supported_required_claim_rate"] == 0.0
    assert metrics["answer_faithfulness"] == 0.0


def test_score_answer_tracks_expected_refusal_without_crediting_claim_recall() -> None:
    module = _load_module()
    item = dict(_suite()["queries"][0])
    item["expected_refusal_when_no_evidence"] = True

    metrics = module.score_answer(
        item,
        "Insufficient evidence in retrieved contexts to answer this question.",
        [],
        no_relevant_evidence=True,
    )

    assert metrics["insufficient_evidence_signaled"] is True
    assert metrics["required_claim_recall"] == 0.0
    assert metrics["supported_required_claim_rate"] == 0.0
    assert metrics["answer_faithfulness"] is None


def test_run_suite_reports_no_context_and_collection_ablation() -> None:
    module = _load_module()
    calls = []

    def retriever(collection: str, query: str, limit: int, exclude_inventory: bool):
        calls.append((collection, query, limit, exclude_inventory))
        return [
            {
                "source": "/tmp/target.md",
                "source_service": "fixture",
                "text": "RAG repair requires faithfulness evidence.",
                "text_excerpt": "RAG repair requires faithfulness evidence.",
                "is_metadata_hit": False,
            }
        ]

    def generator(item, contexts):
        if not contexts:
            return "Insufficient evidence."
        return "RAG faithfulness is supported by retrieved evidence."

    report = module.run_suite(
        _suite(),
        variants=[
            module.Variant(name="no_context", no_context=True),
            module.Variant(name="documents_v2", collection="documents_v2"),
        ],
        limit=5,
        retriever=retriever,
        generator=generator,
        answer_mode="fixture",
    )

    assert calls == [("documents_v2", "what happened", 5, True)]
    assert report["variants"][0]["answer_summary"]["refusal_hit_rate"] == 1.0
    assert report["variants"][0]["answer_summary"]["mean_required_claim_recall"] == 0.0
    assert report["variants"][1]["answer_summary"]["mean_supported_required_claim_rate"] == 1.0
    delta = report["downstream_contribution"][0]["answer_metric_deltas"]
    assert delta["mean_supported_required_claim_rate"] == 1.0
    assert report["claim_ceiling"]["status"] == "not_upgraded"
    assert report["interchange_records"]["documents_v2"]["ragas"][0] == {
        "user_input": "what happened",
        "retrieved_contexts": ["RAG repair requires faithfulness evidence."],
        "response": "RAG faithfulness is supported by retrieved evidence.",
        "reference": "RAG repair requires faithfulness evidence.",
    }


def test_load_suite_validates_reference_answers(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"queries": [{"id": "q", "query": "x"}]}), encoding="utf-8")

    try:
        module.load_suite(path)
    except ValueError as exc:
        assert "missing reference_answer" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_ollama_chat_text_supports_object_and_mapping_response_shapes() -> None:
    module = _load_module()

    assert (
        module._ollama_chat_text(SimpleNamespace(message=SimpleNamespace(content="object text")))
        == "object text"
    )
    assert module._ollama_chat_text({"message": {"content": "mapping text"}}) == "mapping text"


def test_render_markdown_includes_per_query_failures() -> None:
    module = _load_module()
    report = module.run_suite(
        _suite(),
        variants=[module.Variant(name="no_context", no_context=True)],
        limit=5,
        retriever=None,
        generator=lambda _item, _contexts: "existence proof",
        answer_mode="fixture",
    )

    markdown = module.render_markdown(report)

    assert "Claim Ceiling" in markdown
    assert "not_upgraded" in markdown
    assert "no_context / q1" in markdown


def test_run_suite_reports_empty_generator_output_as_error() -> None:
    module = _load_module()

    report = module.run_suite(
        _suite(),
        variants=[module.Variant(name="no_context", no_context=True)],
        limit=5,
        retriever=None,
        generator=lambda _item, _contexts: "",
        answer_mode="fixture",
    )

    assert report["variants"][0]["queries"][0]["errors"] == ["empty_answer"]
