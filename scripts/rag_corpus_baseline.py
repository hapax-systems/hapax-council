#!/usr/bin/env python3
"""Read-only baseline report for the Qdrant RAG documents collection.

Run this before any destructive reindex, embedding change, or collection
migration. The report measures current payload shape and metadata contamination
without mutating Qdrant.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _payload_text(payload: dict[str, Any]) -> str:
    for key in ("text", "content", "body", "summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def classify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Classify one Qdrant payload for retrieval-quality reporting."""

    text = _payload_text(payload)
    text_len = len(text)
    source = str(payload.get("source", ""))
    source_service = payload.get("source_service")
    content_tier = payload.get("content_tier")
    retrieval_eligible = payload.get("retrieval_eligible")
    metadata_only = (
        _truthy(payload.get("is_metadata_only"))
        or content_tier == "metadata_only"
        or retrieval_eligible is False
        or (source_service == "gdrive" and "/.meta/" in source)
    )
    if not content_tier:
        if metadata_only:
            content_tier = "metadata_only"
        elif text_len < 200:
            content_tier = "low_content"
        else:
            content_tier = "full_text"

    return {
        "metadata_only": metadata_only,
        "content_tier": content_tier,
        "retrieval_eligible": retrieval_eligible,
        "text_length": text_len,
        "estimated_tokens": math.ceil(text_len / 4) if text_len else 0,
    }


def _distribution(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)

    def pct(p: float) -> int:
        index = min(len(ordered) - 1, round((len(ordered) - 1) * p))
        return ordered[index]

    return {
        "min": ordered[0],
        "p50": pct(0.5),
        "p90": pct(0.9),
        "max": ordered[-1],
        "avg": round(sum(ordered) / len(ordered), 2),
    }


