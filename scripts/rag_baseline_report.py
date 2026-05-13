#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["qdrant-client>=1.17.0", "ollama>=0.6.1"]
# ///
"""Read-only baseline report for the Qdrant RAG documents collection.

This is the mandatory first step before RAG reindexing, embedding changes,
chunking changes, or collection schema migration. It measures the live corpus
without mutating Qdrant and emits JSON plus Markdown reports suitable for
comparison after quality gates or shadow-index work.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_COLLECTION = "documents"
DEFAULT_SAMPLE_SIZE = 500
DEFAULT_QUERY_LIMIT = 5
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-cpu"


@dataclass(frozen=True)
class PayloadClassification:
    """Normalized read-only classification of a documents payload."""

    source_service: str
    extension: str
    content_type: str
    content_tier: str
    retrieval_eligible: bool | None
    is_metadata_only: bool
    likely_metadata_stub: bool
    metadata_indicators: tuple[str, ...]
    text_length: int
    estimated_tokens: int
    chunk_index: int | None
    chunk_count: int | None


@dataclass
class CorpusStats:
    """Aggregated payload statistics from a Qdrant sample."""

    sampled_points: int = 0
    source_services: Counter[str] = field(default_factory=Counter)
    extensions: Counter[str] = field(default_factory=Counter)
    content_types: Counter[str] = field(default_factory=Counter)
    content_tiers: Counter[str] = field(default_factory=Counter)
    retrieval_eligible: Counter[str] = field(default_factory=Counter)
    metadata_only_count: int = 0
    likely_metadata_stub_count: int = 0
    metadata_indicators: Counter[str] = field(default_factory=Counter)
    text_lengths: list[int] = field(default_factory=list)
    estimated_tokens: list[int] = field(default_factory=list)
    missing_chunk_index: int = 0
    missing_chunk_count: int = 0
    chunk_index_out_of_range: int = 0


def _safe_str(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_payload(payload: dict[str, Any]) -> PayloadClassification:
    """Classify one Qdrant documents payload for baseline reporting."""

    text = _safe_str(payload.get("text"), default="")
    source = _safe_str(payload.get("source"), default="")
    source_service = _safe_str(payload.get("source_service"), default="unknown")
    extension = _safe_str(payload.get("extension") or Path(source).suffix.lower(), default="none")
    content_type = _safe_str(payload.get("content_type"), default="unknown")
    content_tier = _safe_str(payload.get("content_tier"), default="unspecified")
    retrieval_eligible = _safe_bool(payload.get("retrieval_eligible"))
    explicit_metadata_only = _safe_bool(payload.get("is_metadata_only")) is True
    chunk_index = _safe_int(payload.get("chunk_index"))
    chunk_count = _safe_int(payload.get("chunk_count"))

    indicators: list[str] = []
    if explicit_metadata_only:
        indicators.append("is_metadata_only=true")
    if content_tier == "metadata_only":
        indicators.append("content_tier=metadata_only")
    if retrieval_eligible is False:
        indicators.append("retrieval_eligible=false")
    if "/gdrive/.meta/" in source or source.endswith("/.meta"):
        indicators.append("gdrive_meta_path")
    if source_service == "gdrive" and {"gdrive_id", "mime_type", "file_size"} <= payload.keys():
        indicators.append("gdrive_inventory_frontmatter")
    if "**Drive link:**" in text or "Drive link:" in text:
        indicators.append("drive_link_stub_body")
    if content_type in {"audio", "video", "image", "file"} and source_service == "gdrive":
        indicators.append(f"gdrive_{content_type}_inventory")

    text_length = len(text)
    estimated_tokens = max(0, math.ceil(text_length / 4))
    likely_metadata_stub = bool(indicators)

    return PayloadClassification(
        source_service=source_service,
        extension=extension,
        content_type=content_type,
        content_tier=content_tier,
        retrieval_eligible=retrieval_eligible,
        is_metadata_only=explicit_metadata_only or content_tier == "metadata_only",
        likely_metadata_stub=likely_metadata_stub,
        metadata_indicators=tuple(indicators),
        text_length=text_length,
        estimated_tokens=estimated_tokens,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
    )


def aggregate_classifications(items: list[PayloadClassification]) -> CorpusStats:
    """Aggregate classified payload samples into corpus statistics."""

    stats = CorpusStats(sampled_points=len(items))
    for item in items:
        stats.source_services[item.source_service] += 1
        stats.extensions[item.extension] += 1
        stats.content_types[item.content_type] += 1
        stats.content_tiers[item.content_tier] += 1
        stats.retrieval_eligible[str(item.retrieval_eligible)] += 1
        stats.metadata_only_count += int(item.is_metadata_only)
        stats.likely_metadata_stub_count += int(item.likely_metadata_stub)
        stats.text_lengths.append(item.text_length)
        stats.estimated_tokens.append(item.estimated_tokens)
        stats.metadata_indicators.update(item.metadata_indicators)
        if item.chunk_index is None:
            stats.missing_chunk_index += 1
        if item.chunk_count is None:
            stats.missing_chunk_count += 1
        if (
            item.chunk_index is not None
            and item.chunk_count is not None
            and not 0 <= item.chunk_index < item.chunk_count
        ):
            stats.chunk_index_out_of_range += 1
    return stats


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100) * len(ordered)) - 1))
    return ordered[idx]


def _distribution(counter: Counter[str], limit: int | None = None) -> dict[str, int]:
    items = counter.most_common(limit)
    return {key: count for key, count in items}


def _length_summary(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {
            "min": None,
            "median": None,
            "avg": None,
            "p90": None,
            "p95": None,
            "max": None,
        }
    return {
        "min": min(values),
        "median": statistics.median(values),
        "avg": round(statistics.fmean(values), 2),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "max": max(values),
    }


def stats_to_dict(stats: CorpusStats) -> dict[str, Any]:
    sample_count = stats.sampled_points
    metadata_rate = (
        round(stats.likely_metadata_stub_count / sample_count, 4) if sample_count else None
    )
    return {
        "sampled_points": sample_count,
        "source_service_distribution": _distribution(stats.source_services),
        "extension_distribution": _distribution(stats.extensions),
        "content_type_distribution": _distribution(stats.content_types),
        "content_tier_distribution": _distribution(stats.content_tiers),
        "retrieval_eligible_distribution": _distribution(stats.retrieval_eligible),
        "metadata_only_count": stats.metadata_only_count,
        "likely_metadata_stub_count": stats.likely_metadata_stub_count,
        "likely_metadata_contamination_rate": metadata_rate,
        "metadata_stub_indicators": _distribution(stats.metadata_indicators),
        "text_length": _length_summary(stats.text_lengths),
        "estimated_token_length": _length_summary(stats.estimated_tokens),
        "chunk_health": {
            "missing_chunk_index": stats.missing_chunk_index,
            "missing_chunk_count": stats.missing_chunk_count,
            "chunk_index_out_of_range": stats.chunk_index_out_of_range,
        },
    }


def _get_attr(obj: Any, path: tuple[str, ...]) -> Any:
    current = obj
    for part in path:
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _vector_size(collection_info: Any) -> int | dict[str, int] | None:
    vectors = _get_attr(collection_info, ("config", "params", "vectors"))
    if vectors is None:
        return None
    size = getattr(vectors, "size", None)
    if isinstance(size, int):
        return size
    if isinstance(vectors, dict):
        sizes: dict[str, int] = {}
        for name, params in vectors.items():
            named_size = getattr(params, "size", None)
            if named_size is None and isinstance(params, dict):
                named_size = params.get("size")
            if isinstance(named_size, int):
                sizes[str(name)] = named_size
        return sizes or None
    return None


def _point_payload(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None)
    return payload if isinstance(payload, dict) else {}


def collect_payload_sample(client: Any, collection: str, sample_size: int) -> list[dict[str, Any]]:
    """Scroll a read-only payload sample from Qdrant."""

    payloads: list[dict[str, Any]] = []
    offset = None
    while len(payloads) < sample_size:
        batch_size = min(256, sample_size - len(payloads))
        points, offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        payloads.extend(_point_payload(point) for point in points)
        if not offset or not points:
            break
    return payloads


def _read_queries(paths: list[Path], inline: list[str]) -> list[str]:
    queries: list[str] = [q.strip() for q in inline if q.strip()]
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                queries.append(stripped)
    return queries


def _embed_query(query: str, *, model: str, ollama_url: str) -> list[float]:
    import ollama

    client = ollama.Client(host=ollama_url)
    result = client.embed(model=model, input=[f"search_query: {query}"])
    return result["embeddings"][0]


def run_query_smoke(
    client: Any,
    collection: str,
    queries: list[str],
    *,
    limit: int,
    model: str,
    ollama_url: str,
) -> list[dict[str, Any]]:
    """Run optional top-N semantic search smoke queries."""

    smoke: list[dict[str, Any]] = []
    for query in queries:
        entry: dict[str, Any] = {"query": query, "limit": limit, "hits": []}
        try:
            vector = _embed_query(query, model=model, ollama_url=ollama_url)
            results = client.query_points(collection, query=vector, limit=limit)
            for point in getattr(results, "points", []):
                payload = _point_payload(point)
                cls = classify_payload(payload)
                entry["hits"].append(
                    {
                        "score": getattr(point, "score", None),
                        "source": payload.get("source"),
                        "source_service": cls.source_service,
                        "content_tier": cls.content_tier,
                        "retrieval_eligible": cls.retrieval_eligible,
                        "likely_metadata_stub": cls.likely_metadata_stub,
                        "text_length": cls.text_length,
                    }
                )
        except Exception as exc:
            entry["error"] = str(exc)
        smoke.append(entry)
    return smoke


def build_report(
    *,
    collection: str,
    sample_size: int,
    qdrant_url: str,
    queries: list[str],
    query_limit: int,
    embedding_model: str,
    ollama_url: str,
) -> dict[str, Any]:
    """Build a read-only RAG baseline report."""

    generated_at = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "generated_at": generated_at,
        "collection": collection,
        "sample_size_requested": sample_size,
        "qdrant_url": qdrant_url,
        "read_only": True,
        "qdrant_available": False,
        "collection_point_count": None,
        "vector_size": None,
        "payload_schema_keys": [],
        "sample": stats_to_dict(CorpusStats()),
        "query_smoke": [],
        "errors": [],
    }

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=qdrant_url)
        collection_info = client.get_collection(collection)
        report["qdrant_available"] = True
        report["collection_point_count"] = getattr(collection_info, "points_count", None)
        report["vector_size"] = _vector_size(collection_info)
        payloads = collect_payload_sample(client, collection, sample_size)
    except Exception as exc:
        report["errors"].append(f"qdrant_unavailable: {exc}")
        return report

    schema_keys = sorted({key for payload in payloads for key in payload})
    classifications = [classify_payload(payload) for payload in payloads]
    report["payload_schema_keys"] = schema_keys
    report["sample"] = stats_to_dict(aggregate_classifications(classifications))
    if queries:
        report["query_smoke"] = run_query_smoke(
            client,
            collection,
            queries,
            limit=query_limit,
            model=embedding_model,
            ollama_url=ollama_url,
        )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render a human-readable baseline report."""

    sample = report.get("sample", {})
    lines = [
        "# RAG Baseline Report",
        "",
        "Read-only baseline. Run this before reindexing, changing embeddings, "
        "changing chunking, or migrating the `documents` collection.",
        "",
        f"- Generated: `{report.get('generated_at')}`",
        f"- Collection: `{report.get('collection')}`",
        f"- Qdrant available: `{report.get('qdrant_available')}`",
        f"- Point count: `{report.get('collection_point_count')}`",
        f"- Vector size: `{report.get('vector_size')}`",
        f"- Requested sample size: `{report.get('sample_size_requested')}`",
        f"- Sampled points: `{sample.get('sampled_points')}`",
        "",
        "## Metadata Contamination",
        "",
        f"- Metadata-only count: `{sample.get('metadata_only_count')}`",
        f"- Likely metadata stub count: `{sample.get('likely_metadata_stub_count')}`",
        f"- Likely contamination rate: `{sample.get('likely_metadata_contamination_rate')}`",
        "",
        "## Distributions",
        "",
    ]

    for heading, key in [
        ("Source services", "source_service_distribution"),
        ("Extensions", "extension_distribution"),
        ("Content types", "content_type_distribution"),
        ("Content tiers", "content_tier_distribution"),
        ("Retrieval eligibility", "retrieval_eligible_distribution"),
        ("Metadata indicators", "metadata_stub_indicators"),
    ]:
        lines.append(f"### {heading}")
        dist = sample.get(key) or {}
        if not dist:
            lines.append("- (none)")
        else:
            for name, count in dist.items():
                lines.append(f"- `{name}`: {count}")
        lines.append("")

    lines.extend(
        [
            "## Lengths",
            "",
            f"- Text length: `{sample.get('text_length')}`",
            f"- Estimated token length: `{sample.get('estimated_token_length')}`",
            "",
            "## Chunk Health",
            "",
        ]
    )
    for key, value in (sample.get("chunk_health") or {}).items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Payload Schema Keys", ""])
    keys = report.get("payload_schema_keys") or []
    lines.append(", ".join(f"`{key}`" for key in keys) if keys else "(none sampled)")

    errors = report.get("errors") or []
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- `{error}`" for error in errors)

    query_smoke = report.get("query_smoke") or []
    if query_smoke:
        lines.extend(["", "## Query Smoke", ""])
        for entry in query_smoke:
            lines.append(f"### `{entry.get('query')}`")
            if entry.get("error"):
                lines.append(f"- error: `{entry['error']}`")
                lines.append("")
                continue
            hits = entry.get("hits") or []
            if not hits:
                lines.append("- no hits")
            for hit in hits:
                lines.append(
                    "- score={score} source=`{source}` service=`{service}` "
                    "metadata_stub=`{stub}` text_length=`{text_length}`".format(
                        score=hit.get("score"),
                        source=hit.get("source"),
                        service=hit.get("source_service"),
                        stub=hit.get("likely_metadata_stub"),
                        text_length=hit.get("text_length"),
                    )
                )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _resolve_outputs(output: Path | None) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    default_name = f"rag-baseline-{timestamp}"
    if output is None:
        out_dir = Path("reports")
        return out_dir / f"{default_name}.json", out_dir / f"{default_name}.md"
    if output.suffix.lower() in {".json", ".md"}:
        stem = output.with_suffix("")
        return stem.with_suffix(".json"), stem.with_suffix(".md")
    return output / f"{default_name}.json", output / f"{default_name}.md"


def write_reports(report: dict[str, Any], output: Path | None) -> tuple[Path, Path]:
    json_path, markdown_path = _resolve_outputs(output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory or .json/.md path. Both JSON and Markdown are emitted.",
    )
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument("--query", action="append", default=[], help="Optional smoke query.")
    parser.add_argument(
        "--queries-file",
        action="append",
        type=Path,
        default=[],
        help="Optional newline-delimited smoke query file.",
    )
    parser.add_argument("--query-limit", type=int, default=DEFAULT_QUERY_LIMIT)
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))
    parser.add_argument("--json", action="store_true", help="Also print JSON report to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.monotonic()
    queries = _read_queries(args.queries_file, args.query)
    report = build_report(
        collection=args.collection,
        sample_size=args.sample_size,
        qdrant_url=args.qdrant_url,
        queries=queries,
        query_limit=args.query_limit,
        embedding_model=args.embedding_model,
        ollama_url=args.ollama_url,
    )
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    json_path, markdown_path = write_reports(report, args.output)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"wrote JSON: {json_path}")
        print(f"wrote Markdown: {markdown_path}")
        if report.get("errors"):
            print("errors:", "; ".join(report["errors"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
