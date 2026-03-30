#!/usr/bin/env python3
"""query.py — CLI tool for testing RAG retrieval against Qdrant.

Usage:
    python query.py "how does MIDI routing work"
    python query.py "boom bap drum patterns" --collection samples --limit 10
    python query.py --stats
"""

import argparse
import json
import os
import sys
import urllib.request

# Try shared.config first (main venv), fall back to standalone (ingest venv)
try:
    from agents._config import QDRANT_URL, embed
except ImportError:
    QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

    def embed(text: str, prefix: str = "search_query") -> list[float]:
        import ollama

        prefixed = f"{prefix}: {text}" if prefix else text
        result = ollama.embed(model="nomic-embed-text-v2-moe", input=prefixed)
        return result["embeddings"][0]


try:
    from agents import _langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

DEFAULT_COLLECTION = "documents"


def search(query_vec: list[float], collection: str, limit: int) -> list[dict]:
    data = json.dumps(
        {
            "vector": query_vec,
            "limit": limit,
            "with_payload": True,
        }
    ).encode()
    req = urllib.request.Request(
        f"{QDRANT_URL}/collections/{collection}/points/search",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode())
    return result.get("result", [])


def collection_stats(collection: str) -> dict:
    req = urllib.request.Request(f"{QDRANT_URL}/collections/{collection}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read().decode())
    return result.get("result", {})


def all_collections() -> list[str]:
    req = urllib.request.Request(f"{QDRANT_URL}/collections")
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read().decode())
    return [c["name"] for c in result.get("result", {}).get("collections", [])]


def main():
    parser = argparse.ArgumentParser(description="Query RAG knowledge base")
    parser.add_argument("query", nargs="?", help="Search query text")
    parser.add_argument("-c", "--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("-n", "--limit", type=int, default=5)
    parser.add_argument("--stats", action="store_true", help="Show collection statistics")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.stats:
        collections = all_collections()
        for name in collections:
            stats = collection_stats(name)
            points = stats.get("points_count", 0)
            stats.get("vectors_count", 0)
            status = stats.get("status", "unknown")
            print(f"  {name:20s}  {points:>8,} points  status={status}")
        return

    if not args.query:
        parser.print_help()
        sys.exit(1)

    # Embed query
    print(f"Query: {args.query}", file=sys.stderr)
    print(f"Collection: {args.collection}, Limit: {args.limit}", file=sys.stderr)
    print(file=sys.stderr)

    with _tracer.start_as_current_span(
        "query.search",
        attributes={"agent.name": "query", "agent.repo": "hapax-council"},
    ):
        vec = embed(args.query, prefix="search_query")
        results = search(vec, args.collection, args.limit)

        if args.json:
            print(json.dumps(results, indent=2))
            return

        if not results:
            print("No results found.")
            return

        for i, r in enumerate(results, 1):
            score = r.get("score", 0)
            payload = r.get("payload", {})
            filename = payload.get("filename", "?")
            text = payload.get("text", "")
            chunk_idx = payload.get("chunk_index", "?")
            chunk_count = payload.get("chunk_count", "?")

            print(
                f"─── Result {i} ─── score={score:.4f} ── {filename} (chunk {chunk_idx}/{chunk_count})"
            )
            # Truncate long text for display
            if len(text) > 500:
                print(f"{text[:500]}...")
            else:
                print(text)
            print()


if __name__ == "__main__":
    main()
