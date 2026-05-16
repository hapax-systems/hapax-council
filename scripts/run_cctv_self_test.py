#!/usr/bin/env python3
"""Run CCTV against its own design and implementation claims.

The CCTV testing itself. Every architectural choice, design assumption,
and implementation claim from the deliberative council engine is
submitted for adversarial disconfirmation by the engine itself.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

OUTPUT = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
    / "cctv-self-test-verdicts.jsonl"
)

CLAIMS = [
    {
        "id": "DESIGN-1",
        "text": (
            "A 5-phase protocol (independent scoring, evidence matrix, adversarial "
            "challenge, revision, convergence) produces more reliable judgments than "
            "simple multi-model voting or single-model evaluation."
        ),
        "source_ref": "docs/superpowers/specs/2026-05-15-deliberative-council-engine-design.md",
    },
    {
        "id": "DESIGN-2",
        "text": (
            "Six models across four training families (Anthropic, Google, Cohere, "
            "Mistral + Perplexity) provide sufficient diversity to detect systematic "
            "bias. Same-family models should have combined weight halved when they "
            "correlate above 0.90."
        ),
        "source_ref": "agents/deliberative_council/aggregation.py",
    },
    {
        "id": "DESIGN-3",
        "text": (
            "IQR-based convergence classification (converged <= 1, contested 1-2, "
            "hung > 2) is the right aggregation for adversarial deliberation. "
            "Short-circuit at IQR <= 1 saves ~40% of API calls without sacrificing "
            "verdict quality."
        ),
        "source_ref": "agents/deliberative_council/aggregation.py",
    },
    {
        "id": "DESIGN-4",
        "text": (
            "Equipping council members with research tools (read_source, grep, git, "
            "web_verify, qdrant, vault) transforms scoring from text-only to "
            "investigative, producing materially different verdicts."
        ),
        "source_ref": "agents/deliberative_council/tools.py",
    },
    {
        "id": "DESIGN-5",
        "text": (
            "Command-R 35B as restricted-tool text-only anchor provides a useful "
            "bias detector: score delta vs research-equipped models reveals whether "
            "investigation changed the judgment or confirmed priors."
        ),
        "source_ref": "agents/deliberative_council/members.py",
    },
    {
        "id": "IMPL-1",
        "text": (
            "The DisconfirmationRubric's four axes (evidence_adequacy, "
            "counter_evidence_resilience, scope_honesty, falsifiability) are "
            "sufficient to evaluate conceptual coherence of research claims."
        ),
        "source_ref": "agents/deliberative_council/rubrics.py",
    },
    {
        "id": "IMPL-2",
        "text": (
            "Phase 2 using a single model to build the ACH evidence matrix avoids "
            "the committee-of-committees problem. A single synthesizer is "
            "architecturally sound."
        ),
        "source_ref": "agents/deliberative_council/engine.py",
    },
    {
        "id": "IMPL-3",
        "text": (
            "Phase 3 targeting only highest vs lowest scorer per contested axis is "
            "sufficient. Challenging midrange scorers adds cost without proportional "
            "insight."
        ),
        "source_ref": "agents/deliberative_council/engine.py",
    },
    {
        "id": "IMPL-4",
        "text": (
            "Integrating CCTV into segment prep as Pass 3 — extracting claims and "
            "running disconfirmation before validation gates — makes the first "
            "validation pass inherently stronger."
        ),
        "source_ref": "shared/segment_disconfirmation.py",
    },
    {
        "id": "IMPL-5",
        "text": (
            "Adding deliberative_council_ratified to HUMAN_LABEL_ORIGINS is a "
            "legitimate governance amendment: multi-model adversarial deliberation "
            "with operator ratification has equivalent authority to single-operator "
            "cold-reading for epistemic quality labels."
        ),
        "source_ref": "scripts/epistemic_quality_dataset.py",
    },
    {
        "id": "META-1",
        "text": (
            "The CCTV can meaningfully test its own design basis without "
            "self-referential closure invalidating results. Models from different "
            "training families with different biases partially break the "
            "recognizer-is-the-recognized loop."
        ),
        "source_ref": "agents/deliberative_council/engine.py",
    },
    {
        "id": "META-2",
        "text": (
            "The deflation-not-refutation pattern observed across Councils II-IV — "
            "claims are never false but systematically overconfident — is a real "
            "epistemic phenomenon, not an artifact of CCTV agreeableness bias."
        ),
        "source_ref": "docs/superpowers/specs/2026-05-15-deliberative-council-engine-design.md",
    },
    {
        "id": "META-3",
        "text": (
            "CCTV's Goodhart vulnerability is manageable: the scoring rubric is not "
            "in the generation context of models producing claims being tested. "
            "Goodhart pressure exists only if CCTV results feed back into claim "
            "generation."
        ),
        "source_ref": "agents/deliberative_council/rubrics.py",
    },
]


async def run() -> None:
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

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n=== CCTV SELF-TEST: Testing the tester ===")
    print(f"Claims: {len(CLAIMS)} (5 design, 5 implementation, 3 meta)")
    print(f"Models: {config.model_aliases}\n")

    for i, claim in enumerate(CLAIMS):
        print(
            f"[{i + 1}/{len(CLAIMS)}] {claim['id']}: {claim['text'][:70]}...",
            flush=True,
        )

        inp = CouncilInput(
            text=claim["text"],
            source_ref=claim["source_ref"],
            metadata={"claim_id": claim["id"]},
        )

        verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        result = {
            "claim_id": claim["id"],
            "claim_text": claim["text"],
            "scores": verdict.scores,
            "confidence_bands": {k: list(v) for k, v in verdict.confidence_bands.items()},
            "convergence_status": verdict.convergence_status.value,
            "disagreement_log": verdict.disagreement_log,
            "research_findings": verdict.research_findings[:10],
            "adversarial_exchanges": [
                {
                    "axis": e.axis,
                    "high_scorer": e.high_scorer,
                    "low_scorer": e.low_scorer,
                    "response_text": e.response_text[:500],
                }
                for e in verdict.adversarial_exchanges
            ],
            "phases_completed": verdict.receipt.get("phases_completed", []),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        with OUTPUT.open("a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        scores_str = " ".join(f"{k}={v}" for k, v in verdict.scores.items())
        print(f"  -> {verdict.convergence_status.value} | {scores_str}")

    print(f"\n=== CCTV self-test complete. {len(CLAIMS)} claims. ===")


if __name__ == "__main__":
    asyncio.run(run())
