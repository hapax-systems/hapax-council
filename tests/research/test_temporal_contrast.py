"""Measure 3.1 — A/B validation: flat JSON vs temporal bands.

Paired comparison on 4-task battery. Each perception window is formatted
as both flat JSON (baseline) and Husserlian temporal bands (treatment).
Claude scores both responses on relevance, specificity, temporal_awareness,
and actionability.

Run: uv run pytest tests/research/test_temporal_contrast.py -m llm -v
(Requires LITELLM_API_KEY and running LiteLLM gateway at :4000)
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from agents.hapax_daimonion.perception_ring import PerceptionRing
from agents.temporal_bands import TemporalBandFormatter

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS = Path(__file__).parent / "results"

TASK_PROMPTS: dict[str, str] = {
    "what_changed": (
        "Based on the context provided, what just changed in the "
        "operator's state? Be specific about what shifted and when."
    ),
    "what_next": (
        "Based on the context provided, what is likely to happen next? "
        "What should the system anticipate?"
    ),
    "escalate": (
        "Based on the context provided, should the system escalate any concerns? Why or why not?"
    ),
    "summarize": (
        "Summarize the current situation in 2-3 sentences. What is the "
        "operator doing and how is their session going?"
    ),
}

EVALUATOR_PROMPT = """You are evaluating a perception system's response quality.

The system was given context about an operator's state and asked a question.
Rate the response on these dimensions (integer 1-5):

1. **relevance** — Does the response use facts from the context? (1=irrelevant, 5=all claims grounded)
2. **specificity** — Does it mention concrete details: activities, numbers, durations? (1=vague, 5=precise)
3. **temporal_awareness** — Does it reference time, change, trends, or anticipation? (1=timeless, 5=rich temporal)
4. **actionability** — Does it provide clear next steps or signal relevance? (1=philosophical, 5=actionable)

Context given to system:
{context}

Question asked:
{question}

System response:
{response}

