#!/usr/bin/env python3
"""Safe shadow path for rebuilding the RAG documents collection.

This script keeps destructive migration work away from the live `documents`
collection. It can create a `documents_v2` schema, plan or run a capped
reindex into that shadow collection, and compare retrieval results side by side.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_COLLECTION = "documents"
DEFAULT_SHADOW_COLLECTION = "documents_v2"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-cpu"
DEFAULT_GOLDEN_SUITE = Path("evals/rag/golden_queries.json")
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".pptx", ".html", ".md", ".txt", ".py")
TEXT_COVERAGE_EXTENSIONS = {".html", ".md", ".py", ".txt"}


def _hapax_home() -> Path:
    return Path(os.environ.get("HAPAX_HOME", str(Path.home())))


def _repo_root() -> Path:
    return Path(os.environ.get("HAPAX_REPO_ROOT", str(Path(__file__).resolve().parents[1])))


def _personal_root() -> Path:
    return Path(os.environ.get("HAPAX_PERSONAL_ROOT", str(Path.home() / "Documents" / "Personal")))


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def default_source_dirs() -> list[Path]:
    home = _hapax_home()
    repo = _repo_root()
    personal = _personal_root()
    research = personal / "20-projects" / "hapax-research"
    cc_tasks = personal / "20-projects" / "hapax-cc-tasks"
    requests = personal / "20-projects" / "hapax-requests"
    return _dedupe_paths(
        [
            home / "documents" / "rag-sources",
            research / "audit",
            research / "codex-handoffs",
            research / "foundations",
            research / "lab-journals",
            research / "ledgers",
            research / "exposition",
            requests / "active",
            requests / "closed",
            cc_tasks / "active",
            cc_tasks / "closed",
            repo / "README.md",
            repo / "docs",
            repo / "scripts",
            repo / "agents",
            repo / "shared",
            repo / "packages" / "agentgov",
        ]
    )


def classify_source_path(path: Path) -> str:
    normalized = str(path)
    categories = [
        ("/hapax-research/audit/", "audit"),
        ("/hapax-research/codex-handoffs/", "handoff"),
        ("/hapax-research/foundations/", "foundation"),
        ("/hapax-research/lab-journals/", "lab_journal"),
        ("/hapax-research/ledgers/", "ledger"),
        ("/hapax-research/exposition/", "exposition"),
        ("/hapax-requests/active/", "request"),
        ("/hapax-requests/closed/", "request"),
        ("/hapax-cc-tasks/active/", "cc_task"),
        ("/hapax-cc-tasks/closed/", "cc_task"),
        ("/documents/rag-sources/", "rag_source"),
        ("/packages/agentgov/", "agentgov"),
        ("/docs/", "repo_docs"),
        ("/scripts/", "repo_scripts"),
        ("/agents/", "repo_agents"),
        ("/shared/", "repo_shared"),
    ]
    for needle, category in categories:
        if needle in normalized:
            return category
    if path.name == "README.md":
        return "repo_docs"
    return "other"


def source_category_counts(files: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for file in files:
        category = classify_source_path(file)
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def discover_source_files(
    source_dirs: list[Path],
    *,
    supported_extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> list[Path]:
    files: list[Path] = []
    supported = {ext.lower() for ext in supported_extensions}
    for directory in source_dirs:
        if not directory.exists():
            continue
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in supported
        )
    return sorted(files)


def _load_golden_suite(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _label_key(label: dict[str, Any]) -> str:
    parts = []
    for key, value in sorted(label.items()):
        if key == "grade":
            continue
        parts.append(f"{key}={value}")
    return "|".join(parts)


def _golden_labels(suite: dict[str, Any]) -> list[dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for query in suite.get("queries", []):
        if not isinstance(query, dict):
            continue
        for label in query.get("expected_sources", []) or []:
            if not isinstance(label, dict):
                continue
            key = _label_key(label)
            if key:
                labels.setdefault(key, {k: v for k, v in label.items() if k != "grade"})
    return [labels[key] for key in sorted(labels)]


def _safe_read_text(path: Path, *, max_bytes: int = 2_000_000) -> str:
    if path.suffix.lower() not in TEXT_COVERAGE_EXTENSIONS:
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[:max_bytes].decode("utf-8", errors="replace")


def _contains(haystack: str, needle: object) -> bool:
    return str(needle).lower() in haystack.lower()


def _label_matches_file(label: dict[str, Any], path: Path, text: str) -> bool:
    checks: list[bool] = []
    if "source_contains" in label:
        checks.append(_contains(str(path), label["source_contains"]))
    if "text_contains" in label:
        checks.append(_contains(text, label["text_contains"]))
    return bool(checks) and all(checks)


def _source_label_has_text_evidence(label: dict[str, Any], text: str) -> bool:
    return "source_contains" in label and _contains(text, label["source_contains"])


def golden_label_coverage(files: list[Path], suite_path: Path) -> dict[str, Any]:
    if not suite_path.exists():
        return {
            "available": False,
            "suite_path": str(suite_path),
            "error": "suite_not_found",
        }
    try:
        labels = _golden_labels(_load_golden_suite(suite_path))
    except Exception as exc:
        return {
            "available": False,
            "suite_path": str(suite_path),
            "error": str(exc),
        }

    texts = {file: _safe_read_text(file) for file in files}
    covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    text_evidence_for_source_labels: list[dict[str, Any]] = []
    for label in labels:
        matches = [
            str(file) for file in files if _label_matches_file(label, file, texts.get(file, ""))
        ]
        record = {"label": label, "matched_files": matches[:10], "match_count": len(matches)}
        if matches:
            covered.append(record)
            continue
        uncovered.append(record)
        text_matches = [
            str(file)
            for file in files
            if _source_label_has_text_evidence(label, texts.get(file, ""))
        ]
        if text_matches:
            text_evidence_for_source_labels.append(
                {
                    "label": label,
                    "matched_files": text_matches[:10],
                    "match_count": len(text_matches),
                }
            )

    denominator = len(labels)
    numerator = len(covered)
    source_labels = [label for label in labels if "source_contains" in label]
    covered_source_labels = [item for item in covered if "source_contains" in item["label"]]
    return {
        "available": True,
        "suite_path": str(suite_path),
        "expected_label_count": denominator,
        "covered_label_count": numerator,
        "coverage_rate": round(numerator / denominator, 4) if denominator else None,
        "source_contains_label_count": len(source_labels),
        "covered_source_contains_label_count": len(covered_source_labels),
        "source_contains_coverage_rate": (
            round(len(covered_source_labels) / len(source_labels), 4) if source_labels else None
        ),
        "covered_labels": covered,
        "uncovered_labels": uncovered,
        "source_label_text_evidence": text_evidence_for_source_labels,
    }


def build_reindex_report(
    *,
    source_dirs: list[Path],
    source_collection: str,
    target_collection: str,
    max_files: int | None,
    dry_run: bool,
    report_only: bool,
    force: bool,
    qdrant_url: str,
    embedding_model: str,
    suite_path: Path | None = None,
) -> dict[str, Any]:
    files = discover_source_files(source_dirs)
    selected = files[:max_files] if max_files is not None else files
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": "rag_documents_v2_reindex",
        "source_collection": source_collection,
        "target_collection": target_collection,
        "source_dirs": [str(path) for path in source_dirs],
        "qdrant_url": qdrant_url,
        "embedding_model": embedding_model,
        "force": force,
        "dry_run": dry_run,
        "report_only": report_only,
        "writes_enabled": not dry_run and not report_only,
        "files_discovered": len(files),
        "max_files": max_files,
        "files_selected": len(selected),
        "selected_files": [str(path) for path in selected],
        "discovered_source_categories": source_category_counts(files),
        "selected_source_categories": source_category_counts(selected),
    }
    if suite_path is not None:
        report["golden_label_coverage"] = golden_label_coverage(selected, suite_path)
    return report


def _get_attr(obj: Any, path: tuple[str, ...]) -> Any:
    current = obj
    for part in path:
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def vector_size_from_collection_info(collection_info: Any) -> int | dict[str, int] | None:
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


def _collection_exists(client: Any, collection: str) -> bool:
    collections = client.get_collections().collections
    return any(getattr(item, "name", None) == collection for item in collections)


def ensure_collection(client: Any, collection: str, vector_size: int) -> bool:
    """Create a cosine-vector collection if missing."""
    if _collection_exists(client, collection):
        return False

    from qdrant_client.models import Distance, VectorParams

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    return True


def embedding_dimensions(*, model: str, ollama_url: str) -> int:
    import ollama

    client = ollama.Client(host=ollama_url)
    result = client.embed(model=model, input=["search_document: hapax rag shadow schema probe"])
    return len(result["embeddings"][0])


def _make_qdrant_client(qdrant_url: str) -> Any:
    from qdrant_client import QdrantClient

    return QdrantClient(url=qdrant_url)


def collection_report(client: Any, collection: str) -> dict[str, Any]:
    try:
        info = client.get_collection(collection)
    except Exception as exc:
        return {"collection": collection, "available": False, "error": str(exc)}
    return {
        "collection": collection,
        "available": True,
        "points_count": getattr(info, "points_count", None),
        "vectors_count": getattr(info, "vectors_count", None),
        "vector_size": vector_size_from_collection_info(info),
    }


def attach_collection_reports(report: dict[str, Any], qdrant_url: str) -> None:
    try:
        client = _make_qdrant_client(qdrant_url)
    except Exception as exc:
        report["collection_reports"] = []
        report["collection_report_error"] = str(exc)
        return
    collections = [
        report["source_collection"],
        report["target_collection"],
    ]
    report["collection_reports"] = [collection_report(client, name) for name in collections]


def _run_ingest_command(
    *,
    source_dirs: list[Path],
    target_collection: str,
    qdrant_url: str,
    embedding_model: str,
    max_files: int | None,
    force: bool,
    runner=subprocess.run,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        "-m",
        "agents.ingest",
        "--bulk-only",
        "--collection",
        target_collection,
        "--qdrant-url",
        qdrant_url,
        "--embedding-model",
        embedding_model,
    ]
    for source_dir in source_dirs:
        cmd.extend(["--watch-dir", str(source_dir)])
    if max_files is not None:
        cmd.extend(["--max-files", str(max_files)])
    if force:
        cmd.append("--force")
    return runner(cmd, check=False)


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def run_ensure_schema(args: argparse.Namespace) -> int:
    vector_size = args.vector_size
    if vector_size is None:
        vector_size = embedding_dimensions(model=args.embedding_model, ollama_url=args.ollama_url)
    client = _make_qdrant_client(args.qdrant_url)
    created = ensure_collection(client, args.collection, vector_size)
    _print_json(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "collection": args.collection,
            "created": created,
            "vector_size": vector_size,
            "embedding_model": args.embedding_model,
            "qdrant_url": args.qdrant_url,
        }
    )
    return 0


def run_reindex(args: argparse.Namespace) -> int:
    source_dirs = args.source_dir or default_source_dirs()
    report = build_reindex_report(
        source_dirs=source_dirs,
        source_collection=args.source_collection,
        target_collection=args.target_collection,
        max_files=args.max_files,
        dry_run=args.dry_run,
        report_only=args.report_only,
        force=args.force,
        qdrant_url=args.qdrant_url,
        embedding_model=args.embedding_model,
        suite_path=args.suite,
    )

    if args.dry_run or args.report_only:
        attach_collection_reports(report, args.qdrant_url)
        _print_json(report)
        return 0

    vector_size = args.vector_size
    if vector_size is None:
        vector_size = embedding_dimensions(model=args.embedding_model, ollama_url=args.ollama_url)
    client = _make_qdrant_client(args.qdrant_url)
    report["schema"] = {
        "created": ensure_collection(client, args.target_collection, vector_size),
        "vector_size": vector_size,
    }
    result = _run_ingest_command(
        source_dirs=source_dirs,
        target_collection=args.target_collection,
        qdrant_url=args.qdrant_url,
        embedding_model=args.embedding_model,
        max_files=args.max_files,
        force=args.force,
    )
    report["returncode"] = result.returncode
    _print_json(report)
    return result.returncode


def _embed_query(query: str, *, model: str, ollama_url: str) -> list[float]:
    import ollama

    client = ollama.Client(host=ollama_url)
    result = client.embed(model=model, input=[f"search_query: {query}"])
    return result["embeddings"][0]


def _point_payload(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _hit_from_point(point: Any) -> dict[str, Any]:
    payload = _point_payload(point)
    text = str(payload.get("text", ""))
    return {
        "score": getattr(point, "score", None),
        "source": payload.get("source"),
        "source_service": payload.get("source_service"),
        "content_tier": payload.get("content_tier"),
        "retrieval_eligible": payload.get("retrieval_eligible"),
        "text_preview": text[:240],
    }


def compare_shadow_retrieval(
    *,
    client: Any,
    query: str,
    query_vector: list[float],
    source_collection: str,
    shadow_collection: str,
    limit: int,
) -> dict[str, Any]:
    collections: dict[str, Any] = {}
    for collection in (source_collection, shadow_collection):
        try:
            result = client.query_points(collection, query=query_vector, limit=limit)
            points = getattr(result, "points", [])
            collections[collection] = {
                "ok": True,
                "hits": [_hit_from_point(point) for point in points],
            }
        except Exception as exc:
            collections[collection] = {"ok": False, "error": str(exc), "hits": []}
    return {
        "query": query,
        "limit": limit,
        "source_collection": source_collection,
        "shadow_collection": shadow_collection,
        "collections": collections,
    }


def _read_queries(paths: list[Path], inline: list[str]) -> list[str]:
    queries = [query.strip() for query in inline if query.strip()]
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                queries.append(stripped)
    return queries


def run_compare(args: argparse.Namespace) -> int:
    queries = _read_queries(args.queries_file, args.query)
    if not queries:
        raise SystemExit("compare requires --query or --queries-file")

    client = _make_qdrant_client(args.qdrant_url)
    comparisons = []
    for query in queries:
        vector = _embed_query(query, model=args.embedding_model, ollama_url=args.ollama_url)
        comparisons.append(
            compare_shadow_retrieval(
                client=client,
                query=query,
                query_vector=vector,
                source_collection=args.source_collection,
                shadow_collection=args.shadow_collection,
                limit=args.limit,
            )
        )
    _print_json(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "qdrant_url": args.qdrant_url,
            "embedding_model": args.embedding_model,
            "comparisons": comparisons,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_URL))

    subparsers = parser.add_subparsers(dest="command", required=True)

    schema = subparsers.add_parser("ensure-schema", help="Create documents_v2 if missing.")
    schema.add_argument("--collection", default=DEFAULT_SHADOW_COLLECTION)
    schema.add_argument("--vector-size", type=int, default=None)
    schema.set_defaults(func=run_ensure_schema)

    reindex = subparsers.add_parser("reindex", help="Plan or run shadow reindexing.")
    reindex.add_argument("--source-collection", default=DEFAULT_SOURCE_COLLECTION)
    reindex.add_argument("--target-collection", default=DEFAULT_SHADOW_COLLECTION)
    reindex.add_argument("--source-dir", action="append", type=Path, default=[])
    reindex.add_argument("--max-files", type=int, default=None)
    reindex.add_argument("--suite", type=Path, default=DEFAULT_GOLDEN_SUITE)
    reindex.add_argument("--dry-run", action="store_true")
    reindex.add_argument("--report-only", action="store_true")
    reindex.add_argument("--force", action="store_true")
    reindex.add_argument("--vector-size", type=int, default=None)
    reindex.set_defaults(func=run_reindex)

    compare = subparsers.add_parser("compare", help="Compare documents and documents_v2 retrieval.")
    compare.add_argument("--source-collection", default=DEFAULT_SOURCE_COLLECTION)
    compare.add_argument("--shadow-collection", default=DEFAULT_SHADOW_COLLECTION)
    compare.add_argument("--query", action="append", default=[])
    compare.add_argument("--queries-file", action="append", type=Path, default=[])
    compare.add_argument("--limit", type=int, default=5)
    compare.set_defaults(func=run_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
