#!/usr/bin/env python3
"""Run CCTV against the 6 action plan documents — antagonistic shakeup."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

PLANS_DIR = Path.home() / "Documents/Personal/20-projects/hapax-research"
OUTPUT_FILE = PLANS_DIR / "cctv-action-plan-verdicts.jsonl"

CLAIMS = [
    {
        "id": "GL-1",
        "domain": "grounding-loop",
        "text": "The acceptance signal in conversation_pipeline.py is bound to the wrong turn — stored on current ThreadEntry when it's feedback on the prior assistant utterance. Every downstream metric (GQI, SCED, effort calibration) is built on a corrupted supervision signal.",
        "source_ref": "agents/hapax_daimonion/conversation_pipeline.py",
    },
    {
        "id": "GL-2",
        "domain": "grounding-loop",
        "text": "System context is rebuilt BEFORE acceptance is classified, so the grounding directive the LLM sees is always one turn stale. Moving classification before context rebuild fixes directive timing.",
        "source_ref": "agents/hapax_daimonion/conversation_pipeline.py",
    },
    {
        "id": "GL-3",
        "domain": "grounding-loop",
        "text": "Replacing keyword heuristics in classify_acceptance() with embedding-based prototype similarity using nomic-embed preserves the non-LLM property while fixing coverage. DeBERTa NLI is an alternative.",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
    },
    {
        "id": "GOV-1",
        "domain": "governance",
        "text": "sdlc_axiom_judge.py can be replaced with VetoChain-composed deterministic predicates for T0/T1 implications, demoting the LLM judge to advisory for T2/T3 cases only.",
        "source_ref": "scripts/sdlc_axiom_judge.py",
    },
    {
        "id": "GOV-2",
        "domain": "governance",
        "text": "A governance replay harness re-evaluating historical decisions against current policies would detect regressions and make governance a verifiable runtime property.",
        "source_ref": "packages/policyflow/src/policyflow/",
    },
    {
        "id": "RES-1",
        "domain": "research",
        "text": "The RLHF ceiling/restoration claim in CONTEXT-AS-COMPUTATION.md should be retired — CCTV scored evidence_adequacy=2, Shaikh shows suppression not restoration, and Command-R's IPO+CoPG makes the binary framing untenable.",
        "source_ref": "agents/hapax_daimonion/proofs/CONTEXT-AS-COMPUTATION.md",
    },
    {
        "id": "RES-2",
        "domain": "research",
        "text": "Cycle 2 needs Kruschke BEST with AR(1) residuals, BF>=10 bar, and repair_cycle_resolution_rate_2turn as primary DV. The observed effect (+0.029 vs predicted +0.150) means Cycle 1 was underpowered.",
        "source_ref": "agents/hapax_daimonion/proofs/CYCLE-1-PILOT-REPORT.md",
    },
    {
        "id": "TRUST-1",
        "domain": "operator-trust",
        "text": "All six receipt data sources (stimmung, CPAL state, DU state, routing tier, acceptance signal, strategy directive) are already computed in-process on ConversationPipeline — the receipt publisher requires only collection and write, no new computation.",
        "source_ref": "agents/hapax_daimonion/conversation_pipeline.py",
    },
    {
        "id": "TRUST-2",
        "domain": "operator-trust",
        "text": "A correspondence panel color-coding whether narration vocabulary tracks architectural state can use Description-of-Being section 5 analogies mapped to expected stimmung/GQI regions.",
        "source_ref": "axioms/persona/hapax-description-of-being.md",
    },
    {
        "id": "PUB-1",
        "domain": "publication",
        "text": "policyflow is the safest first publication because its claims are algebraically verifiable via Hypothesis property tests — no trust/grounding/phenomenological claims to defend.",
        "source_ref": "packages/policyflow/",
    },
    {
        "id": "PUB-2",
        "domain": "publication",
        "text": "Citation fixes (LOCOMO attribution, Sharma scope, Niu/Von Oswald scale) must precede any external-facing publication and cost zero implementation effort.",
        "source_ref": "agents/hapax_daimonion/proofs/",
    },
    {
        "id": "ROUTE-1",
        "domain": "routing",
        "text": "The grounding-providers.json 'contradiction' partially dissolves on close reading — it governs factual claim satisfaction, not voice routing. The config is correct but the framing/documentation is wrong.",
        "source_ref": "config/grounding-providers.json",
    },
    {
        "id": "ROUTE-2",
        "domain": "routing",
        "text": "ALL tiers produce user-facing voice output. The tier IS the output model. Most substantive turns go to cloud. The system was never local-sovereign in practice.",
        "source_ref": "agents/hapax_daimonion/model_router.py",
    },
    {
        "id": "ROUTE-3",
        "domain": "routing",
        "text": "The real distinction is source-conditioned (Command-R requires supplied evidence) vs free-generation (cloud models can make open-world claims), not RLHF vs non-RLHF.",
        "source_ref": "config/grounding-providers.json",
    },
]


async def run_cctv() -> None:
    from agents.deliberative_council.engine import deliberate
    from agents.deliberative_council.models import CouncilConfig, CouncilInput, CouncilMode
    from agents.deliberative_council.rubrics import DisconfirmationRubric

    rubric = DisconfirmationRubric()
    config = CouncilConfig()

    print("\n=== CCTV: Action Plan Antagonistic Shakeup ===")
    print(f"Claims: {len(CLAIMS)} from 6 action plans")
    print(f"Models: {config.model_aliases}\n")

    for i, claim in enumerate(CLAIMS):
        print(f"[{i + 1}/{len(CLAIMS)}] {claim['id']}: {claim['text'][:70]}...", flush=True)

        inp = CouncilInput(
            text=claim["text"],
            source_ref=claim["source_ref"],
            metadata={"claim_id": claim["id"], "domain": claim["domain"]},
        )

        verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

        result = {
            "claim_id": claim["id"],
            "domain": claim["domain"],
            "claim_text": claim["text"],
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
            "phases_completed": verdict.receipt.get("phases_completed", []),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        with OUTPUT_FILE.open("a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        scores_str = " ".join(f"{k}={v}" for k, v in verdict.scores.items())
        print(f"  → {verdict.convergence_status.value} | {scores_str}")

    print(f"\n=== Done. {len(CLAIMS)} action plan claims evaluated. ===")


if __name__ == "__main__":
    asyncio.run(run_cctv())
