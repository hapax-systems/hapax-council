#!/usr/bin/env python3
"""LRR Phase 5 post-swap smoke test — run the directive compliance
benchmark + CAPABLE tier assertion + latency measurement after the
Hermes 3 substrate swap.

This is Task 13 of the Phase 5 swap procedure (the go/no-go gate).
Exits non-zero if any of:

  - Directive compliance: < 3/5 prompts produced a response that
    followed the grounding directive
  - Word limit compliance: < 4/5 prompts stayed within the
    configured word limit
  - CAPABLE tier verification: ``shared.config.MODELS["capable"]``
    no longer routes to Claude Opus
  - Latency check: sustained TTFT above the configured threshold

Exit codes::

    0  all checks passed — Phase 5 swap gate passed
    1  argparse / environment error
    2  directive compliance failure (< 3/5)
    3  word-limit compliance failure (< 4/5)
    4  CAPABLE tier verification failure
    5  latency threshold exceeded
    6  LiteLLM gateway unreachable / benchmark invocation failed

Usage::

    scripts/phase-5-post-swap-smoke.py                          # full run
    scripts/phase-5-post-swap-smoke.py --capable-check          # CAPABLE only
    scripts/phase-5-post-swap-smoke.py --benchmark              # directive only
    scripts/phase-5-post-swap-smoke.py --latency-threshold-ms 1500
    scripts/phase-5-post-swap-smoke.py --json                   # machine output
    scripts/phase-5-post-swap-smoke.py --dry-run                # no live LLM calls

Benchmark design:

The directive compliance benchmark uses 5 canned prompts that are
designed to stress-test specific grounding behaviors. Each prompt has
an expected directive (e.g., "rephrase", "elaborate") and a word
limit. The model's response is graded on:

  1. Directive adherence: does the response actually rephrase /
     elaborate / advance as instructed?
  2. Word limit adherence: is the response within N+20% of the
     configured limit?

The grading is LLM-as-judge (Claude Opus via LiteLLM's ``capable``
alias). This gives a stable reference grader independent of the
system-under-test. The judge LLM is itself CAPABLE-tier and NOT the
Hermes 3 Hermes 3 under test.

Both checks are soft gates — they indicate directive compliance for
Condition A' as a whole, not for any individual prompt. The Phase 5
exit criterion is >= 3/5 directive + >= 4/5 word limit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field

DEFAULT_LITELLM_URL = "http://localhost:4000"
DEFAULT_HERMES_MODEL = "local-fast"  # LiteLLM alias that should point at Hermes 3
DEFAULT_JUDGE_MODEL = "capable"  # LiteLLM alias for Claude Opus
DEFAULT_LATENCY_THRESHOLD_MS = 1500  # TTFT threshold


@dataclass
class BenchmarkPrompt:
    """One directive-compliance test case."""

    id: str
    user_text: str
    directive: str  # the grounding directive injected into the VOLATILE band
    word_limit: int
    expected_behavior_description: str  # for the judge LLM


# Five prompts covering the 5 grounding directive strategies used by the
# grounding_ledger FSM (advance, rephrase, elaborate, present_reasoning, ungrounded_caution).
BENCHMARK_PROMPTS: list[BenchmarkPrompt] = [
    BenchmarkPrompt(
        id="advance",
        user_text="Yeah, that makes sense. Can you tell me more about the next step?",
        directive="advance: the previous exchange was grounded. Proceed to the next topic.",
        word_limit=35,
        expected_behavior_description=(
            "The response should advance to a new topic or next step without repeating "
            "the previous exchange. It should acknowledge grounding implicitly and move forward."
        ),
    ),
    BenchmarkPrompt(
        id="rephrase",
        user_text="Wait, what? I don't follow.",
        directive=(
            "rephrase: the previous response was not grounded. Acknowledge the "
            "confusion and rephrase using simpler language."
        ),
        word_limit=30,
        expected_behavior_description=(
            "The response should rephrase the previous content in simpler terms, "
            "not introduce new information."
        ),
    ),
    BenchmarkPrompt(
        id="elaborate",
        user_text="Can you explain that a different way?",
        directive=(
            "elaborate: operator asked for clarification. Provide additional detail "
            "or a concrete example of the most recent topic."
        ),
        word_limit=45,
        expected_behavior_description=(
            "The response should expand on the most recent topic with additional "
            "detail or a concrete example. It should NOT change topics."
        ),
    ),
    BenchmarkPrompt(
        id="present_reasoning",
        user_text="I'm not sure I agree with that.",
        directive=(
            "present_reasoning: operator is contesting. Walk through the reasoning "
            "step by step without doubling down or backing off."
        ),
        word_limit=50,
        expected_behavior_description=(
            "The response should lay out the reasoning in steps, acknowledging the "
            "disagreement. It should NOT simply repeat the prior assertion."
        ),
    ),
    BenchmarkPrompt(
        id="ungrounded_caution",
        user_text="Hmm, I'm not sure.",
        directive=(
            "ungrounded_caution: previous exchange is ambiguous. Offer a concrete "
            "choice point that the operator can accept or correct."
        ),
        word_limit=30,
        expected_behavior_description=(
            "The response should offer a concrete question or binary choice to "
            "resolve the ambiguity, rather than proceeding as if grounded."
        ),
    ),
]


@dataclass
class PromptResult:
    prompt_id: str
    response_text: str = ""
    ttft_ms: float = 0.0
    response_word_count: int = 0
    directive_pass: bool = False
    word_limit_pass: bool = False
    judge_reasoning: str = ""
    error: str = ""


@dataclass
class SmokeResult:
    ok: bool = True
    exit_code: int = 0
    reason: str = ""
    prompts: list[PromptResult] = field(default_factory=list)
    directive_pass_count: int = 0
    word_limit_pass_count: int = 0
    capable_tier_ok: bool | None = None
    capable_tier_value: str = ""
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    dry_run: bool = False


def check_capable_tier() -> tuple[bool, str]:
    """Verify shared.config.MODELS['capable'] still routes to Claude Opus.

    This is a pure static check — imports the config module and reads
    the alias. Does NOT require the LiteLLM gateway.
    """
    try:
        from shared.config import MODELS
    except ImportError as exc:
        return False, f"shared.config import failed: {exc}"
    capable = MODELS.get("capable", "")
    if not isinstance(capable, str):
        return False, f"MODELS['capable'] is not a string: {type(capable).__name__}"
    if not capable:
        return False, "MODELS['capable'] is empty — CAPABLE tier missing"
    # Accept variants: "claude-opus-4-6", "openai/claude-opus-...", "anthropic/claude-opus"
    if "claude" not in capable.lower() or "opus" not in capable.lower():
        return False, f"MODELS['capable']={capable!r} does not route to Claude Opus"
    return True, capable


def run_prompt_with_hermes(
    prompt: BenchmarkPrompt,
    litellm_url: str,
    hermes_model: str,
) -> PromptResult:
    """Execute a single benchmark prompt against the Hermes 3 substrate.

    Returns a PromptResult with raw response + TTFT. The grading step
    happens separately via grade_response_with_judge().
    """
    result = PromptResult(prompt_id=prompt.id)
    try:
        import httpx
    except ImportError:
        result.error = "httpx not installed"
        return result

    payload = {
        "model": hermes_model,
        "messages": [
            {
                "role": "system",
                "content": f"You are a grounded conversational partner. Follow this directive strictly: {prompt.directive}",
            },
            {"role": "user", "content": prompt.user_text},
        ],
        "max_tokens": 200,
        "temperature": 0.7,
    }

    t0 = time.monotonic()
    try:
        response = httpx.post(
            f"{litellm_url}/v1/chat/completions",
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001
        result.error = f"Hermes 3 request failed: {exc}"
        return result

    t1 = time.monotonic()
    result.ttft_ms = (t1 - t0) * 1000

    try:
        result.response_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        result.error = f"unexpected response shape: {exc}"
        return result

    result.response_word_count = len(result.response_text.split())
    result.word_limit_pass = result.response_word_count <= int(prompt.word_limit * 1.2)
    return result


def grade_response_with_judge(
    prompt: BenchmarkPrompt,
    response_text: str,
    litellm_url: str,
    judge_model: str,
) -> tuple[bool, str]:
    """Grade a single response using Claude Opus as an LLM-as-judge.

    Returns (directive_pass, reasoning).
    """
    try:
        import httpx
    except ImportError:
        return False, "httpx not installed"

    judge_prompt = f"""You are grading a conversational response for directive compliance.

