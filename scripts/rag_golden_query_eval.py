#!/usr/bin/env python3
"""Evaluate audit-critical RAG retrieval against a local golden query suite."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.rag_inventory import is_inventory_payload

DEFAULT_COLLECTION = "documents"
DEFAULT_LIMIT = 10
DEFAULT_PRECISION_K = 5
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-cpu"
DEFAULT_EMBEDDING_BASE_MODEL = "nomic-embed-text-v2-moe"
DEFAULT_EXPECTED_EMBED_DIMENSIONS = 768
DEFAULT_SUITE = Path("evals/rag/golden_queries.json")


def load_suite(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("suite must contain a non-empty queries list")
    ids = [item.get("id") for item in queries if isinstance(item, Mapping)]
    if len(ids) != len(set(ids)):
        raise ValueError("suite query ids must be unique")
    return data


def is_metadata_hit(payload: Mapping[str, Any]) -> bool:
    return is_inventory_payload(payload)


def normalize_hit(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None) or {}
    if not isinstance(payload, Mapping):
        payload = {}
    text = str(payload.get("text", ""))
    return {
        "id": str(getattr(point, "id", "")),
        "score": getattr(point, "score", None),
        "source": str(payload.get("source", "")),
        "source_service": str(payload.get("source_service", "")),
        "content_type": str(payload.get("content_type", "")),
        "content_tier": str(payload.get("content_tier", "")),
        "text": text,
        "text_excerpt": text[:300],
        "is_metadata_hit": is_metadata_hit(payload),
    }


def _contains(haystack: str, needle: object) -> bool:
    return str(needle).lower() in haystack.lower()


def label_matches_hit(label: Mapping[str, Any], hit: Mapping[str, Any]) -> bool:
    checks = []
    if "source_contains" in label:
        checks.append(_contains(str(hit.get("source", "")), label["source_contains"]))
    if "source_service" in label:
        checks.append(
            str(hit.get("source_service", "")).lower() == str(label["source_service"]).lower()
        )
    if "content_type" in label:
        checks.append(
            str(hit.get("content_type", "")).lower() == str(label["content_type"]).lower()
        )
    if "text_contains" in label:
        checks.append(_contains(str(hit.get("text", "")), label["text_contains"]))
    return bool(checks) and all(checks)


def matched_label_indexes(hit: Mapping[str, Any], labels: Sequence[Mapping[str, Any]]) -> list[int]:
    return [index for index, label in enumerate(labels) if label_matches_hit(label, hit)]


def hit_grade(hit: Mapping[str, Any], labels: Sequence[Mapping[str, Any]]) -> int:
    grades = [int(labels[index].get("grade", 1)) for index in matched_label_indexes(hit, labels)]
    return max(grades, default=0)


def _dcg(grades: Sequence[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))


def _round_metric(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def label_signature(label: Mapping[str, Any]) -> str:
    return "|".join(f"{key}={value}" for key, value in sorted(label.items()) if key != "grade")


def _label_record(label: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in label.items() if key != "grade"}


def corpus_utilization_metrics(query_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    labels_by_signature: dict[str, Mapping[str, Any]] = {}
    source_labels_by_signature: dict[str, Mapping[str, Any]] = {}
    matched_signatures: set[str] = set()
    matched_source_signatures: set[str] = set()
    for report in query_reports:
        labels = [
            label for label in report.get("expected_sources", []) if isinstance(label, Mapping)
        ]
        for label in labels:
            signature = label_signature(label)
            if not signature:
                continue
            labels_by_signature.setdefault(signature, label)
            if "source_contains" in label:
                source_labels_by_signature.setdefault(signature, label)
        for hit in report.get("hits", []):
            if not isinstance(hit, Mapping):
                continue
            for index in matched_label_indexes(hit, labels):
                signature = label_signature(labels[index])
                matched_signatures.add(signature)
                if "source_contains" in labels[index]:
                    matched_source_signatures.add(signature)

    expected_count = len(labels_by_signature)
    expected_source_count = len(source_labels_by_signature)
    matched_count = len(matched_signatures)
    matched_source_count = len(matched_source_signatures)
    return {
        "expected_label_denominator": expected_count,
        "matched_label_numerator": matched_count,
        "golden_label_utilization_rate": _round_metric(
            matched_count / expected_count if expected_count else None
        ),
        "expected_source_label_denominator": expected_source_count,
        "matched_source_label_numerator": matched_source_count,
        "source_label_utilization_rate": _round_metric(
            matched_source_count / expected_source_count if expected_source_count else None
        ),
        "unmatched_expected_labels": [
            _label_record(labels_by_signature[signature])
            for signature in sorted(set(labels_by_signature) - matched_signatures)
        ],
        "unmatched_expected_source_labels": [
            _label_record(source_labels_by_signature[signature])
            for signature in sorted(set(source_labels_by_signature) - matched_source_signatures)
        ],
    }


def query_metrics(
    hits: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    *,
    precision_k: int = DEFAULT_PRECISION_K,
    recall_k: int | None = None,
    ndcg_k: int | None = None,
) -> dict[str, Any]:
    recall_limit = recall_k or len(hits)
    ndcg_limit = ndcg_k or len(hits)
    grades = [hit_grade(hit, labels) for hit in hits]
    matched_for_ranking: set[int] = set()
    ndcg_grades = []
    for hit in hits:
        new_label_grades = []
        for index in matched_label_indexes(hit, labels):
            if index in matched_for_ranking:
                continue
            matched_for_ranking.add(index)
            new_label_grades.append(int(labels[index].get("grade", 1)))
        ndcg_grades.append(max(new_label_grades, default=0))
    relevant_ranks = [index + 1 for index, grade in enumerate(grades) if grade > 0]
    precision_hits = sum(1 for grade in grades[:precision_k] if grade > 0)
    matched_labels = {
        index for hit in hits[:recall_limit] for index in matched_label_indexes(hit, labels)
    }
    label_count = len(labels)
    ideal_grades = sorted((int(label.get("grade", 1)) for label in labels), reverse=True)[
        :ndcg_limit
    ]
    dcg = _dcg(ndcg_grades[:ndcg_limit])
    ideal_dcg = _dcg(ideal_grades)
    metadata_hits = sum(1 for hit in hits if hit.get("is_metadata_hit"))

    return {
        "precision_at_5": _round_metric(precision_hits / precision_k if precision_k else None),
        "recall_at_k": _round_metric(len(matched_labels) / label_count if label_count else None),
        "mrr": _round_metric(1 / relevant_ranks[0] if relevant_ranks else 0.0),
        "ndcg_at_k": _round_metric(dcg / ideal_dcg if ideal_dcg else None),
        "metadata_hit_rate": _round_metric(metadata_hits / len(hits) if hits else 0.0),
        "hit_count": len(hits),
        "relevant_hit_count": len(relevant_ranks),
        "matched_label_count": len(matched_labels),
        "label_count": label_count,
        "no_hits": len(hits) == 0,
        "no_relevant_evidence": len(relevant_ranks) == 0,
    }


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


def aggregate_metrics(query_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [report["retrieval_metrics"] for report in query_reports]
    unique_sources = {
        hit.get("source")
        for report in query_reports
        for hit in report.get("hits", [])
        if hit.get("source")
    }
    services = Counter(
        str(hit.get("source_service") or "unknown")
        for report in query_reports
        for hit in report.get("hits", [])
    )
    total = len(metrics)
    query_error_count = sum(1 for report in query_reports if report.get("errors"))
    utilization = corpus_utilization_metrics(query_reports)
    return {
        "query_count": total,
        "query_error_count": query_error_count,
        "query_error_rate": _round_metric(query_error_count / total if total else None),
        "mean_precision_at_5": _mean([item["precision_at_5"] for item in metrics]),
        "mean_recall_at_k": _mean([item["recall_at_k"] for item in metrics]),
        "mean_mrr": _mean([item["mrr"] for item in metrics]),
        "mean_ndcg_at_k": _mean([item["ndcg_at_k"] for item in metrics]),
        "mean_metadata_hit_rate": _mean([item["metadata_hit_rate"] for item in metrics]),
        "no_hits_rate": _round_metric(
            sum(1 for item in metrics if item["no_hits"]) / total if total else None
        ),
        "no_relevant_evidence_rate": _round_metric(
            sum(1 for item in metrics if item["no_relevant_evidence"]) / total if total else None
        ),
        "unique_source_count": len(unique_sources),
        "source_service_distribution": dict(services.most_common()),
        "corpus_utilization": utilization,
        "golden_label_utilization_rate": utilization["golden_label_utilization_rate"],
        "golden_label_utilization_numerator": utilization["matched_label_numerator"],
        "golden_label_utilization_denominator": utilization["expected_label_denominator"],
        "source_label_utilization_rate": utilization["source_label_utilization_rate"],
        "source_label_utilization_numerator": utilization["matched_source_label_numerator"],
        "source_label_utilization_denominator": utilization["expected_source_label_denominator"],
    }


def compare_reports(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    current_metrics = current.get("retrieval_summary", {})
    baseline_metrics = baseline.get("retrieval_summary", {})
    compared_keys = [
        "mean_precision_at_5",
        "mean_recall_at_k",
        "mean_mrr",
        "mean_ndcg_at_k",
        "mean_metadata_hit_rate",
        "no_relevant_evidence_rate",
        "golden_label_utilization_rate",
        "source_label_utilization_rate",
    ]
    deltas: dict[str, float | None] = {}
    for key in compared_keys:
        current_value = current_metrics.get(key)
        baseline_value = baseline_metrics.get(key)
        if isinstance(current_value, int | float) and isinstance(baseline_value, int | float):
            deltas[key] = round(float(current_value) - float(baseline_value), 4)
        else:
            deltas[key] = None
    return {
        "baseline_generated_at": baseline.get("generated_at"),
        "current_generated_at": current.get("generated_at"),
        "metric_deltas": deltas,
    }


def _embed_query(query: str, *, model: str, ollama_url: str) -> list[float]:
    import ollama

    client = ollama.Client(host=ollama_url)
    result = client.embed(model=model, input=[f"search_query: {query}"])
    return result["embeddings"][0]


def _points_from_response(response: Any) -> Sequence[Any]:
    points = getattr(response, "points", [])
    return points if isinstance(points, Sequence) else []


def _inventory_filter(exclude_inventory: bool) -> Any:
    if not exclude_inventory:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

    return Filter(
        must_not=[
            FieldCondition(key="retrieval_eligible", match=MatchValue(value=False)),
            FieldCondition(key="is_metadata_only", match=MatchValue(value=True)),
            FieldCondition(
                key="content_tier",
                match=MatchAny(any=["metadata_only", "metadata-only", "stub", "inventory"]),
            ),
        ]
    )


def query_qdrant(
    client: Any,
    collection: str,
    query: str,
    *,
    limit: int,
    embedder: Callable[[str], list[float]],
    exclude_inventory: bool = False,
) -> list[dict[str, Any]]:
    vector = embedder(query)
    query_limit = limit * 10 if exclude_inventory else limit
    response = client.query_points(
        collection_name=collection,
        query=vector,
        query_filter=_inventory_filter(exclude_inventory),
        limit=query_limit,
        with_payload=True,
        with_vectors=False,
    )
    hits = [normalize_hit(point) for point in _points_from_response(response)]
    if exclude_inventory:
        hits = [hit for hit in hits if not hit["is_metadata_hit"]]
    return hits[:limit]


def run_suite(
    suite: Mapping[str, Any],
    *,
    collection: str,
    limit: int,
    precision_k: int,
    qdrant_url: str,
    embedding_model: str,
    ollama_url: str,
    exclude_inventory: bool = False,
    client: Any | None = None,
    embedder: Callable[[str], list[float]] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if client is None:
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=qdrant_url)
        except Exception as exc:
            client = None
            errors.append(f"qdrant_client_unavailable: {exc}")

    if embedder is None:

        def embedder(query: str) -> list[float]:
            return _embed_query(
                query,
                model=embedding_model,
                ollama_url=ollama_url,
            )

    query_reports = []
    for item in suite["queries"]:
        labels = item.get("expected_sources") or []
        hits: list[dict[str, Any]] = []
        query_errors: list[str] = []
        if client is None:
            query_errors.append("qdrant_client_unavailable")
        else:
            try:
                hits = query_qdrant(
                    client,
                    collection,
                    item["query"],
                    limit=limit,
                    embedder=embedder,
                    exclude_inventory=exclude_inventory,
                )
            except Exception as exc:
                query_errors.append(f"{type(exc).__name__}: {exc}")
        query_reports.append(
            {
                "id": item["id"],
                "topic": item.get("topic", "unknown"),
                "query": item["query"],
                "expected_sources": labels,
                "retrieval_metrics": query_metrics(
                    hits,
                    labels,
                    precision_k=precision_k,
                    recall_k=limit,
                    ndcg_k=limit,
                ),
                "hits": [
                    {key: value for key, value in hit.items() if key != "text"} for hit in hits
                ],
                "errors": query_errors,
            }
        )

    query_error_messages = sorted(
        {error for query_report in query_reports for error in query_report.get("errors", [])}
    )
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "suite_id": suite.get("suite_id"),
        "suite_version": suite.get("version"),
        "collection": collection,
        "limit": limit,
        "precision_k": precision_k,
        "qdrant_url": qdrant_url,
        "embedding_model": embedding_model,
        "exclude_inventory": exclude_inventory,
        "retrieval_summary": aggregate_metrics(query_reports),
        "queries": query_reports,
        "answer_faithfulness": {
            "status": "not_evaluated",
            "reason": "This suite measures retrieval only. Faithfulness requires grounded answer artifacts and claim-to-source checks.",
        },
        "errors": [*errors, *query_error_messages],
    }
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["retrieval_summary"]
    lines = [
        "# RAG Golden Query Evaluation",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Suite: `{report.get('suite_id')}` v`{report.get('suite_version')}`",
        f"- Collection: `{report.get('collection')}`",
        f"- Limit: `{report.get('limit')}`",
        f"- Exclude inventory: `{report.get('exclude_inventory')}`",
        "",
        "## Retrieval Summary",
        "",
    ]
    for key, value in summary.items():
        if key == "corpus_utilization":
            continue
        lines.append(f"- `{key}`: {value}")

    utilization = summary.get("corpus_utilization")
    if isinstance(utilization, Mapping):
        lines.extend(["", "## Corpus Utilization", ""])
        lines.append(
            "- Golden label utilization: `{num}/{den}` (`{rate}`)".format(
                num=utilization.get("matched_label_numerator"),
                den=utilization.get("expected_label_denominator"),
                rate=utilization.get("golden_label_utilization_rate"),
            )
        )
        lines.append(
            "- Source label utilization: `{num}/{den}` (`{rate}`)".format(
                num=utilization.get("matched_source_label_numerator"),
                den=utilization.get("expected_source_label_denominator"),
                rate=utilization.get("source_label_utilization_rate"),
            )
        )
        unmatched = utilization.get("unmatched_expected_source_labels") or []
        if unmatched:
            lines.append(f"- Unmatched source labels: `{len(unmatched)}`")

    lines.extend(
        [
            "",
            "## Answer Faithfulness",
            "",
            f"- Status: `{report['answer_faithfulness']['status']}`",
            f"- Reason: {report['answer_faithfulness']['reason']}",
            "",
            "## Query Results",
            "",
        ]
    )
    for query in report["queries"]:
        metrics = query["retrieval_metrics"]
        lines.extend(
            [
                f"### {query['id']}",
                "",
                f"- Topic: `{query['topic']}`",
                f"- Query: {query['query']}",
                f"- Precision@5: `{metrics['precision_at_5']}`",
                f"- Recall@k: `{metrics['recall_at_k']}`",
                f"- MRR: `{metrics['mrr']}`",
                f"- nDCG@k: `{metrics['ndcg_at_k']}`",
                f"- Metadata-hit rate: `{metrics['metadata_hit_rate']}`",
                f"- No relevant evidence: `{metrics['no_relevant_evidence']}`",
            ]
        )
        if query.get("errors"):
            lines.append(f"- Errors: `{'; '.join(query['errors'])}`")
        for hit in query.get("hits", [])[:5]:
            lines.append(
                "- hit score=`{score}` metadata=`{metadata}` service=`{service}` source=`{source}`".format(
                    score=hit.get("score"),
                    metadata=hit.get("is_metadata_hit"),
                    service=hit.get("source_service"),
                    source=hit.get("source"),
                )
            )
        lines.append("")

    if report.get("comparison"):
        lines.extend(["## Baseline Comparison", ""])
        for key, value in report["comparison"]["metric_deltas"].items():
            lines.append(f"- `{key}` delta: {value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_outputs(output: Path | None) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if output is None:
        output = Path("reports/rag-golden-query") / f"rag-golden-query-{timestamp}.json"
    if output.suffix.lower() == ".md":
        return output.with_suffix(".json"), output
    if output.suffix.lower() == ".json":
        return output, output.with_suffix(".md")
    return (
        output / f"rag-golden-query-{timestamp}.json",
        output / f"rag-golden-query-{timestamp}.md",
    )


def write_report(report: Mapping[str, Any], output: Path | None) -> tuple[Path, Path]:
    json_path, markdown_path = _resolve_outputs(output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--precision-k", type=int, default=DEFAULT_PRECISION_K)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument(
        "--embedding-base-model",
        default=os.environ.get("NOMIC_BASE_MODEL", DEFAULT_EMBEDDING_BASE_MODEL),
        help="Base Ollama model expected before the embedding alias is copied.",
    )
    parser.add_argument(
        "--expected-embed-dimensions",
        type=int,
        default=int(os.environ.get("EXPECTED_EMBED_DIMENSIONS", DEFAULT_EXPECTED_EMBED_DIMENSIONS)),
    )
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    parser.add_argument(
        "--skip-embedding-health-check",
        action="store_true",
        help="Skip the local Ollama alias/dimension preflight.",
    )
    parser.add_argument("--exclude-inventory", action="store_true")
    parser.add_argument("--compare", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def run_embedding_health_preflight(
    *,
    ollama_url: str,
    embedding_model: str,
    embedding_base_model: str | None,
    expected_dimensions: int,
) -> dict[str, Any]:
    script_path = Path(__file__).resolve().with_name("nomic_embedding_health_check.py")
    spec = importlib.util.spec_from_file_location("_nomic_embedding_health_check", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load embedding health check from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.run_health_check(
        ollama_url=ollama_url,
        model_alias=embedding_model,
        base_model=embedding_base_model,
        expected_dimensions=expected_dimensions,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.skip_embedding_health_check:
        health_report = run_embedding_health_preflight(
            ollama_url=args.ollama_url,
            embedding_model=args.embedding_model,
            embedding_base_model=args.embedding_base_model,
            expected_dimensions=args.expected_embed_dimensions,
        )
        if not health_report["ok"]:
            print("embedding health check failed:", file=sys.stderr)
            print(json.dumps(health_report, indent=2, sort_keys=True), file=sys.stderr)
            return 2
        dimensions = health_report["checks"]["embedding_dimensions"]["observed"][0]
        print(f"embedding health: ok model={args.embedding_model} dimensions={dimensions}")
    suite = load_suite(args.suite)
    report = run_suite(
        suite,
        collection=args.collection,
        limit=args.limit,
        precision_k=args.precision_k,
        qdrant_url=args.qdrant_url,
        embedding_model=args.embedding_model,
        ollama_url=args.ollama_url,
        exclude_inventory=args.exclude_inventory,
    )
    if args.compare:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        report["comparison"] = compare_reports(report, baseline)
    json_path, markdown_path = write_report(report, args.output)
    print(f"wrote JSON: {json_path}")
    print(f"wrote Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
