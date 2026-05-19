#!/usr/bin/env python3
"""Run CCTV (Conceptual Coherence Tester and Validator) against council synthesis claims.

Extracts material claims from Council Synthesis II and III documents,
runs each through the full 5-phase deliberative council engine in
DISCONFIRMATION mode, and produces a structured report.

Usage:
    uv run python scripts/run_cctv_council_synthesis.py [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

SYNTHESIS_2 = Path("/data/downloads/council_synthesis_2.md")
SYNTHESIS_3 = Path("/data/downloads/council_synthesis_3.md")
OUTPUT_DIR = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
)
OUTPUT_FILE = OUTPUT_DIR / "cctv-council-synthesis-verdicts.jsonl"


CLAIMS = [
    {
        "id": "C2-1",
        "source": "council_synthesis_2",
        "text": "RLHF demonstrably reduces grounding acts: present-day post-trained assistants underproduce clarification and follow-up acts, worsened by preference optimization",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
        "evidence_cited": "Shaikh et al. NAACL 2024: 3x less clarification, 16x less follow-up; 23.23% on Rifts",
    },
    {
        "id": "C2-2",
        "source": "council_synthesis_2",
        "text": "The grounding architecture is a genuine architectural response, not a rename: it externalizes and measures conversation-level grounding with a DU ledger, acceptance classification, GQI, and monologic scoring",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
        "evidence_cited": "grounding_ledger.py, _score_monologic(), test_rlhf_monitoring.py, 2-of-7 Traum grounding acts implemented",
    },
    {
        "id": "C2-3",
        "source": "council_synthesis_2",
        "text": "The RLHF correction claim outruns its citations: context engineering can plausibly bend the bias but has not been shown to break the ceiling",
        "source_ref": "docs/research/2026-04-16-olmo-litellm-route-and-cycle-2-deferral.md",
        "evidence_cited": "Niu et al. ACL 2025 entrainment heads: lexical entrainment, not grounding stance; Von Oswald 2023: toy linear regression setting",
    },
    {
        "id": "C2-4",
        "source": "council_synthesis_2",
        "text": "The monologic scorer has a Goodhart problem: once in CI, the LLM under grounding context will progressively shape output to satisfy the scorer's surface features",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
        "evidence_cited": "_score_monologic() is a surface-marker heuristic; no out-of-band non-LLM signal for grounding quality",
    },
    {
        "id": "C2-5",
        "source": "council_synthesis_2",
        "text": "SCED Cycle 1 evidence is insufficient for the trust claim: BF=3.66 does not clear BF>=10 bar for a claim this large, especially with autocorrelation correction",
        "source_ref": "agents/hapax_daimonion/proofs/CYCLE-1-PILOT-REPORT.md",
        "evidence_cited": "BF=3.66 explicitly labeled inconclusive; autocorrelation correction acknowledged",
    },
    {
        "id": "C2-6",
        "source": "council_synthesis_2",
        "text": "The recognizer-is-the-recognized problem: _score_monologic() and the acceptance classifier are RLHF-trained LLMs detecting output of RLHF-trained LLMs, with no out-of-band non-LLM signal",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
        "evidence_cited": "Grounding has no algebraic primitives — may be a structural property of the domain",
    },
    {
        "id": "C3-1",
        "source": "council_synthesis_3",
        "text": "The local non-RLHF substrate is real and doing continuous work: DMN posts directly to TabbyAPI at :5000 with 5s sensory ticks and 30s evaluative ticks",
        "source_ref": "agents/dmn/ollama.py",
        "evidence_cited": "DMN_MODEL hardcoded to Qwen3.5-9B; direct to TabbyAPI",
    },
    {
        "id": "C3-2",
        "source": "council_synthesis_3",
        "text": "Stigmergy provides genuine protection against coupling-induced contamination by forcing local DMN to read RLHF output as external artifact rather than internal thought",
        "source_ref": "agents/manifests/reactive_engine.yaml",
        "evidence_cited": "inotify-driven rule engine; shared/chronicle.py authority downgrade logic in consumer layer",
    },
    {
        "id": "C3-3",
        "source": "council_synthesis_3",
        "text": "The conversation path is NOT fixed to local models: salience routing escalates to cloud (local-fast threshold 0.20, anything above routes to cloud RLHF)",
        "source_ref": "agents/hapax_daimonion/model_router.py",
        "evidence_cited": "TIER_ROUTES: LOCAL(0-0.20)->local-fast, FAST->gemini-flash, STRONG->claude-sonnet, CAPABLE->claude-opus",
    },
    {
        "id": "C3-4",
        "source": "council_synthesis_3",
        "text": "config/grounding-providers.json marks Command-R as can_satisfy_open_world_claims: false and latest_cloud_model_default: true — the architecture has not crossed from 'local substrate exists' to 'local is epistemic sovereign'",
        "source_ref": "config/grounding-providers.json",
        "evidence_cited": "Line 8: latest_cloud_model_default: true; Line 38: can_satisfy_open_world_claims: false",
    },
    {
        "id": "C3-5",
        "source": "council_synthesis_3",
        "text": "The coherence-vs-correspondence gap is the steelman that survives all three councils: the architecture succeeds at internal coherence but the trust problem is correspondence (do narrations track reality?)",
        "source_ref": "axioms/persona/hapax-description-of-being.md",
        "evidence_cited": "Description-of-being section 6 prohibition on inner-life claims; every structural claim must be grep-able",
    },
    {
        "id": "C3-6",
        "source": "council_synthesis_3",
        "text": "Command-R is characterized as non-RLHF but Cohere documents preference fine-tuning (IPO + CoPG) in Command-R's training — the binary RLHF/non-RLHF framing collapses",
        "source_ref": "config/grounding-providers.json",
        "evidence_cited": "CCTV adversarial pass finding: Cohere Command-R training includes preference optimization",
    },
]


async def run_cctv() -> None:
    from agents.deliberative_council.engine import deliberate
    from agents.deliberative_council.models import CouncilConfig, CouncilInput, CouncilMode
    from agents.deliberative_council.rubrics import DisconfirmationRubric

    rubric = DisconfirmationRubric()
    config = CouncilConfig(
        model_aliases=(
            "claude-opus",
            "claude-sonnet",
            "gemini-pro",
            "local-fast",
            "web-research",
            "mistral-large",
        ),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== CCTV: Council Synthesis Disconfirmation ===")
    print(f"Claims: {len(CLAIMS)}")
    print(f"Models: {config.model_aliases}")
    print(f"Output: {OUTPUT_FILE}\n")

    for i, claim in enumerate(CLAIMS):
        print(f"[{i + 1}/{len(CLAIMS)}] {claim['id']}: {claim['text'][:80]}...")

        inp = CouncilInput(
            text=claim["text"],
            source_ref=claim["source_ref"],
            metadata={
                "claim_id": claim["id"],
                "source_document": claim["source"],
                "evidence_cited": claim["evidence_cited"],
            },
        )

        verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        result = {
            "claim_id": claim["id"],
            "claim_text": claim["text"],
            "source_ref": claim["source_ref"],
            "scores": verdict.scores,
            "confidence_bands": {k: list(v) for k, v in verdict.confidence_bands.items()},
            "convergence_status": verdict.convergence_status.value,
            "disagreement_log": verdict.disagreement_log,
            "research_findings": verdict.research_findings,
            "adversarial_exchanges": [
                {
                    "axis": e.axis,
                    "high_scorer": e.high_scorer,
                    "low_scorer": e.low_scorer,
                    "response_text": e.response_text[:500],
                }
                for e in verdict.adversarial_exchanges
            ],
            "receipt": verdict.receipt,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        with OUTPUT_FILE.open("a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        status = verdict.convergence_status.value
        scores_str = " ".join(f"{k}={v}" for k, v in verdict.scores.items())
        print(f"  → {status} | {scores_str}")

    print(f"\n=== Done. {len(CLAIMS)} claims evaluated. Output: {OUTPUT_FILE} ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="CCTV: Council Synthesis Disconfirmation")
    parser.add_argument("--limit", type=int, default=0, help="Max claims to process (0=all)")
    args = parser.parse_args()

    if args.limit > 0:
        global CLAIMS
        CLAIMS = CLAIMS[: args.limit]

    asyncio.run(run_cctv())


if __name__ == "__main__":
    main()
