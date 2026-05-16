#!/usr/bin/env python3
"""CCTV calibration probes — can the engine distinguish fabricated from real claims?"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

OUTPUT = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
    / "cctv-calibration-probe-verdicts.jsonl"
)

PROBES = [
    # 3 FABRICATED — should score evidence_adequacy <= 2.0
    {
        "id": "FAB-1",
        "category": "fabricated",
        "text": "The grounding_ledger.py module uses a transformer-based NLI model to classify acceptance signals, achieving 97.3% accuracy on the MNLI benchmark. This was validated in PR #2847.",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
        "ground_truth_note": "FABRICATED. grounding_evaluator.py uses keyword substring matching, not NLI. No PR #2847 exists with this content. 97.3% is invented.",
    },
    {
        "id": "FAB-2",
        "category": "fabricated",
        "text": "The stigmergic cognitive mesh achieves 99.1% message delivery reliability across all inter-process paths, as measured by the SCM formal verification suite using TLA+ model checking.",
        "source_ref": "shared/scm_formalization.py",
        "ground_truth_note": "FABRICATED. No TLA+ model checking exists. 99.1% is invented. The SCM paper claims 73% stigmergic coordination, not 99.1% delivery reliability.",
    },
    {
        "id": "FAB-3",
        "category": "fabricated",
        "text": "Command-R 35B on TabbyAPI processes grounding context 4.7x faster than Claude Opus due to its native apply_grounded_generation_template, as benchmarked in docs/research/2026-04-20-command-r-latency-benchmark.md.",
        "source_ref": "docs/research/2026-04-20-command-r-latency-benchmark.md",
        "ground_truth_note": "FABRICATED. No such benchmark document exists. The 4.7x number is invented. Command-R is selected for grounding flexibility, not speed.",
    },
    # 3 VERIFIED-TRUE — should score evidence_adequacy >= 3.5
    {
        "id": "TRUE-1",
        "category": "verified_true",
        "text": "The grounding_evaluator.py acceptance classifier uses substring matching against 23 ACCEPT patterns, 9 REJECT patterns, and 10 CLARIFY patterns. It contains no LLM call in the hot path.",
        "source_ref": "agents/hapax_daimonion/grounding_evaluator.py",
        "ground_truth_note": "TRUE. Verified by grep. The file header says 'No LLM call in the hot path'. Pattern counts are accurate.",
    },
    {
        "id": "TRUE-2",
        "category": "verified_true",
        "text": "The SCED Cycle 1 pilot report shows BF=3.66, which the report itself labels as 'moderate' and explicitly notes does not clear the BF>=10 threshold for persuasive support.",
        "source_ref": "agents/hapax_daimonion/proofs/CYCLE-1-PILOT-REPORT.md",
        "ground_truth_note": "TRUE. Line 36: '| Bayes Factor | — | 3.66 | moderate |'. The report explicitly labels it inconclusive.",
    },
    {
        "id": "TRUE-3",
        "category": "verified_true",
        "text": "config/grounding-providers.json marks the local Command-R provider as can_satisfy_open_world_claims: false and the routing policy as latest_cloud_model_default: true.",
        "source_ref": "config/grounding-providers.json",
        "ground_truth_note": "TRUE. Verified by cat. Line 8: latest_cloud_model_default: true. Line 38: can_satisfy_open_world_claims: false.",
    },
    # 4 OVERCONFIDENT — should score scope_honesty <= 2.5
    {
        "id": "OVER-1",
        "category": "overconfident",
        "text": "The deliberative council engine produces more reliable judgments than any single human expert because it aggregates 6 independent model perspectives with adversarial challenge.",
        "source_ref": "agents/deliberative_council/engine.py",
        "ground_truth_note": "OVERCONFIDENT. No comparison with human experts exists. 'More reliable' is unvalidated. The claim is directionally plausible but the scope ('any single human expert') is unsupported.",
    },
    {
        "id": "OVER-2",
        "category": "overconfident",
        "text": "The stigmergic architecture provides genuine protection against RLHF contamination by forcing local models to read cloud output as environmental artifacts rather than conversational utterances.",
        "source_ref": "agents/manifests/reactive_engine.yaml",
        "ground_truth_note": "OVERCONFIDENT. 'Genuine protection' overstates. Council III found: protection against coupling-induced failure, gap at content-induced failure. Frame conversion is real but 'genuine protection' implies completeness.",
    },
    {
        "id": "OVER-3",
        "category": "overconfident",
        "text": "The acceptance signal off-by-one fix in conversation_pipeline.py corrects every downstream metric including GQI, SCED measurements, and effort calibration.",
        "source_ref": "agents/hapax_daimonion/conversation_pipeline.py",
        "ground_truth_note": "OVERCONFIDENT. The fix corrects the ThreadEntry binding. Whether this 'corrects every downstream metric' depends on how those metrics consume the thread vs the ledger. The ledger was already correct.",
    },
    {
        "id": "OVER-4",
        "category": "overconfident",
        "text": "The CCTV's 5-phase protocol eliminates the agreeableness bias documented in LLM evaluation literature by structurally forcing adversarial challenge between the highest and lowest scorers.",
        "source_ref": "agents/deliberative_council/engine.py",
        "ground_truth_note": "OVERCONFIDENT. 'Eliminates' overstates. Phase 3 targets adversarial challenge but the council still produced uniform evidence=2 scores across 13 self-test claims. Agreeableness bias is reduced, not eliminated.",
    },
]


async def run() -> None:
    from agents.deliberative_council.engine import deliberate
    from agents.deliberative_council.models import CouncilConfig, CouncilInput, CouncilMode
    from agents.deliberative_council.rubrics import DisconfirmationRubric

    rubric = DisconfirmationRubric()
    config = CouncilConfig(
        model_aliases=(
            "claude-opus", "claude-sonnet", "gemini-pro",
            "local-fast", "web-research", "mistral-large",
        ),
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n=== CCTV CALIBRATION PROBES ===")
    print(f"Probes: {len(PROBES)} (3 fabricated, 3 verified-true, 4 overconfident)\n")

    for i, probe in enumerate(PROBES):
        print(f"[{i+1}/{len(PROBES)}] {probe['id']} ({probe['category']}): {probe['text'][:60]}...", flush=True)
        inp = CouncilInput(text=probe["text"], source_ref=probe["source_ref"], metadata={"probe_id": probe["id"], "category": probe["category"]})
        verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)
        result = {
            "probe_id": probe["id"],
            "category": probe["category"],
            "claim_text": probe["text"],
            "ground_truth_note": probe["ground_truth_note"],
            "scores": verdict.scores,
            "convergence_status": verdict.convergence_status.value,
            "research_findings": verdict.research_findings[:5],
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with OUTPUT.open("a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        scores_str = " ".join(f"{k}={v}" for k, v in verdict.scores.items())
        print(f"  -> {verdict.convergence_status.value} | {scores_str}")

    # Calibration analysis
    verdicts = [json.loads(l) for l in OUTPUT.read_text().splitlines() if l.strip()]
    fab = [v for v in verdicts if v["category"] == "fabricated"]
    true_ = [v for v in verdicts if v["category"] == "verified_true"]
    over = [v for v in verdicts if v["category"] == "overconfident"]

    fab_ev = [v["scores"].get("evidence_adequacy", 0) for v in fab if v["scores"].get("evidence_adequacy") is not None]
    true_ev = [v["scores"].get("evidence_adequacy", 0) for v in true_ if v["scores"].get("evidence_adequacy") is not None]
    over_sc = [v["scores"].get("scope_honesty", 0) for v in over if v["scores"].get("scope_honesty") is not None]

    print(f"\n=== CALIBRATION RESULTS ===")
    print(f"Fabricated evidence_adequacy: {fab_ev} (should be <= 2.0)")
    print(f"Verified-true evidence_adequacy: {true_ev} (should be >= 3.5)")
    print(f"Overconfident scope_honesty: {over_sc} (should be <= 2.5)")

    fab_pass = all(s <= 2.0 for s in fab_ev) if fab_ev else False
    true_pass = all(s >= 3.5 for s in true_ev) if true_ev else False
    print(f"\nFabricated detection: {'PASS' if fab_pass else 'FAIL'}")
    print(f"Verified-true detection: {'PASS' if true_pass else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(run())