Reply with ONLY a JSON object: {{"relevance": N, "specificity": N, "temporal_awareness": N, "actionability": N}}
"""


@dataclass
class TrialResult:
    snapshot_idx: int
    task: str
    condition: str  # "flat" or "temporal"
    response: str
    scores: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


@dataclass
class ContrastResult:
    trials: list[TrialResult]
    timestamp: str = ""

    def summary(self) -> dict[str, dict[str, float]]:
        """Compute mean scores per condition per metric."""
        from collections import defaultdict

        sums: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for t in self.trials:
            for metric, score in t.scores.items():
                sums[t.condition][metric].append(score)

        return {
            cond: {metric: sum(vals) / len(vals) for metric, vals in metrics.items()}
            for cond, metrics in sums.items()
        }

    def effect_sizes(self) -> dict[str, float]:
        """Mean difference (temporal - flat) per metric."""
        from collections import defaultdict

        flat_scores: dict[str, list[float]] = defaultdict(list)
        temp_scores: dict[str, list[float]] = defaultdict(list)
        for t in self.trials:
            target = flat_scores if t.condition == "flat" else temp_scores
            for metric, score in t.scores.items():
                target[metric].append(score)

        effects = {}
        for metric in flat_scores:
            f_mean = sum(flat_scores[metric]) / max(1, len(flat_scores[metric]))
            t_mean = sum(temp_scores[metric]) / max(1, len(temp_scores[metric]))
            effects[metric] = round(t_mean - f_mean, 3)
        return effects


def load_snapshots() -> list[dict]:
    """Load perception snapshots from fixtures."""
    path = FIXTURES / "perception_snapshots_50.jsonl"
    with path.open() as f:
        return [json.loads(line) for line in f]


def build_flat_context(snapshot: dict, history: list[dict]) -> str:
    """Flat JSON context (baseline condition)."""
    ctx = {
        "current": snapshot,
        "recent_history": history[-5:] if history else [],
    }
    return f"Current perception state (JSON):\n{json.dumps(ctx, indent=2)}"


def build_temporal_context(ring: PerceptionRing, formatter: TemporalBandFormatter) -> str:
    """Temporal bands XML context (treatment condition)."""
    bands = formatter.format(ring)
    xml = formatter.format_xml(bands)
    preamble = (
        "Temporal context (retention = fading past, impression = vivid present, "
        "protention = anticipated near-future):"
    )
    return preamble + "\n" + xml


async def call_llm(prompt: str, model_id: str = "claude-sonnet") -> str:
    """Call LLM via LiteLLM gateway."""
    import httpx

    from shared.config import LITELLM_BASE, LITELLM_KEY

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{LITELLM_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def score_response(
    context: str, question: str, response: str, model_id: str = "claude-sonnet"
) -> dict[str, int]:
    """Use LLM-as-judge to score a response."""
    prompt = EVALUATOR_PROMPT.format(
        context=context,
        question=question,
        response=response,
    )
    raw = await call_llm(prompt, model_id)
    # Extract JSON from response (may have markdown wrapping)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        return json.loads(raw[start:end])
    return {"relevance": 3, "specificity": 3, "temporal_awareness": 3, "actionability": 3}


@pytest.mark.llm
@pytest.mark.asyncio
async def test_temporal_contrast_ab(
    n_pairs: int = 20,
    model_id: str = "claude-sonnet",
) -> None:
    """Main A/B test: n_pairs snapshot windows × 4 tasks × 2 conditions.

    Run with: uv run pytest tests/research/test_temporal_contrast.py -m llm -v
    """
    snapshots = load_snapshots()
    formatter = TemporalBandFormatter()
    trials: list[TrialResult] = []

    for idx in range(min(n_pairs, len(snapshots) - 5)):
        # Build ring with 6-snapshot history
        ring = PerceptionRing()
        history: list[dict] = []
        for j in range(max(0, idx - 5), idx + 1):
            ring.push(snapshots[j])
            history.append(snapshots[j])

        current = snapshots[idx]
        flat_ctx = build_flat_context(current, history)
        temporal_ctx = build_temporal_context(ring, formatter)

        for task_name, task_prompt in TASK_PROMPTS.items():
            # Flat condition
            t0 = time.monotonic()
            flat_resp = await call_llm(
                f"{flat_ctx}\n\nQuestion: {task_prompt}",
                model_id,
            )
            flat_latency = (time.monotonic() - t0) * 1000

            flat_scores = await score_response(flat_ctx, task_prompt, flat_resp, model_id)
            trials.append(
                TrialResult(
                    snapshot_idx=idx,
                    task=task_name,
                    condition="flat",
                    response=flat_resp,
                    scores=flat_scores,
                    latency_ms=flat_latency,
                )
            )

            # Temporal condition
            t0 = time.monotonic()
            temporal_resp = await call_llm(
                f"{temporal_ctx}\n\nQuestion: {task_prompt}",
                model_id,
            )
            temporal_latency = (time.monotonic() - t0) * 1000

            temporal_scores = await score_response(
                temporal_ctx,
                task_prompt,
                temporal_resp,
                model_id,
            )
            trials.append(
                TrialResult(
                    snapshot_idx=idx,
                    task=task_name,
                    condition="temporal",
                    response=temporal_resp,
                    scores=temporal_scores,
                    latency_ms=temporal_latency,
                )
            )

    # Save results
    result = ContrastResult(
        trials=trials,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"contrast_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(asdict(result), indent=2))

    # Report
    summary = result.summary()
    effects = result.effect_sizes()

    print("\n=== Measure 3.1: Temporal Bands A/B ===")
    print(f"Pairs: {n_pairs}, Tasks: {len(TASK_PROMPTS)}, Trials: {len(trials)}")
    print("\nMean scores:")
    for cond, metrics in summary.items():
        print(f"  {cond}: {metrics}")
    print("\nEffect sizes (temporal - flat):")
    for metric, effect in effects.items():
        print(f"  {metric}: {effect:+.3f}")

    # Gate: temporal_awareness improvement ≥ 0.5
    ta_effect = effects.get("temporal_awareness", 0)
    print(f"\nGate: temporal_awareness effect = {ta_effect:+.3f} (threshold: ≥0.5)")
    if ta_effect >= 0.5:
        print("PASS — temporal bands improve temporal reasoning")
    else:
        print("WATCH — effect below threshold, needs more data or investigation")

    # Save summary
    summary_path = RESULTS / f"summary_{time.strftime('%Y%m%d_%H%M%S')}.md"
    summary_path.write_text(
        f"# Measure 3.1: Temporal Bands A/B\n\n"
        f"**Date:** {result.timestamp}\n"
        f"**Pairs:** {n_pairs}\n"
        f"**Model:** {model_id}\n\n"
        f"## Mean Scores\n\n"
        f"| Condition | Relevance | Specificity | Temporal Awareness | Actionability |\n"
        f"|-----------|-----------|-------------|-------------------|---------------|\n"
        + "\n".join(
            f"| {cond} | {m.get('relevance', 0):.2f} | {m.get('specificity', 0):.2f} "
            f"| {m.get('temporal_awareness', 0):.2f} | {m.get('actionability', 0):.2f} |"
            for cond, m in summary.items()
        )
        + "\n\n## Effect Sizes\n\n"
        + "\n".join(f"- **{k}**: {v:+.3f}" for k, v in effects.items())
        + f"\n\n## Gate\n\n"
        f"temporal_awareness effect: {ta_effect:+.3f} "
        f"({'PASS' if ta_effect >= 0.5 else 'WATCH'})\n"
    )