def aggregate_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate sampled payloads into baseline contamination metrics."""

    source_services: Counter[str] = Counter()
    extensions: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    schema_keys: Counter[str] = Counter()
    chunk_indexes = 0
    chunk_counts = 0
    metadata_only = 0
    retrieval_ineligible = 0
    text_lengths: list[int] = []
    token_lengths: list[int] = []

    for payload in payloads:
        quality = classify_payload(payload)
        if quality["metadata_only"]:
            metadata_only += 1
        if payload.get("retrieval_eligible") is False:
            retrieval_ineligible += 1
        source_services[str(payload.get("source_service") or "unknown")] += 1
        extensions[
            str(
                payload.get("extension") or Path(str(payload.get("source", ""))).suffix or "unknown"
            )
        ] += 1
        tiers[str(quality["content_tier"])] += 1
        schema_keys.update(str(key) for key in payload)
        if "chunk_index" in payload:
            chunk_indexes += 1
        if "chunk_count" in payload:
            chunk_counts += 1
        text_lengths.append(int(quality["text_length"]))
        token_lengths.append(int(quality["estimated_tokens"]))

    sample_count = len(payloads)
    return {
        "sample_count": sample_count,
        "metadata_only_count": metadata_only,
        "metadata_only_rate": round(metadata_only / sample_count, 4) if sample_count else 0.0,
        "retrieval_ineligible_count": retrieval_ineligible,
        "retrieval_ineligible_rate": round(retrieval_ineligible / sample_count, 4)
        if sample_count
        else 0.0,
        "source_service_distribution": dict(source_services.most_common()),
        "extension_distribution": dict(extensions.most_common()),
        "content_tier_distribution": dict(tiers.most_common()),
        "text_length_distribution": _distribution(text_lengths),
        "estimated_token_distribution": _distribution(token_lengths),
        "payload_schema_keys": dict(schema_keys.most_common()),
        "chunk_index_coverage": round(chunk_indexes / sample_count, 4) if sample_count else 0.0,
        "chunk_count_coverage": round(chunk_counts / sample_count, 4) if sample_count else 0.0,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _collection_vector_size(collection_info: Any) -> Any:
    config = getattr(collection_info, "config", None)
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    if vectors is None:
        return None
    size = getattr(vectors, "size", None)
    if size is not None:
        return size
    if isinstance(vectors, dict):
        return {name: getattr(vector, "size", None) for name, vector in vectors.items()}
    return None


def collect_report(
    *,
    qdrant_url: str,
    collection: str,
    sample_size: int,
    queries: list[str] | None = None,
    query_limit: int = 5,
) -> dict[str, Any]:
    """Collect a read-only baseline report from Qdrant."""

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        from qdrant_client import QdrantClient
    except Exception as exc:
        return {
            "generated_at": generated_at,
            "collection": collection,
            "qdrant_url": qdrant_url,
            "available": False,
            "error": f"qdrant_client import failed: {exc}",
            "aggregate": aggregate_payloads([]),
            "query_smoke": [],
        }

    try:
        client = QdrantClient(url=qdrant_url)
        info = client.get_collection(collection)
        points, _ = client.scroll(
            collection_name=collection,
            limit=sample_size,
            with_payload=True,
            with_vectors=False,
        )
        payloads = [dict(point.payload or {}) for point in points]
        query_smoke = _run_query_smoke(client, collection, queries or [], query_limit)
        return {
            "generated_at": generated_at,
            "collection": collection,
            "qdrant_url": qdrant_url,
            "available": True,
            "collection_points_count": getattr(info, "points_count", None),
            "collection_vectors_count": getattr(info, "vectors_count", None),
            "vector_size": _collection_vector_size(info),
            "sample_size_requested": sample_size,
            "aggregate": aggregate_payloads(payloads),
            "query_smoke": query_smoke,
        }
    except Exception as exc:
        return {
            "generated_at": generated_at,
            "collection": collection,
            "qdrant_url": qdrant_url,
            "available": False,
            "error": str(exc),
            "aggregate": aggregate_payloads([]),
            "query_smoke": [],
        }


def _run_query_smoke(
    client: Any,
    collection: str,
    queries: list[str],
    query_limit: int,
) -> list[dict[str, Any]]:
    if not queries:
        return []
    try:
        from shared.config import embed
    except Exception as exc:
        return [{"query": query, "error": f"embed import failed: {exc}"} for query in queries]

    smoke = []
    for query in queries:
        try:
            vector = embed(query, prefix="search_query")
            result = client.query_points(collection, query=vector, limit=query_limit)
            smoke.append(
                {
                    "query": query,
                    "result_count": len(result.points),
                    "top": [
                        {
                            "score": point.score,
                            "source": (point.payload or {}).get("source"),
                            "source_service": (point.payload or {}).get("source_service"),
                            "content_tier": (point.payload or {}).get("content_tier"),
                            "retrieval_eligible": (point.payload or {}).get("retrieval_eligible"),
                        }
                        for point in result.points
                    ],
                }
            )
        except Exception as exc:
            smoke.append({"query": query, "error": str(exc)})
    return smoke


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report.get("aggregate", {})
    lines = [
        "# RAG Corpus Baseline",
        "",
        "> Mandatory read-only baseline before any reindex, embedding change, or collection migration.",
        "",
        f"- Generated at: `{report.get('generated_at')}`",
        f"- Collection: `{report.get('collection')}`",
        f"- Qdrant available: `{report.get('available')}`",
    ]
    if report.get("error"):
        lines.append(f"- Error: `{report['error']}`")
    lines.extend(
        [
            f"- Collection points: `{report.get('collection_points_count')}`",
            f"- Vector size: `{report.get('vector_size')}`",
            f"- Sample count: `{aggregate.get('sample_count', 0)}`",
            f"- Metadata-only rate: `{aggregate.get('metadata_only_rate', 0.0)}`",
            f"- Retrieval-ineligible rate: `{aggregate.get('retrieval_ineligible_rate', 0.0)}`",
            "",
            "## Source Services",
            "",
        ]
    )
    for key, count in aggregate.get("source_service_distribution", {}).items():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Content Tiers", ""])
    for key, count in aggregate.get("content_tier_distribution", {}).items():
        lines.append(f"- `{key}`: {count}")
    lines.extend(
        [
            "",
            "## Text Lengths",
            "",
            "```json",
            json.dumps(aggregate.get("text_length_distribution", {}), indent=2, sort_keys=True),
            "```",
            "",
            "## Payload Schema Keys",
            "",
        ]
    )
    for key, count in aggregate.get("payload_schema_keys", {}).items():
        lines.append(f"- `{key}`: {count}")
    if report.get("query_smoke"):
        lines.extend(["", "## Query Smoke", ""])
        for row in report["query_smoke"]:
            if row.get("error"):
                lines.append(f"- `{row['query']}`: error `{row['error']}`")
            else:
                lines.append(f"- `{row['query']}`: {row.get('result_count', 0)} results")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any], output_path: Path) -> tuple[Path, Path]:
    base = output_path.with_suffix("") if output_path.suffix else output_path
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _read_queries(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default="documents")
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("reports/rag-corpus-baseline/documents-baseline"),
        help="Base output path; .json and .md reports are emitted.",
    )
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--query-list", type=Path, help="Optional newline-delimited query list.")
    parser.add_argument("--query-limit", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_report(
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        sample_size=args.sample_size,
        queries=_read_queries(args.query_list),
        query_limit=args.query_limit,
    )
    json_path, md_path = write_reports(report, args.output_path)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
