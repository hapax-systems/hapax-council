#!/usr/bin/env python3
"""Evaluate RAG answer faithfulness and downstream evidence contribution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rag_golden_query_eval as retrieval_eval

DEFAULT_COLLECTION = "documents_v2"
DEFAULT_LIMIT = 8
DEFAULT_OUTPUT_DIR = Path("reports/rag-answer-faithfulness")
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-cpu"
DEFAULT_GENERATOR_MODEL = "phi4-mini:latest"
DEFAULT_SUITE = Path("evals/rag/answer_faithfulness_v1.json")
DEFAULT_CONTEXT_CHARS = 1200


@dataclass(frozen=True)
class Variant:
    name: str
    collection: str | None = None
    no_context: bool = False
    exclude_inventory: bool = True


AnswerGenerator = Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], str]
Retriever = Callable[[str, str, int, bool], list[dict[str, Any]]]


def _round_metric(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _contains(text: str, term: object) -> bool:
    return str(term).lower() in text.lower()


def _term_coverage(text: str, terms: Sequence[Any]) -> float | None:
    if not terms:
        return None
    matched = sum(1 for term in terms if _contains(text, term))
    return _round_metric(matched / len(terms))


def _claim_terms(claim: Mapping[str, Any], key: str, fallback: str) -> list[str]:
    value = claim.get(key)
    if value is None:
        value = claim.get(fallback, [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def _source_matches(claim: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]]) -> bool:
    expected_sources = claim.get("source_contains") or []
    if isinstance(expected_sources, str):
        expected_sources = [expected_sources]
    if not expected_sources:
        return True
    for context in contexts:
        source = str(context.get("source", ""))
        if any(_contains(source, expected) for expected in expected_sources):
            return True
    return False


def load_suite(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("suite must contain a non-empty queries list")
    ids: list[str] = []
    for item in queries:
        if not isinstance(item, Mapping):
            raise ValueError("suite queries must be objects")
        query_id = item.get("id")
        if not isinstance(query_id, str) or not query_id:
            raise ValueError("each query must have an id")
        ids.append(query_id)
        if not item.get("query"):
            raise ValueError(f"{query_id}: missing query")
        if not item.get("reference_answer"):
            raise ValueError(f"{query_id}: missing reference_answer")
        required_claims = item.get("required_claims")
        if not isinstance(required_claims, list) or not required_claims:
            raise ValueError(f"{query_id}: missing required_claims")
    if len(ids) != len(set(ids)):
        raise ValueError("suite query ids must be unique")
    return data


def score_answer(
    item: Mapping[str, Any],
    answer: str,
    contexts: Sequence[Mapping[str, Any]],
    *,
    no_relevant_evidence: bool | None = None,
) -> dict[str, Any]:
    context_text = "\n".join(str(context.get("text", "")) for context in contexts)
    required_claims = [
        claim for claim in item.get("required_claims", []) if isinstance(claim, Mapping)
    ]
    claim_reports = []
    present_required = 0
    supported_required = 0
    support_denominator = len(required_claims)
    for claim in required_claims:
        answer_terms = _claim_terms(claim, "answer_terms", "terms")
        support_terms = _claim_terms(claim, "support_terms", "terms")
        answer_coverage = _term_coverage(answer, answer_terms)
        support_coverage = _term_coverage(context_text, support_terms)
        present = bool(answer_terms) and all(_contains(answer, term) for term in answer_terms)
        supported = (
            present
            and bool(support_terms)
            and all(_contains(context_text, term) for term in support_terms)
            and _source_matches(claim, contexts)
        )
        if present:
            present_required += 1
        if supported:
            supported_required += 1
        claim_reports.append(
            {
                "id": str(claim.get("id", "")),
                "answer_term_coverage": answer_coverage,
                "support_term_coverage": support_coverage,
                "present_in_answer": present,
                "supported_by_context": supported,
                "source_match_required": bool(claim.get("source_contains")),
                "source_matched": _source_matches(claim, contexts),
            }
        )

    forbidden_reports = []
    for forbidden in item.get("forbidden_claims", []):
        if not isinstance(forbidden, Mapping):
            continue
        terms = _claim_terms(forbidden, "terms", "answer_terms")
        matched_terms = [term for term in terms if _contains(answer, term)]
        if matched_terms:
            forbidden_reports.append(
                {
                    "id": str(forbidden.get("id", "")),
                    "matched_terms": matched_terms,
                }
            )

    refusal_terms = item.get("insufficient_evidence_terms") or [
        "insufficient evidence",
        "not enough evidence",
        "cannot answer",
        "cannot determine",
    ]
    if isinstance(refusal_terms, str):
        refusal_terms = [refusal_terms]
    insufficient_evidence_signaled = any(_contains(answer, term) for term in refusal_terms)
    expected_refusal = bool(item.get("expected_refusal_when_no_evidence", False))
    if no_relevant_evidence is not None:
        expected_refusal = expected_refusal and no_relevant_evidence

    required_count = len(required_claims)
    required_claim_recall = _round_metric(
        present_required / required_count if required_count else None
    )
    supported_required_claim_rate = _round_metric(
        supported_required / support_denominator if support_denominator else None
    )
    answer_faithfulness = _round_metric(
        supported_required / present_required if present_required else None
    )
    forbidden_claim_count = len(forbidden_reports)
    contribution_score = supported_required_claim_rate or 0.0

    return {
        "required_claim_count": required_count,
        "present_required_claim_count": present_required,
        "supported_required_claim_count": supported_required,
        "required_claim_recall": required_claim_recall,
        "supported_required_claim_rate": supported_required_claim_rate,
        "answer_faithfulness": answer_faithfulness,
        "forbidden_claim_count": forbidden_claim_count,
        "forbidden_claim_hits": forbidden_reports,
        "expected_refusal_when_no_evidence": expected_refusal,
        "insufficient_evidence_signaled": insufficient_evidence_signaled,
        "contribution_score": contribution_score,
        "claim_checks": claim_reports,
    }


def aggregate_answer_metrics(query_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scores = [report["answer_metrics"] for report in query_reports]
    total = len(scores)
    refusal_expected = [item for item in scores if item.get("expected_refusal_when_no_evidence")]
    refusal_hits = [
        item for item in refusal_expected if item.get("insufficient_evidence_signaled") is True
    ]
    return {
        "query_count": total,
        "mean_required_claim_recall": _mean([item.get("required_claim_recall") for item in scores]),
        "mean_supported_required_claim_rate": _mean(
            [item.get("supported_required_claim_rate") for item in scores]
        ),
        "mean_answer_faithfulness": _mean([item.get("answer_faithfulness") for item in scores]),
        "mean_contribution_score": _mean([item.get("contribution_score") for item in scores]),
        "total_forbidden_claim_hits": sum(
            int(item.get("forbidden_claim_count", 0)) for item in scores
        ),
        "refusal_expected_count": len(refusal_expected),
        "refusal_hit_rate": _round_metric(
            len(refusal_hits) / len(refusal_expected) if refusal_expected else None
        ),
    }


def _mean(values: Sequence[Any]) -> float | None:
    present = [float(value) for value in values if isinstance(value, int | float)]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


def extractive_answer_generator(
    item: Mapping[str, Any],
    contexts: Sequence[Mapping[str, Any]],
    *,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> str:
    if not contexts:
        return "Insufficient evidence in retrieved contexts to answer this question."
    parts = [f"Question: {item['query']}", "Retrieved evidence:"]
    for index, context in enumerate(contexts[:4], start=1):
        text = " ".join(str(context.get("text", "")).split())
        source = str(context.get("source", "unknown"))
        parts.append(f"{index}. {source}: {text[:context_chars]}")
    return "\n".join(parts)


def ollama_answer_generator(
    *,
    model: str,
    ollama_url: str,
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> AnswerGenerator:
    def generate(item: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]]) -> str:
        if not contexts:
            return "Insufficient evidence in retrieved contexts to answer this question."
        import ollama

        client = ollama.Client(host=ollama_url)
        context_lines = []
        for index, context in enumerate(contexts[:6], start=1):
            text = " ".join(str(context.get("text", "")).split())
            source = str(context.get("source", "unknown"))
            context_lines.append(f"[{index}] source={source}\n{text[:context_chars]}")
        response = client.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided retrieved contexts. "
                        "If the contexts do not support the answer, say "
                        "'Insufficient evidence in retrieved contexts.'"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {item['query']}\n\nRetrieved contexts:\n"
                        + "\n\n".join(context_lines)
                    ),
                },
            ],
            options={"temperature": 0, "seed": 42, "num_predict": 384},
        )
        return _ollama_chat_text(response)

    return generate


def _ollama_chat_text(response: Any) -> str:
    message = getattr(response, "message", None)
    content = getattr(message, "content", None)
    if content is not None:
        return str(content)
    if isinstance(response, Mapping):
        message_dict = response.get("message")
        if isinstance(message_dict, Mapping) and message_dict.get("content") is not None:
            return str(message_dict["content"])
    return str(response)


def build_retriever(
    *,
    qdrant_url: str,
    embedding_model: str,
    ollama_url: str,
) -> Retriever:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=qdrant_url)

    def embedder(query: str) -> list[float]:
        return retrieval_eval._embed_query(  # noqa: SLF001
            query,
            model=embedding_model,
            ollama_url=ollama_url,
        )

    def retrieve(
        collection: str, query: str, limit: int, exclude_inventory: bool
    ) -> list[dict[str, Any]]:
        return retrieval_eval.query_qdrant(
            client,
            collection,
            query,
            limit=limit,
            embedder=embedder,
            exclude_inventory=exclude_inventory,
        )

    return retrieve


def run_variant(
    suite: Mapping[str, Any],
    variant: Variant,
    *,
    limit: int,
    retriever: Retriever | None,
    generator: AnswerGenerator,
) -> dict[str, Any]:
    query_reports = []
    retrieval_summary_reports = []
    for item in suite["queries"]:
        labels = item.get("expected_sources") or []
        errors: list[str] = []
        contexts: list[dict[str, Any]] = []
        if not variant.no_context:
            if retriever is None or variant.collection is None:
                errors.append("retriever_unavailable")
            else:
                try:
                    contexts = retriever(
                        variant.collection,
                        item["query"],
                        limit,
                        variant.exclude_inventory,
                    )
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
        answer = generator(item, contexts)
        retrieval_metrics = retrieval_eval.query_metrics(
            contexts,
            labels,
            precision_k=min(5, limit),
            recall_k=limit,
            ndcg_k=limit,
        )
        if not answer.strip():
            errors.append("empty_answer")
        answer_metrics = score_answer(
            item,
            answer,
            contexts,
            no_relevant_evidence=bool(retrieval_metrics["no_relevant_evidence"]),
        )
        retrieval_summary_reports.append(
            {
                "expected_sources": labels,
                "retrieval_metrics": retrieval_metrics,
                "hits": contexts,
                "errors": errors,
            }
        )
        query_reports.append(
            {
                "id": item["id"],
                "topic": item.get("topic", "unknown"),
                "query": item["query"],
                "reference_answer": item["reference_answer"],
                "retrieval_metrics": retrieval_metrics,
                "answer": answer,
                "answer_metrics": answer_metrics,
                "contexts": [
                    {
                        key: value
                        for key, value in context.items()
                        if key in {"id", "score", "source", "source_service", "text_excerpt"}
                    }
                    for context in contexts
                ],
                "errors": errors,
            }
        )
    return {
        "name": variant.name,
        "collection": variant.collection,
        "no_context": variant.no_context,
        "exclude_inventory": variant.exclude_inventory,
        "retrieval_summary": retrieval_eval.aggregate_metrics(retrieval_summary_reports),
        "answer_summary": aggregate_answer_metrics(query_reports),
        "queries": query_reports,
    }


def compare_variant_summaries(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    current_summary = current.get("answer_summary", {})
    baseline_summary = baseline.get("answer_summary", {})
    keys = [
        "mean_required_claim_recall",
        "mean_supported_required_claim_rate",
        "mean_answer_faithfulness",
        "mean_contribution_score",
        "total_forbidden_claim_hits",
    ]
    deltas: dict[str, float | None] = {}
    for key in keys:
        current_value = current_summary.get(key)
        baseline_value = baseline_summary.get(key)
        if isinstance(current_value, int | float) and isinstance(baseline_value, int | float):
            deltas[key] = round(float(current_value) - float(baseline_value), 4)
        else:
            deltas[key] = None
    return {
        "baseline": baseline.get("name"),
        "current": current.get("name"),
        "answer_metric_deltas": deltas,
    }


def build_downstream_contribution(variants: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    comparisons = []
    by_name = {str(variant.get("name")): variant for variant in variants}
    if "no_context" in by_name:
        baseline = by_name["no_context"]
        for variant in variants:
            if variant.get("name") != "no_context":
                comparisons.append(compare_variant_summaries(variant, baseline))
    if "documents" in by_name and "documents_v2" in by_name:
        comparisons.append(compare_variant_summaries(by_name["documents_v2"], by_name["documents"]))
    return comparisons


def build_interchange_records(variant: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    ragas_records = []
    deepeval_records = []
    for query in variant.get("queries", []):
        contexts = [
            str(context.get("text_excerpt", ""))
            for context in query.get("contexts", [])
            if context.get("text_excerpt")
        ]
        ragas_records.append(
            {
                "user_input": query.get("query"),
                "retrieved_contexts": contexts,
                "response": query.get("answer"),
                "reference": query.get("reference_answer"),
            }
        )
        deepeval_records.append(
            {
                "input": query.get("query"),
                "actual_output": query.get("answer"),
                "expected_output": query.get("reference_answer"),
                "retrieval_context": contexts,
            }
        )
    return {"ragas": ragas_records, "deepeval": deepeval_records}


def run_suite(
    suite: Mapping[str, Any],
    *,
    variants: Sequence[Variant],
    limit: int,
    retriever: Retriever | None,
    generator: AnswerGenerator,
    answer_mode: str,
    generator_model: str | None = None,
) -> dict[str, Any]:
    variant_reports = [
        run_variant(
            suite,
            variant,
            limit=limit,
            retriever=retriever,
            generator=generator,
        )
        for variant in variants
    ]
    interchange = {
        str(variant["name"]): build_interchange_records(variant) for variant in variant_reports
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "suite_id": suite.get("suite_id"),
        "suite_version": suite.get("version"),
        "answer_mode": answer_mode,
        "generator_model": generator_model,
        "limit": limit,
        "variants": variant_reports,
        "downstream_contribution": build_downstream_contribution(variant_reports),
        "interchange_records": interchange,
        "claim_ceiling": {
            "status": "not_upgraded",
            "reason": (
                "This report measures answer artifacts and ablation deltas. "
                "It does not upgrade Token Capital to an existence proof or "
                "publication-grade compounding claim."
            ),
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RAG Answer Faithfulness Evaluation",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Suite: `{report.get('suite_id')}` v`{report.get('suite_version')}`",
        f"- Answer mode: `{report.get('answer_mode')}`",
        f"- Generator model: `{report.get('generator_model')}`",
        "",
        "## Claim Ceiling",
        "",
        f"- Status: `{report['claim_ceiling']['status']}`",
        f"- Reason: {report['claim_ceiling']['reason']}",
        "",
        "## Variant Summaries",
        "",
    ]
    for variant in report["variants"]:
        lines.extend(
            [
                f"### {variant['name']}",
                "",
                f"- Collection: `{variant.get('collection')}`",
                f"- No context: `{variant.get('no_context')}`",
                f"- Mean required-claim recall: `{variant['answer_summary']['mean_required_claim_recall']}`",
                f"- Mean supported required-claim rate: `{variant['answer_summary']['mean_supported_required_claim_rate']}`",
                f"- Mean answer faithfulness: `{variant['answer_summary']['mean_answer_faithfulness']}`",
                f"- Forbidden claim hits: `{variant['answer_summary']['total_forbidden_claim_hits']}`",
                "",
            ]
        )
    lines.extend(["## Downstream Contribution", ""])
    for comparison in report.get("downstream_contribution", []):
        lines.append(f"### {comparison['baseline']} -> {comparison['current']}")
        for key, value in comparison["answer_metric_deltas"].items():
            lines.append(f"- `{key}` delta: {value}")
        lines.append("")
    lines.extend(["## Query Failures", ""])
    for variant in report["variants"]:
        for query in variant.get("queries", []):
            metrics = query["answer_metrics"]
            if (
                metrics.get("supported_required_claim_count") == metrics.get("required_claim_count")
                and not metrics.get("forbidden_claim_hits")
                and not query.get("errors")
            ):
                continue
            lines.extend(
                [
                    f"### {variant['name']} / {query['id']}",
                    "",
                    f"- Required recall: `{metrics['required_claim_recall']}`",
                    f"- Supported claim rate: `{metrics['supported_required_claim_rate']}`",
                    f"- Faithfulness: `{metrics['answer_faithfulness']}`",
                    f"- Forbidden hits: `{metrics['forbidden_claim_count']}`",
                    f"- Insufficient evidence signaled: `{metrics['insufficient_evidence_signaled']}`",
                ]
            )
            if query.get("errors"):
                lines.append(f"- Errors: `{'; '.join(query['errors'])}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_outputs(output: Path | None) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if output is None:
        output = DEFAULT_OUTPUT_DIR / f"rag-answer-faithfulness-{timestamp}.json"
    if output.suffix.lower() == ".md":
        return output.with_suffix(".json"), output
    if output.suffix.lower() == ".json":
        return output, output.with_suffix(".md")
    return (
        output / f"rag-answer-faithfulness-{timestamp}.json",
        output / f"rag-answer-faithfulness-{timestamp}.md",
    )


def write_report(report: Mapping[str, Any], output: Path | None) -> tuple[Path, Path]:
    json_path, markdown_path = _resolve_outputs(output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def parse_variants(args: argparse.Namespace) -> list[Variant]:
    variants: list[Variant] = []
    if args.include_no_context:
        variants.append(Variant(name="no_context", no_context=True))
    for collection in args.collections:
        variants.append(
            Variant(
                name=collection,
                collection=collection,
                no_context=False,
                exclude_inventory=args.exclude_inventory,
            )
        )
    if not variants:
        variants.append(
            Variant(
                name=args.collection,
                collection=args.collection,
                no_context=False,
                exclude_inventory=args.exclude_inventory,
            )
        )
    return variants


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--collections", nargs="*", default=[])
    parser.add_argument("--include-no-context", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    parser.add_argument(
        "--answer-mode",
        choices=["extractive", "ollama"],
        default="extractive",
    )
    parser.add_argument("--generator-model", default=DEFAULT_GENERATOR_MODEL)
    parser.add_argument("--context-chars", type=int, default=DEFAULT_CONTEXT_CHARS)
    parser.add_argument("--exclude-inventory", action="store_true", default=True)
    parser.add_argument("--include-inventory", dest="exclude_inventory", action="store_false")
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    suite = load_suite(args.suite)
    variants = parse_variants(args)
    retriever = build_retriever(
        qdrant_url=args.qdrant_url,
        embedding_model=args.embedding_model,
        ollama_url=args.ollama_url,
    )
    if args.answer_mode == "ollama":
        generator = ollama_answer_generator(
            model=args.generator_model,
            ollama_url=args.ollama_url,
            context_chars=args.context_chars,
        )
        generator_model = args.generator_model
    else:

        def generator(
            item: Mapping[str, Any],
            contexts: Sequence[Mapping[str, Any]],
        ) -> str:
            return extractive_answer_generator(
                item,
                contexts,
                context_chars=args.context_chars,
            )

        generator_model = None
    report = run_suite(
        suite,
        variants=variants,
        limit=args.limit,
        retriever=retriever,
        generator=generator,
        answer_mode=args.answer_mode,
        generator_model=generator_model,
    )
    json_path, markdown_path = write_report(report, args.output)
    print(f"wrote JSON: {json_path}")
    print(f"wrote Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
