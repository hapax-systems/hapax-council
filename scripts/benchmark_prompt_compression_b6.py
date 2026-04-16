#!/usr/bin/env python3
"""B6 — Prompt compression Phase 2 A/B benchmark on current hardware.

Measures the latency impact of Phase 1.1 (system prompt tool directory stripping)
on Qwen3.5-9B EXL3 5.0bpw served by TabbyAPI. Conditions A and B from
``docs/superpowers/specs/2026-04-10-prompt-compression-research-plan-design.md`` §4.2.
Conditions C and D require Hermes 3 70B and stay deferred until B5 hardware arrives.

Hits TabbyAPI directly at http://localhost:5000 to isolate model latency from
the LiteLLM gateway hop. Uses TabbyAPI's per-response ``usage`` block which
already reports ``prompt_time``, ``completion_time``, and ``total_time`` — no
streaming instrumentation required.

Run order: warm-up + measurements for condition A as a contiguous block, then
condition B as a contiguous block. This is the production-relevant case
(stable system prompt across many turns, prefix cache warm). Alternating A/B
would force cache thrashing on every call and is not representative.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from agents.hapax_daimonion.persona import system_prompt

TABBY_URL = "http://localhost:5000/v1/chat/completions"
MODEL = "Qwen3.5-9B-exl3-5.00bpw"
DEFAULT_POLICY = " Mode: focused. Be concise."

# 20 representative short voice utterances spanning typical conversation
# categories. The exact wording matters less than the count and diversity —
# both conditions see the identical user message, so the only delta is the
# system prompt.
UTTERANCES = [
    # Activation / acknowledgement
    "hey hapax",
    "you there",
    "hapax good morning",
    "thanks",
    # Status / time
    "what time is it",
    "what's on my schedule today",
    "any new emails this morning",
    "what's the weather doing",
    # Actions
    "text emma I'm running late",
    "find my phone and ring it",
    "open the studio app",
    "lock my phone",
    # Search / lookup
    "search my emails for the studio contract",
    "find that note about the new mic preset",
    "what was the last thing I asked you",
    "who emailed me yesterday",
    # System / governance
    "what's the system status",
    "check governance health",
    "any nudges I should look at",
    "summarize today's briefing",
]


def build_messages(condition: str, utterance: str) -> list[dict[str, str]]:
    if condition == "A":
        sys_prompt = system_prompt(tool_recruitment_active=False, policy_block=DEFAULT_POLICY)
    elif condition == "B":
        sys_prompt = system_prompt(tool_recruitment_active=True, policy_block=DEFAULT_POLICY)
    else:
        raise ValueError(f"unknown condition {condition!r}")
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": utterance},
    ]


def call_tabby(
    client: httpx.Client, condition: str, utterance: str, max_tokens: int
) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": build_messages(condition, utterance),
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }
    t0 = time.perf_counter()
    response = client.post(TABBY_URL, json=payload, timeout=60.0)
    wall = time.perf_counter() - t0
    response.raise_for_status()
    body = response.json()
    usage = body.get("usage") or {}
    choice = (body.get("choices") or [{}])[0]
    return {
        "condition": condition,
        "utterance": utterance,
        "wall_time": wall,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_time": usage.get("prompt_time"),
        "completion_time": usage.get("completion_time"),
        "total_time": usage.get("total_time"),
        "prompt_tokens_per_sec": usage.get("prompt_tokens_per_sec"),
        "completion_tokens_per_sec": usage.get("completion_tokens_per_sec"),
        "finish_reason": choice.get("finish_reason"),
    }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def stats(values: list[float | None]) -> dict[str, float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return {}
    return {
        "n": len(clean),
        "min": min(clean),
        "median": statistics.median(clean),
        "mean": statistics.fmean(clean),
        "p95": percentile(clean, 0.95),
        "p99": percentile(clean, 0.99),
        "max": max(clean),
    }


def aggregate(records: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    rows = [r for r in records if r["condition"] == condition]
    if not rows:
        return {}
    return {
        "condition": condition,
        "n": len(rows),
        "prompt_tokens": stats([r["prompt_tokens"] for r in rows]),
        "completion_tokens": stats([r["completion_tokens"] for r in rows]),
        "prompt_time": stats([r["prompt_time"] for r in rows]),
        "completion_time": stats([r["completion_time"] for r in rows]),
        "total_time": stats([r["total_time"] for r in rows]),
        "wall_time": stats([r["wall_time"] for r in rows]),
    }


def run_block(
    client: httpx.Client,
    condition: str,
    trials: int,
    warmup: int,
    max_tokens: int,
    log: bool,
) -> list[dict[str, Any]]:
    if log:
        print(f"\n=== block {condition} (warmup={warmup}, trials={trials}) ===", file=sys.stderr)
    for i in range(warmup):
        u = UTTERANCES[i % len(UTTERANCES)]
        if log:
            print(f"  warmup {condition} {i + 1}/{warmup}: {u!r}", file=sys.stderr)
        call_tabby(client, condition, u, max_tokens)
    out: list[dict[str, Any]] = []
    for i in range(trials):
        u = UTTERANCES[i % len(UTTERANCES)]
        rec = call_tabby(client, condition, u, max_tokens)
        out.append(rec)
        if log:
            pt = rec["prompt_tokens"]
            tt = rec["total_time"]
            print(
                f"  trial {condition} {i + 1}/{trials}: tok={pt} total={tt:.3f}s", file=sys.stderr
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20, help="Trials per condition")
    parser.add_argument(
        "--warmup", type=int, default=3, help="Warmup calls per condition (discarded)"
    )
    parser.add_argument("--max-tokens", type=int, default=80)
    parser.add_argument("--out-dir", default="~/hapax-state/benchmarks/prompt-compression")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    log = not args.quiet
    if log:
        print(f"benchmark: {args.trials} trials/condition, {args.warmup} warmups", file=sys.stderr)
        print(f"target: {TABBY_URL} model={MODEL}", file=sys.stderr)

    records: list[dict[str, Any]] = []
    with httpx.Client() as client:
        records.extend(run_block(client, "A", args.trials, args.warmup, args.max_tokens, log))
        records.extend(run_block(client, "B", args.trials, args.warmup, args.max_tokens, log))

    aggregated = {
        "model": MODEL,
        "endpoint": TABBY_URL,
        "trials_per_condition": args.trials,
        "warmups_per_condition": args.warmup,
        "max_tokens": args.max_tokens,
        "captured_at": datetime.now(UTC).isoformat(),
        "policy_block": DEFAULT_POLICY,
        "block_order": ["A", "B"],
        "conditions": {
            "A": aggregate(records, "A"),
            "B": aggregate(records, "B"),
        },
        "raw": records,
    }

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"phase2-ab-{timestamp}.json"
    out_path.write_text(json.dumps(aggregated, indent=2))
    if log:
        print(f"\nresults: {out_path}", file=sys.stderr)

    a = aggregated["conditions"]["A"]
    b = aggregated["conditions"]["B"]
    if a and b:
        print()
        print("                    Condition A (full)  Condition B (compressed)  Δ")
        print(
            f"prompt tok median   {a['prompt_tokens']['median']:>14.0f}  {b['prompt_tokens']['median']:>23.0f}  {b['prompt_tokens']['median'] - a['prompt_tokens']['median']:+.0f}"
        )
        print(
            f"prompt time p50     {a['prompt_time']['median']:>13.4f}s {b['prompt_time']['median']:>22.4f}s  {(b['prompt_time']['median'] - a['prompt_time']['median']) * 1000:+.1f}ms"
        )
        print(
            f"prompt time p95     {a['prompt_time']['p95']:>13.4f}s {b['prompt_time']['p95']:>22.4f}s  {(b['prompt_time']['p95'] - a['prompt_time']['p95']) * 1000:+.1f}ms"
        )
        print(
            f"total time p50      {a['total_time']['median']:>13.4f}s {b['total_time']['median']:>22.4f}s  {(b['total_time']['median'] - a['total_time']['median']) * 1000:+.1f}ms"
        )
        print(
            f"total time p95      {a['total_time']['p95']:>13.4f}s {b['total_time']['p95']:>22.4f}s  {(b['total_time']['p95'] - a['total_time']['p95']) * 1000:+.1f}ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
