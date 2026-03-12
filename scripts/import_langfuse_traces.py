#!/usr/bin/env python3
"""Import JSONL trace files (from CI) into local Langfuse.

Usage::

    uv run python scripts/import_langfuse_traces.py /tmp/langfuse-traces.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def import_traces(trace_file: Path) -> int:
    """Read JSONL spans and POST them to Langfuse. Returns count imported."""
    try:
        import httpx
    except ImportError:
        print("httpx is required: uv pip install httpx", file=sys.stderr)
        return 0

    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not public_key or not secret_key:
        print(
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY env vars.",
            file=sys.stderr,
        )
        return 0

    lines = trace_file.read_text().strip().splitlines()
    count = 0

    with httpx.Client(
        base_url=host,
        auth=(public_key, secret_key),
        timeout=30,
    ) as client:
        for line in lines:
            span = json.loads(line)
            # Map our TraceSpan fields to Langfuse ingestion API.
            payload = {
                "batch": [
                    {
                        "id": span.get("span_id", ""),
                        "type": "span-create",
                        "body": {
                            "traceId": span.get("trace_id", ""),
                            "name": span.get("name", ""),
                            "startTime": span.get("start_time", 0),
                            "endTime": span.get("end_time", 0),
                            "model": span.get("model", ""),
                            "input": span.get("input_text", ""),
                            "output": span.get("output_text", ""),
                            "metadata": span.get("metadata", {}),
                        },
                    }
                ]
            }
            try:
                resp = client.post("/api/public/ingestion", json=payload)
                if resp.status_code < 300:
                    count += 1
                else:
                    print(f"Failed to import span: {resp.status_code}", file=sys.stderr)
            except httpx.HTTPError as e:
                print(f"HTTP error: {e}", file=sys.stderr)

    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Langfuse traces from JSONL")
    parser.add_argument("trace_file", type=Path)
    args = parser.parse_args()

    if not args.trace_file.exists():
        print(f"File not found: {args.trace_file}", file=sys.stderr)
        sys.exit(1)

    count = import_traces(args.trace_file)
    print(f"Imported {count} spans from {args.trace_file}")


if __name__ == "__main__":
    main()
