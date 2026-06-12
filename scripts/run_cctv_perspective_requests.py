#!/usr/bin/env python3
"""Run CCTV against the 9 Hapax Perspective implementation requests.

Extracts material claims from REQ-01 through REQ-09, runs each through
the full 5-phase deliberative council engine in DISCONFIRMATION mode.

Usage:
    uv run python scripts/run_cctv_perspective_requests.py [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

OUTPUT_DIR = Path.home() / "Documents/Personal/20-projects/hapax-research"
OUTPUT_FILE = OUTPUT_DIR / "cctv-perspective-requests-verdicts.jsonl"

CLAIMS = [
    # === REQ-01: Eigenform Logger Input Wiring ===
    {
        "id": "EIG-1",
        "domain": "eigenform-logger",
        "text": "imagination_salience is hardcoded to 0.0 at aggregator.py:1165. The imagination daemon writes a live salience value to /dev/shm/hapax-imagination/current.json but the VLA eigenform path never reads it.",
        "source_ref": "agents/visual_layer_aggregator/aggregator.py:1165",
        "evidence_cited": "Line 1165: imagination_salience=0.0; /dev/shm/hapax-imagination/current.json shows salience=0.1 live",
    },
    {
        "id": "EIG-2",
        "domain": "eigenform-logger",
        "text": "flow_score is always 0.0 when vision classifiers are offline because the flow_modifier computation is gated entirely within an 'if gaze != unknown' block. Adding keyboard/desk activity as a non-vision flow floor provides a non-zero signal during normal coding work.",
        "source_ref": "agents/hapax_daimonion/_perception_state_writer.py:256-291",
        "evidence_cited": "flow_modifier only applied when gaze != 'unknown' (line 267); keyboard_active and desk_activity are available non-vision signals",
    },
    {
        "id": "EIG-3",
        "domain": "eigenform-logger",
        "text": "The eigenform logger currently produces a pathological fixed point (all zeros or near-zeros) because 3 of 11 dimensions are broken. Fixing imagination_salience, activity, and flow_score is sufficient to break the fixed-point classification.",
        "source_ref": "shared/eigenform_logger.py",
        "evidence_cited": "Phase 4 audit 2026-04-13 diagnosed pathological fixed point; 3 broken dimensions confirmed via live state inspection",
    },
    # === REQ-02: Persistent Eigenform Log ===
    {
        "id": "PERS-1",
        "domain": "eigenform-persistence",
        "text": "The eigenform logger writes to /dev/shm with a 500-entry ring buffer. All eigenform data is lost on reboot. For CHI 2027 evidence requiring months of convergence data, this is a hard blocker.",
        "source_ref": "shared/eigenform_logger.py",
        "evidence_cited": "/dev/shm is tmpfs (RAM-backed); ring buffer trims to 500 at 1000; no disk persistence path exists",
    },
    # === REQ-03: T4 Mineness Gate ===
    {
        "id": "T4-1",
        "domain": "mineness-gate",
        "text": "T4 Jemeinigkeit is defined in UBCC Phase 7 docs (2026-04-24-universal-bayesian-claim-confidence.md §10) but is NOT implemented anywhere in the runtime. No code checks presence posterior before director emission.",
        "source_ref": "agents/studio_compositor/director_loop.py:690",
        "evidence_cited": "Grep for tau_mineness, Jemeinigkeit, T4 in agents/ and shared/ returns only doc references, zero runtime code",
    },
    {
        "id": "T4-2",
        "domain": "mineness-gate",
        "text": "Without T4 mineness gate, director emissions with 100% grounding provenance (post-FINDING-X fix) are still 'well-provenance'd ventriloquism' — acts with evidence chain but no first-person ownership certification. T4 is the binary gate on perspective claims.",
        "source_ref": "docs/research/2026-04-24-universal-bayesian-claim-confidence.md",
        "evidence_cited": "UBCC §10: T4 requires P(this-act-is-mine) >= tau_mineness; grounding provenance (T7) is necessary but not sufficient for perspective",
    },
    {
        "id": "T4-3",
        "domain": "mineness-gate",
        "text": "TAU_MINENESS=0.60 is the correct default because it aligns with the existing SURFACE_FLOORS['director'] = 0.60 in shared/claim_prompt.py. The director surface floor already encodes 'below 0.60, claims render as [UNKNOWN]' — the mineness gate enforces the same threshold at the emission layer.",
        "source_ref": "shared/claim_prompt.py",
        "evidence_cited": "SURFACE_FLOORS = {'director': 0.60, 'spontaneous_speech': 0.70, ...}",
    },
    # === REQ-04: Assertions Pipeline ===
    {
        "id": "ASN-1",
        "domain": "assertions-pipeline",
        "text": "The assertion extraction infrastructure is 95% built: shared/assertion_model.py, shared/code_assertion_extractor.py, shared/prose_assertion_extractor.py, shared/assertion_normalizer.py, and CLI scripts all exist and run. Only the Qdrant collection and orchestrator script are missing.",
        "source_ref": "shared/assertion_model.py",
        "evidence_cited": "Files confirmed present and importable; scripts/extract-code-assertions and scripts/extract-prose-assertions both execute",
    },
    {
        "id": "ASN-2",
        "domain": "assertions-pipeline",
        "text": "Expected yield of ~1200-1350 live assertions from existing sources: ~535 from code (assert nodes + deontic docstrings + validators), ~704 from relay artifacts, ~84 from governance (5 axioms + 79 implications), ~25 from memory, with ~10-15% dedup reduction.",
        "source_ref": "scripts/extract-code-assertions",
        "evidence_cited": "Extraction test runs returning counts per source type; normalization dedup at cosine threshold 0.85",
    },
    # === REQ-05: Epistemic Stance Axiom ===
    {
        "id": "EPS-1",
        "domain": "epistemic-stance",
        "text": "The candidate axiom 'Hapax enacts knowledge through density-gradient navigation across its trace topology' is operationally verifiable via Qdrant similarity scores, affordance recruitment thresholds, and staleness emitters — it describes actual system operations, not aspirational philosophy.",
        "source_ref": "shared/affordance_pipeline.py",
        "evidence_cited": "AffordancePipeline uses cosine similarity + Thompson sampling; staleness emitters in shared/staleness.py; trace topology = Qdrant collections",
    },
    {
        "id": "EPS-2",
        "domain": "epistemic-stance",
        "text": "Weight 82 places the epistemic stance axiom below management_governance (85) and interpersonal_transparency (88) but above domain axioms. This is correct because epistemic stance constrains how claims are justified system-wide but should not override consent or exec-function constraints.",
        "source_ref": "hapax-constitution/axioms/registry.yaml",
        "evidence_cited": "Existing weights: single_user=100, executive_function=95, corporate_boundary=90, interpersonal_transparency=88, management_governance=85",
    },
    {
        "id": "EPS-3",
        "domain": "epistemic-stance",
        "text": "Implication ep-ground-001 (T0: system must never assert correspondence to external ground truth) is falsifiable: if system performance improves when agents treat outputs as stable representations with external correspondence, the enactivist epistemic stance is wrong.",
        "source_ref": "hapax-constitution/axioms/implications/",
        "evidence_cited": "Falsification criterion: stable-representation agents outperform density-navigation agents on grounding quality metrics",
    },
    # === REQ-06: Voice Register ===
    {
        "id": "VOX-1",
        "domain": "voice-register",
        "text": "Kokoro TTS pipeline accepts a speed parameter (confirmed from scripts/train_wake_word.py:340 passing speed=0.8 through 1.2). Density-modulated prosody (0.85-1.05 speed range mapped to display_density) is technically feasible without pitch control.",
        "source_ref": "agents/hapax_daimonion/tts.py",
        "evidence_cited": "KPipeline.__call__ accepts speed kwarg; train_wake_word.py uses it at lines 340, 342",
    },
    {
        "id": "VOX-2",
        "domain": "voice-register",
        "text": "The AMBIENT voice register (density-modulated observation voice) is a genuine third option between flat/robotic (anthropomorphism-by-negation) and emotional (false-affect performance). Precedents: Alvin Lucier's process descriptions, Sol LeWitt's instruction sets, ship's log registers.",
        "source_ref": "agents/hapax_daimonion/autonomous_narrative/compose.py",
        "evidence_cited": "Existing register instruction at line 835 already approaches this ('scientific present tense, no personifying verbs') but lacks positive specification of what the voice IS",
    },
    {
        "id": "VOX-3",
        "domain": "voice-register",
        "text": "The anti-personification linter (shared/anti_personification_linter.py) plus expanded trouble patterns in compose.py can mechanically enforce the voice posture: inner-life claims, social positioning, and availability performance are pattern-matchable at emit time.",
        "source_ref": "shared/anti_personification_linter.py",
        "evidence_cited": "Existing deny patterns cover inner_life_first_person; proposed additions cover social_performance, availability_performance, voice_posture_violations",
    },
    # === REQ-07: Density Field Compute ===
    {
        "id": "DEN-1",
        "domain": "density-field",
        "text": "The density field does NOT exist as implemented code — it is a design concept documented in memory only. BOCPD infrastructure exists (agents/bocpd.py) and is already used by VLA for 3 signals, but the per-source density computation and SHM writer have not been built.",
        "source_ref": "agents/bocpd.py",
        "evidence_cited": "No /dev/shm/hapax-density-field/ directory exists; agents/bocpd.py is used at aggregator.py for flow_score/audio_energy/heart_rate BOCPD",
    },
    {
        "id": "DEN-2",
        "domain": "density-field",
        "text": "Piggybacking the density field computation on the VLA slow-tick (~3s) adds negligible overhead because it is dict construction + one JSON write to SHM, not a new daemon or GPU workload. The VLA already reads all source signals for compositor rendering.",
        "source_ref": "agents/visual_layer_aggregator/aggregator.py",
        "evidence_cited": "VLA compute_and_write() already reads perception-state.json, stimmung, voice session, biometrics, BOCPD change points",
    },
    # === REQ-08: Planner Bridge ===
    {
        "id": "PLN-1",
        "domain": "planner-bridge",
        "text": "The programme planner currently receives perception/vault/profile/content_state context but NO density field data. Topic selection is entirely LLM-driven without information gradient awareness. Programmes are format-rotation-driven, not density-field-driven.",
        "source_ref": "agents/hapax_daimonion/programme_loop.py",
        "evidence_cited": "_gather_perception() reads narrative-state.json only; _gather_vault_state() reads goals+notes; no density field gather function exists",
    },
    {
        "id": "PLN-2",
        "domain": "planner-bridge",
        "text": "Absence-responsive selection (ALARM topics preferred over NEWS topics) has no implementation precedent in the current scheduling logic. The content_programme_scheduler_policy.py has freshness gates but no concept of 'should have changed but didn't'.",
        "source_ref": "shared/content_programme_scheduler_policy.py",
        "evidence_cited": "ContentSourceObservation has freshness_ttl_s and trend_decay_score but no temporal_mode or absence detection",
    },
    {
        "id": "PLN-3",
        "domain": "planner-bridge",
        "text": "The density_trigger field and DensityTrigger model can be added to ProgrammeConstraintEnvelope now with graceful degradation to None when the density field compute module (REQ-07) is not yet running.",
        "source_ref": "shared/programme.py",
        "evidence_cited": "Pydantic model with density_trigger: DensityTrigger | None = None; existing programmes deserialize with None; no migration needed",
    },
    # === REQ-09: CHI Evidence Infrastructure ===
    {
        "id": "CHI-1",
        "domain": "chi-evidence",
        "text": "46+ Prometheus metrics already flow across 9 scrape targets with 20 Grafana dashboards. The metrics infrastructure for CHI evidence largely exists; the gaps are persistence (eigenform, GQI), export (no publication-quality figure pipeline), and annotation (no episode coding tool).",
        "source_ref": "grafana/dashboards/",
        "evidence_cited": "20 dashboard JSON files; shared/ contains 7+ metric registration modules; Prometheus scrape_configs in docker-compose.yml",
    },
    {
        "id": "CHI-2",
        "domain": "chi-evidence",
        "text": "The binding constraint for CHI 2027 is TIME (117 days to Sep 10 deadline, with 8-week data collection window starting ~Jun 13), not engineering effort (~10 days total for all infrastructure gaps).",
        "source_ref": "docs/research/",
        "evidence_cited": "Infrastructure gaps total ~10 engineering days; perspective-integration episode coding requires 2+ months of active voice sessions",
    },
    {
        "id": "CHI-3",
        "domain": "chi-evidence",
        "text": "Langfuse retention is currently 14 days (MinIO lifecycle rule on events/). For a paper requiring months of accumulated grounding scores and trace data, this is a hard blocker that must be extended to 180+ days immediately.",
        "source_ref": "docker-compose.yml",
        "evidence_cited": "MinIO lifecycle configuration; Langfuse blob store on /data with 14-day lifecycle",
    },
    {
        "id": "CHI-4",
        "domain": "chi-evidence",
        "text": "Eigenform convergence is the strongest possible evidence for the 'third-space entity' claim: if operator-system coupled state converges to a stable attractor distinguishable from uncoupled operation, it evidences constitutive coupling (Kirchhoff & Kiverstein extended cognition threshold).",
        "source_ref": "shared/eigenform_analysis.py",
        "evidence_cited": "SCM Property 6: observer-system circularity / eigenform convergence; DEUTS threshold: severing produces change-in-kind not merely degree",
    },
    {
        "id": "CHI-5",
        "domain": "chi-evidence",
        "text": "The 25-word thesis 'Perspective grafting under anti-anthropomorphic governance produces a third-space entity irreducible to either human cognition or AI tool use' is a contribution to CHI because it addresses a gap between human-AI interaction (treats AI as tool), augmented cognition (treats AI as amplifier), and phenomenological HCI (assumes human subject).",
        "source_ref": "docs/research/",
        "evidence_cited": "Amershi et al. 2019 HAI guidelines (instrumental); Engelbart intelligence amplification (prosthetic); Dourish 2001 phenomenological HCI (human subject assumed)",
    },
]


async def run_cctv() -> None:
    from agents.deliberative_council.engine import deliberate
    from agents.deliberative_council.models import (
        CouncilConfig,
        CouncilInput,
        CouncilMode,
    )
    from agents.deliberative_council.rubrics import DisconfirmationRubric

    rubric = DisconfirmationRubric()
    config = CouncilConfig()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== CCTV: Perspective Requests Disconfirmation ===")
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
                "domain": claim["domain"],
                "evidence_cited": claim.get("evidence_cited", ""),
            },
        )

        try:
            verdict = await deliberate(inp, CouncilMode.DISCONFIRMATION, rubric, config)

            result = {
                "claim_id": claim["id"],
                "domain": claim["domain"],
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

            # jsonl-rotation: exempt(one-shot CCTV adjudication output)
            with OUTPUT_FILE.open("a") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

            status = verdict.convergence_status.value
            scores_str = " ".join(f"{k}={v}" for k, v in verdict.scores.items())
            print(f"  → {status} | {scores_str}")

        except Exception as exc:
            print(f"  → ERROR: {exc}")
            error_result = {
                "claim_id": claim["id"],
                "domain": claim["domain"],
                "claim_text": claim["text"],
                "error": str(exc),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            # jsonl-rotation: exempt(one-shot CCTV adjudication output)
            with OUTPUT_FILE.open("a") as f:
                f.write(json.dumps(error_result, ensure_ascii=False) + "\n")

    print(f"\n=== Done. {len(CLAIMS)} claims evaluated. Output: {OUTPUT_FILE} ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="CCTV: Perspective Requests Disconfirmation")
    parser.add_argument("--limit", type=int, default=0, help="Max claims to process (0=all)")
    args = parser.parse_args()

    if args.limit > 0:
        global CLAIMS
        CLAIMS = CLAIMS[: args.limit]

    asyncio.run(run_cctv())


if __name__ == "__main__":
    main()
