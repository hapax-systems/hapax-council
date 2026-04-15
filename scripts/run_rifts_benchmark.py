#!/usr/bin/env python3
"""RIFTS benchmark harness — runs microsoft/rifts prompts against a LiteLLM model route.

Per delta's nightly queue Item #10 (2026-04-15T07:55Z). Captures per-prompt
model outputs + latency. Does NOT compute the RIFTS accuracy score (requires
the RIFTS labeler; deferred to a follow-up step).

Dataset: microsoft/rifts on Hugging Face (~1740 prompts, ambiguous vs
non-ambiguous split). Per Shaikh et al. ACL 2025, frontier models average
23.23% on RIFTS, with a stark 96% / 2.22% asymmetry between non-ambiguous
and ambiguous splits.

Usage::

    # Dry run — no inference, no download, uses inline fixture (5 prompts)
    python scripts/run_rifts_benchmark.py --dry-run --model local-fast

    # Real run — requires dataset already on disk (operator-triggered per
    # nightly queue Item #11)
    python scripts/run_rifts_benchmark.py \\
        --model local-fast \\
        --dataset-path research/benchmarks/rifts/microsoft_rifts \\
        --output research/benchmarks/rifts/results-local-fast-20260415.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

RIFTS_DATASET_NAME = "microsoft/rifts"
DEFAULT_LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
DEFAULT_MAX_TOKENS = 256
DEFAULT_TIMEOUT_S = 60.0


# Inline fixture — 5 example prompts for --dry-run. These are beta's synthetic
# reconstructions of what RIFTS-style prompts look like, NOT the actual
# dataset content. The actual dataset is loaded via --dataset-path for real
# runs.
DRY_RUN_FIXTURE: list[dict[str, object]] = [
    {
        "id": "fixture-000",
        "prompt": "help me with my thing",
        "ambiguous": True,  # no object, no verb; clarification needed
        "note": "canonical ambiguous prompt — model should ask 'what thing?'",
    },
    {
        "id": "fixture-001",
        "prompt": "summarize this for me",
        "ambiguous": True,  # 'this' has no referent
        "note": "referential ambiguity",
    },
    {
        "id": "fixture-002",
        "prompt": "what is 2+2",
        "ambiguous": False,  # clear, self-contained
        "note": "canonical non-ambiguous — model should answer directly",
    },
    {
        "id": "fixture-003",
        "prompt": "book a flight to Paris for tomorrow",
        "ambiguous": True,  # missing departure, time of day, passenger info, etc.
        "note": "task ambiguity — multiple missing parameters",
    },
    {
        "id": "fixture-004",
        "prompt": "list the planets in our solar system",
        "ambiguous": False,  # clear, factual
        "note": "canonical non-ambiguous — factual retrieval",
    },
]


@dataclass
class RunResult:
    prompt_id: str
    ambiguous: bool
    prompt_text: str
    model: str
    response: str
    latency_ms: float
    tokens_in: int | None
    tokens_out: int | None
    error: str | None
    timestamp: str


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RIFTS benchmark harness (beta 2026-04-15 Item #10 deliverable)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default="local-fast",
        help="LiteLLM route name (default: local-fast — Qwen3.5-9B via TabbyAPI)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use inline fixture (5 prompts); no external downloads, no inference calls",
    )
    parser.add_argument(
        "--dataset-path",
        type=Path,
        help="Path to the RIFTS dataset (HuggingFace dataset dir). Required unless --dry-run",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSONL path (default: research/benchmarks/rifts/results-<model>-<timestamp>.jsonl)",
    )
    parser.add_argument(
        "--litellm-url",
        default=DEFAULT_LITELLM_URL,
        help=f"LiteLLM base URL (default: {DEFAULT_LITELLM_URL})",
    )
    parser.add_argument(
        "--litellm-key",
        default=os.environ.get("LITELLM_MASTER_KEY", ""),
        help="LiteLLM master key (default: $LITELLM_MASTER_KEY env var)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"max_tokens per completion (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap on number of prompts to run (0 = all; useful for smoke tests)",
    )
    return parser.parse_args(argv)


def _load_fixture() -> Iterator[dict[str, object]]:
    yield from DRY_RUN_FIXTURE


def _load_dataset(path: Path) -> Iterator[dict[str, object]]:
    """Load the RIFTS dataset from a local HuggingFace dataset directory.

    The RIFTS dataset schema is not 100% pinned until the real download lands.
    This loader tries multiple known conventions and raises if none match.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"dataset path {path} does not exist. Download with:\n"
            f"  huggingface-cli download {RIFTS_DATASET_NAME} --repo-type dataset "
            f"--local-dir {path}"
        )

    # Try known conventions in order:
    # 1. A JSONL file per split (e.g. data/train.jsonl)
    # 2. A Parquet file per split (datasets library default)
    # 3. A single all-in-one jsonl

    jsonl_candidates = [
        path / "data" / "train.jsonl",
        path / "train.jsonl",
        path / "data.jsonl",
        path / "rifts.jsonl",
    ]
    for candidate in jsonl_candidates:
        if candidate.exists():
            with candidate.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    yield json.loads(line)
            return

    # Parquet fallback — requires pandas/pyarrow
    parquet_candidates = list(path.rglob("*.parquet"))
    if parquet_candidates:
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError(
                "RIFTS dataset only has Parquet files and pandas is not installed. "
                "Either convert to JSONL or `uv add pandas pyarrow --dev`"
            ) from exc
        for parquet_path in sorted(parquet_candidates):
            df = pd.read_parquet(parquet_path)
            for _, row in df.iterrows():
                yield row.to_dict()
        return

    raise RuntimeError(
        f"no recognizable dataset files found under {path}. "
        f"Expected JSONL or Parquet files; got: {sorted(p.name for p in path.iterdir() if p.is_file())}"
    )