Context: the response was generated by a voice AI system under an active grounding directive.

Directive given to the system: {prompt.directive}

Expected behavior: {prompt.expected_behavior_description}

The system's response was: {response_text!r}

Did the response follow the directive and exhibit the expected behavior?

Answer with a single line starting with PASS or FAIL, followed by one sentence of reasoning. Example:
PASS: The response rephrased the prior content using simpler language without introducing new topics.
FAIL: The response ignored the directive and advanced to a new topic.
"""

    payload = {
        "model": judge_model,
        "messages": [{"role": "user", "content": judge_prompt}],
        "max_tokens": 100,
        "temperature": 0.0,
    }

    try:
        response = httpx.post(
            f"{litellm_url}/v1/chat/completions",
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        judge_output = data["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"judge request failed: {exc}"

    directive_pass = judge_output.upper().startswith("PASS")
    return directive_pass, judge_output


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def run_smoke(args: argparse.Namespace) -> SmokeResult:
    result = SmokeResult(dry_run=args.dry_run)

    # CAPABLE tier check (always runs unless explicitly disabled)
    if not args.benchmark_only:
        ok, value = check_capable_tier()
        result.capable_tier_ok = ok
        result.capable_tier_value = value
        if not ok:
            result.ok = False
            result.exit_code = 4
            result.reason = f"CAPABLE tier verification failed: {value}"
            return result

    if args.capable_check_only:
        result.reason = f"CAPABLE tier verified: {value}"
        return result

    # Benchmark + latency (skipped on dry-run)
    if args.dry_run:
        result.reason = f"dry-run complete; CAPABLE tier verified: {result.capable_tier_value}"
        return result

    ttfts: list[float] = []
    for prompt in BENCHMARK_PROMPTS:
        prompt_result = run_prompt_with_hermes(prompt, args.litellm_url, args.hermes_model)
        if prompt_result.error:
            result.prompts.append(prompt_result)
            result.ok = False
            result.exit_code = 6
            result.reason = f"benchmark invocation failed on {prompt.id}: {prompt_result.error}"
            return result

        # Grade the response
        directive_pass, reasoning = grade_response_with_judge(
            prompt, prompt_result.response_text, args.litellm_url, args.judge_model
        )
        prompt_result.directive_pass = directive_pass
        prompt_result.judge_reasoning = reasoning
        result.prompts.append(prompt_result)
        ttfts.append(prompt_result.ttft_ms)

        if directive_pass:
            result.directive_pass_count += 1
        if prompt_result.word_limit_pass:
            result.word_limit_pass_count += 1

    result.latency_p50_ms = percentile(ttfts, 0.5)
    result.latency_p95_ms = percentile(ttfts, 0.95)

    # Gate 1: directive compliance >= 3/5
    if result.directive_pass_count < 3:
        result.ok = False
        result.exit_code = 2
        result.reason = (
            f"directive compliance failure: {result.directive_pass_count}/5 < 3 "
            f"(Phase 5 gate: ≥ 3/5 required)"
        )
        return result

    # Gate 2: word limit compliance >= 4/5
    if result.word_limit_pass_count < 4:
        result.ok = False
        result.exit_code = 3
        result.reason = (
            f"word limit compliance failure: {result.word_limit_pass_count}/5 < 4 "
            f"(Phase 5 gate: ≥ 4/5 required)"
        )
        return result

    # Gate 3: latency threshold
    if result.latency_p95_ms > args.latency_threshold_ms:
        result.ok = False
        result.exit_code = 5
        result.reason = (
            f"latency p95 {result.latency_p95_ms:.0f} ms > threshold {args.latency_threshold_ms} ms"
        )
        return result

    result.reason = (
        f"all gates passed — directive {result.directive_pass_count}/5, "
        f"word-limit {result.word_limit_pass_count}/5, "
        f"latency p50 {result.latency_p50_ms:.0f} ms / p95 {result.latency_p95_ms:.0f} ms"
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phase-5-post-swap-smoke.py",
        description="LRR Phase 5 post-swap smoke test / go-no-go gate",
    )
    p.add_argument(
        "--litellm-url",
        default=DEFAULT_LITELLM_URL,
        help=f"LiteLLM gateway URL (default: {DEFAULT_LITELLM_URL})",
    )
    p.add_argument(
        "--hermes-model",
        default=DEFAULT_HERMES_MODEL,
        help=f"LiteLLM alias for Hermes 3 (default: {DEFAULT_HERMES_MODEL})",
    )
    p.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help=f"LiteLLM alias for the judge LLM (default: {DEFAULT_JUDGE_MODEL})",
    )
    p.add_argument(
        "--latency-threshold-ms",
        type=int,
        default=DEFAULT_LATENCY_THRESHOLD_MS,
        help=f"p95 TTFT threshold in ms (default: {DEFAULT_LATENCY_THRESHOLD_MS})",
    )
    p.add_argument(
        "--capable-check-only",
        action="store_true",
        help="Run only the CAPABLE tier check + exit (skip benchmark + latency)",
    )
    p.add_argument(
        "--benchmark-only",
        action="store_true",
        help="Run only the benchmark + latency (skip CAPABLE tier check)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Run CAPABLE check + prompt definition sanity but skip live LLM calls",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSON output",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_smoke(args)

    if args.as_json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status = "OK" if result.ok else "FAIL"
        print(f"phase-5-post-swap-smoke: {status} — {result.reason}")
        if result.capable_tier_ok is not None:
            mark = "✓" if result.capable_tier_ok else "✗"
            print(f"  {mark} CAPABLE tier: {result.capable_tier_value}")
        if result.prompts:
            for pr in result.prompts:
                if pr.error:
                    print(f"  ✗ {pr.prompt_id}: ERROR {pr.error}")
                    continue
                dmark = "✓" if pr.directive_pass else "✗"
                wmark = "✓" if pr.word_limit_pass else "✗"
                print(
                    f"  {dmark}{wmark} {pr.prompt_id}: "
                    f"{pr.response_word_count} words, {pr.ttft_ms:.0f} ms TTFT — {pr.judge_reasoning[:80]}"
                )
        if result.latency_p50_ms:
            print(
                f"  latency p50={result.latency_p50_ms:.0f} ms, p95={result.latency_p95_ms:.0f} ms"
            )

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