def _extract_prompt_fields(raw: dict[str, object]) -> tuple[str, str, bool]:
    """Extract (prompt_id, prompt_text, ambiguous) from a RIFTS dataset record.

    Tries known field-name conventions. The actual RIFTS schema may use
    different names; this function is the single point to update when the
    dataset is downloaded and inspected.
    """
    prompt_id = str(
        raw.get("id")
        or raw.get("prompt_id")
        or raw.get("example_id")
        or f"unknown-{hash(json.dumps(raw, sort_keys=True)) & 0xFFFF:04x}"
    )
    prompt_text = str(
        raw.get("prompt") or raw.get("prompt_text") or raw.get("input") or raw.get("user") or ""
    )
    ambiguous_raw = raw.get("ambiguous") or raw.get("requires_grounding") or raw.get("split")
    if isinstance(ambiguous_raw, bool):
        ambiguous = ambiguous_raw
    elif isinstance(ambiguous_raw, str):
        ambiguous = ambiguous_raw.lower() in ("ambiguous", "true", "1", "yes", "requires_grounding")
    else:
        ambiguous = False
    return prompt_id, prompt_text, ambiguous


def _call_litellm(
    *,
    client: httpx.Client,
    url: str,
    key: str,
    model: str,
    prompt: str,
    max_tokens: int,
) -> tuple[str, int | None, int | None, float, str | None]:
    """Call LiteLLM /v1/chat/completions. Returns (response_text, tokens_in, tokens_out, latency_ms, error)."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    t_start = time.perf_counter()
    try:
        response = client.post(
            f"{url}/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=DEFAULT_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return "", None, None, latency_ms, f"httpx error: {exc}"
    latency_ms = (time.perf_counter() - t_start) * 1000.0

    if response.status_code != 200:
        return "", None, None, latency_ms, f"HTTP {response.status_code}: {response.text[:200]}"

    try:
        data = response.json()
    except ValueError as exc:
        return "", None, None, latency_ms, f"json decode: {exc}"

    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        return "", None, None, latency_ms, f"response schema: {exc}"

    usage = data.get("usage", {}) or {}
    tokens_in = usage.get("prompt_tokens")
    tokens_out = usage.get("completion_tokens")
    return content, tokens_in, tokens_out, latency_ms, None


def _dry_run(model: str, output_path: Path | None) -> int:
    print(f"# RIFTS harness dry run — {datetime.now(UTC).isoformat()}")
    print(f"# model route: {model}")
    print(f"# planned output: {output_path or '(none — dry run)'}")
    print(f"# fixture prompts: {len(DRY_RUN_FIXTURE)}")
    print("#")
    print("# Dry run does NOT call LiteLLM and does NOT download the real dataset.")
    print("# To run the real benchmark, omit --dry-run and provide --dataset-path.")
    print("#")
    for i, item in enumerate(_load_fixture(), start=1):
        tag = "AMBIG " if item["ambiguous"] else "CLEAR "
        print(f"{i:3d}. [{tag}] {item['id']}: {item['prompt']!r:50s} (note: {item['note']})")
    print("#")
    print("# Dry run complete. No inference calls made. No files written.")
    return 0


def _real_run(args: argparse.Namespace) -> int:
    if args.dataset_path is None:
        print(
            "ERROR: --dataset-path is required for real runs. Use --dry-run for fixture-only.",
            file=sys.stderr,
        )
        return 2

    output_path = args.output or Path(
        f"research/benchmarks/rifts/results-{args.model}-"
        f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%SZ')}.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"# RIFTS harness real run — {datetime.now(UTC).isoformat()}")
    print(f"# model route: {args.model}")
    print(f"# dataset path: {args.dataset_path}")
    print(f"# output: {output_path}")
    print(f"# max_tokens: {args.max_tokens}")
    print(f"# litellm: {args.litellm_url}")
    print("#")

    count_success = 0
    count_error = 0
    count_total = 0
    with httpx.Client() as client, output_path.open("w") as out_f:
        for raw in _load_dataset(args.dataset_path):
            if args.limit and count_total >= args.limit:
                break
            count_total += 1
            prompt_id, prompt_text, ambiguous = _extract_prompt_fields(raw)
            if not prompt_text:
                count_error += 1
                continue

            response, tokens_in, tokens_out, latency_ms, error = _call_litellm(
                client=client,
                url=args.litellm_url,
                key=args.litellm_key,
                model=args.model,
                prompt=prompt_text,
                max_tokens=args.max_tokens,
            )

            result = RunResult(
                prompt_id=prompt_id,
                ambiguous=ambiguous,
                prompt_text=prompt_text,
                model=args.model,
                response=response,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=error,
                timestamp=datetime.now(UTC).isoformat(),
            )
            out_f.write(json.dumps(result.__dict__) + "\n")
            out_f.flush()

            if error:
                count_error += 1
                print(f"  [{count_total:4d}] ERROR {prompt_id}: {error[:80]}")
            else:
                count_success += 1
                if count_total % 50 == 0:
                    print(
                        f"  [{count_total:4d}] {count_success} OK, {count_error} err, "
                        f"last latency {latency_ms:.0f} ms"
                    )

    print("#")
    print(f"# Done. {count_success} OK, {count_error} err, total {count_total}")
    print(f"# Output: {output_path}")
    return 0 if count_error == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        return _dry_run(args.model, args.output)
    return _real_run(args)


if __name__ == "__main__":
    sys.exit(main())
